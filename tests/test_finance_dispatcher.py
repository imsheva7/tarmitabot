"""Real financial FSM, photo invoices, quotas and callbacks without Telegram network."""
import os
from pathlib import Path
import subprocess
import sys


def test_finance_and_purchase_forms_through_real_dispatcher(tmp_path):
    script=r'''
import asyncio
from pathlib import Path
import jdatetime
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery,EditMessageText,EditMessageCaption,SendMessage,SendPhoto
from aiogram.types import Message,Update,User
from cryptography.fernet import Fernet
from erpbot.bootstrap import initialize_runtime
from erpbot.core import runtime
from erpbot.core.settings import Settings
from erpbot.loader import register_handlers
from erpbot.services.requests import create_request

class OfflineSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls=[]
        self.message_id=100
    async def close(self): pass
    async def make_request(self,bot,method,timeout=None):
        self.calls.append(method)
        if isinstance(method,AnswerCallbackQuery): return True
        assert isinstance(method,(SendMessage,EditMessageText,EditMessageCaption,SendPhoto)),type(method)
        self.message_id+=1
        return Message(message_id=self.message_id,date=0,chat={'id':method.chat_id,'type':'private'},
            text=getattr(method,'text',None),caption=getattr(method,'caption',None))
    async def stream_content(self,*args,**kwargs):
        raise AssertionError('No network')
        yield b''

async def main():
    app=initialize_runtime(Settings.from_env({
        'BOT_TOKEN':'123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk',
        'FERNET_KEY':Fernet.generate_key().decode(),'GROUP_ID':'-100999',
    },data_directory=Path.cwd()),configure_logging=False)
    runtime.init_db()
    runtime.get_current_tehran_time=lambda:jdatetime.datetime(1405,7,24,12,30)
    with runtime.get_connection() as conn:
        conn.executemany('INSERT INTO staff_mapping(staff_name,telegram_user_id,role) VALUES(?,?,?)',[
            ('Admin',101,'main_admin'),('Employee',202,'staff'),('Other',303,'staff'),
            ('Finance',404,'finance'),('Purchase',505,'purchase')])
    register_handlers()
    session=OfflineSession()
    app.bot.session=session
    app.bot._me=User(id=123456789,is_bot=True,first_name='Bot',username='test_bot')
    sequence=0
    async def click(data,user=202,photo=False):
        nonlocal sequence
        sequence+=1
        session.calls.clear()
        message={'message_id':10,'date':0,'chat':{'id':user,'type':'private'},
                 'from':{'id':123456789,'is_bot':True,'first_name':'Bot'},'text':'Menu'}
        if photo:
            message.pop('text')
            message['caption']='Invoice'
            message['photo']=[{'file_id':'invoice-file','file_unique_id':'unique','width':200,'height':200}]
        query={'id':str(sequence),'from':{'id':user,'is_bot':False,'first_name':'Test'},
               'chat_instance':'test','data':data,'message':message}
        await app.dispatcher.feed_update(app.bot,Update.model_validate({'update_id':sequence,'callback_query':query}))
    async def send(text=None,user=202,photo=False):
        nonlocal sequence
        sequence+=1
        session.calls.clear()
        message={'message_id':sequence,'date':0,'chat':{'id':user,'type':'private'},
                 'from':{'id':user,'is_bot':False,'first_name':'Test'}}
        if text is not None: message['text']=text
        if photo: message['photo']=[{'file_id':'invoice-file','file_unique_id':'unique','width':200,'height':200}]
        await app.dispatcher.feed_update(app.bot,Update.model_validate({'update_id':sequence,'message':message}))
    def rows():
        with runtime.get_connection() as conn:
            return conn.execute('SELECT * FROM requests ORDER BY id').fetchall()
    context=app.dispatcher.fsm.get_context(bot=app.bot,chat_id=202,user_id=202)
    await click('req_advance')
    await send('999999999999999999999999999999')
    assert await context.get_state()=='Form:waiting_for_advance_amount'
    await send('۹۰,۰۰۰,۰۰۰')
    assert await context.get_state()=='Form:waiting_for_advance_amount'
    await send('۱۰,۰۰۰,۰۰۰ ریال')
    await send('invalid card')
    assert await context.get_state()=='Form:waiting_for_advance_card'
    card='6037991234567890'
    await send(card)
    await send('دلیل <الف>')
    assert card not in session.calls[0].text
    assert await context.get_state()=='Form:waiting_for_advance_preview'
    await click('adv_submit_final')
    rid=rows()[-1]['id']
    assert await context.get_state() is None
    assert rows()[-1]['amount']==10_000_000
    assert card not in rows()[-1]['sensitive_data']
    assert card in runtime.decrypt_data(rows()[-1]['sensitive_data'])
    for call in session.calls:
        if isinstance(call,SendMessage): assert card not in call.text
    await click('paid_'+str(rid),404)
    assert session.calls[-1].show_alert and 'در انتظار' in rows()[-1]['status']
    await click('approve_'+str(rid),505)
    assert session.calls[-1].show_alert
    await click('approve_'+str(rid),101)
    secret_calls=[call for call in session.calls if isinstance(call,SendMessage) and card in call.text]
    assert len(secret_calls)==1 and secret_calls[0].chat_id==404
    await click('paid_'+str(rid),505)
    assert session.calls[-1].show_alert
    await click('paid_'+str(rid),404)
    assert 'پرداخت شده' in rows()[-1]['status']
    await click('paid_'+str(rid),404)
    assert session.calls[-1].show_alert
    # A second form checks the cap again after another request consumes it.
    await click('req_advance')
    await send('70000000')
    await send(card)
    await send('درخواست دوم')
    with runtime.get_connection() as conn:
        create_request(conn,202,'Employee','Telegram','مساعده','مبلغ','دلیل','محفوظ','-',
            year=1405,created_at='1405/07/24 12:30',month_tag='1405/07',amount=1)
    before=len(rows())
    await click('adv_submit_final')
    assert session.calls[-1].show_alert and len(rows())==before
    assert await context.get_state()=='Form:waiting_for_advance_preview'
    await click('back_to_main')
    # Photo invoices retain their attachment and edit the caption on both decisions.
    await click('req_petty')
    await send(photo=True)
    await send('۱۲۳,۰۰۰')
    await send('شرح فاکتور')
    assert isinstance(session.calls[0],SendPhoto)
    await click('petty_submit_final',photo=True)
    assert any(isinstance(call,SendPhoto) and call.message_thread_id==57 for call in session.calls)
    rid=rows()[-1]['id']
    await click('approve_'+str(rid),101,photo=True)
    assert any(isinstance(call,EditMessageCaption) for call in session.calls)
    await click('paid_'+str(rid),404,photo=True)
    assert any(isinstance(call,EditMessageCaption) for call in session.calls)
    assert 'پرداخت شده' in rows()[-1]['status']
    # Purchase form and exact completion role.
    await click('req_purchase')
    await send('کالای <آزمایشی>')
    await send('دو عدد')
    await send('شرح خرید')
    await click('purch_submit_final')
    rid=rows()[-1]['id']
    await click('approve_'+str(rid),101)
    assert any(isinstance(call,SendMessage) and call.chat_id==505 and 'دستور خرید' in call.text for call in session.calls)
    await click('paid_'+str(rid),101)
    assert session.calls[-1].show_alert and rows()[-1]['status']=='✅ تأیید شده قطعی'
    await click('bought_'+str(rid),404)
    assert session.calls[-1].show_alert
    await click('bought_'+str(rid),505)
    assert rows()[-1]['status']=='🛒 خریداری شده'
    # Account activity is checked in message steps, not just callbacks.
    await click('req_purchase')
    with runtime.get_connection() as conn:
        conn.execute('UPDATE staff_mapping SET is_active=0 WHERE telegram_user_id=202')
    await send('نباید پذیرفته شود')
    assert 'فعال' in session.calls[-1].text
    with runtime.get_connection() as conn:
        conn.execute('UPDATE staff_mapping SET is_active=1 WHERE telegram_user_id=202')
    for payload in ('paid_bad','bought_'+'9'*100,'paid_0'):
        await click(payload,101)
        assert session.calls[-1].show_alert
    await app.close()

asyncio.run(main())
'''
    root=Path(__file__).resolve().parents[1]
    env=dict(os.environ,PYTHONPATH=str(root),PYTHONIOENCODING='utf-8')
    result=subprocess.run([sys.executable,'-c',script],cwd=tmp_path,env=env,capture_output=True,text=True,encoding='utf-8',timeout=60)
    assert result.returncode==0,result.stdout+result.stderr
