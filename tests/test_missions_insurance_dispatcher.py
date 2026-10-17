"""Real mission and insurance FSM, legacy actions and seven-day alerts without network."""
import os
from pathlib import Path
import subprocess
import sys


def test_missions_and_insurance_through_dispatcher(tmp_path):
    script=r'''
import asyncio
import sqlite3
from pathlib import Path
import jdatetime
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery,EditMessageText,SendMessage
from aiogram.types import Message,Update,User
from cryptography.fernet import Fernet
from erpbot.bootstrap import initialize_runtime
from erpbot.core import runtime
from erpbot.core.settings import Settings
from erpbot.loader import register_handlers
from erpbot.scheduler.insurance import deliver_alerts

class OfflineSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls=[]
    async def close(self): pass
    async def make_request(self,bot,method,timeout=None):
        self.calls.append(method)
        if isinstance(method,AnswerCallbackQuery): return True
        assert isinstance(method,(SendMessage,EditMessageText)),type(method)
        return Message(message_id=100+len(self.calls),date=0,chat={'id':method.chat_id,'type':'private'},text=method.text)
    async def stream_content(self,*args,**kwargs):
        raise AssertionError('No network')
        yield b''

async def main():
    app=initialize_runtime(Settings.from_env({
        'BOT_TOKEN':'123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk',
        'FERNET_KEY':Fernet.generate_key().decode(),'GROUP_ID':'-100999',
    },data_directory=Path.cwd()),configure_logging=False)
    runtime.init_db()
    with runtime.get_connection() as conn:
        conn.executemany('INSERT INTO staff_mapping(staff_name,telegram_user_id,role) VALUES(?,?,?)',[
            ('Admin',101,'main_admin'),('Employee',202,'staff'),('Finance',404,'finance'),('Purchase',505,'purchase')])
        car=conn.execute("INSERT INTO user_assets(asset_type,details,is_active) VALUES('خودروی سازمانی','کد: CAR-01 | پلاک: A',1)").lastrowid
        conn.execute("INSERT INTO user_assets(asset_type,details,is_active) VALUES('خودروی سازمانی',?,1)",('کد: '+'خودرو'*30+' | پلاک: B',))
    register_handlers()
    session=OfflineSession()
    app.bot.session=session
    app.bot._me=User(id=123456789,is_bot=True,first_name='Bot',username='test_bot')
    sequence=0
    async def click(data,user=202):
        nonlocal sequence
        sequence+=1
        session.calls.clear()
        query={'id':str(sequence),'from':{'id':user,'is_bot':False,'first_name':'Test'},
            'chat_instance':'test','data':data,'message':{'message_id':10,'date':0,'chat':{'id':user,'type':'private'},
            'from':{'id':123456789,'is_bot':True,'first_name':'Bot'},'text':'Menu'}}
        await app.dispatcher.feed_update(app.bot,Update.model_validate({'update_id':sequence,'callback_query':query}))
    async def send(text,user=202):
        nonlocal sequence
        sequence+=1
        session.calls.clear()
        message={'message_id':sequence,'date':0,'chat':{'id':user,'type':'private'},
                 'from':{'id':user,'is_bot':False,'first_name':'Test'},'text':text}
        await app.dispatcher.feed_update(app.bot,Update.model_validate({'update_id':sequence,'message':message}))
    def requests():
        with runtime.get_connection() as conn: return conn.execute('SELECT * FROM requests ORDER BY id').fetchall()
    def policies():
        with runtime.get_connection() as conn: return conn.execute('SELECT * FROM vehicle_insurances ORDER BY id').fetchall()
    context=app.dispatcher.fsm.get_context(bot=app.bot,chat_id=202,user_id=202)
    await click('req_mission')
    await send('تهران <آزمایش>')
    await send('1405/12/30')
    assert await context.get_state()=='Form:waiting_for_mission_start_date'
    await send('۱۴۰۵/۷/۲۴')
    await send('1405/07/23')
    assert await context.get_state()=='Form:waiting_for_mission_end_date'
    await send('۱۴۰۵/۷/۲۵')
    assert '2 روز' in session.calls[0].text and '&lt;آزمایش&gt;' in session.calls[0].text
    await click('mission_submit_final')
    mission=requests()[-1]
    assert mission['start_date']=='1405/07/24' and mission['end_date']=='1405/07/25'
    assert await context.get_state() is None
    await click('approve_'+str(mission['id']),404)
    assert session.calls[-1].show_alert
    await click('approve_'+str(mission['id']),101)
    assert requests()[-1]['status']=='✅ تأیید شده قطعی'
    await click('approve_'+str(mission['id']),101)
    assert session.calls[-1].show_alert
    # Inactive account cannot advance a message step.
    await click('req_mission')
    with runtime.get_connection() as conn: conn.execute('UPDATE staff_mapping SET is_active=0 WHERE telegram_user_id=202')
    await send('نباید پذیرفته شود')
    assert 'فعال' in session.calls[0].text
    with runtime.get_connection() as conn: conn.execute('UPDATE staff_mapping SET is_active=1 WHERE telegram_user_id=202')
    # Ordinary users cannot start an insurance form even through forged legacy callback.
    await click('inselcar_NEW')
    assert session.calls[-1].show_alert
    await click('admin_add_insurance',404)
    buttons=[b for row in session.calls[0].reply_markup.inline_keyboard for b in row]
    assert all(len(b.callback_data.encode('utf-8'))<=64 for b in buttons)
    assert any(b.callback_data==f'insasset_{car}' for b in buttons)
    await click(f'insasset_{car}',404)
    await send('شرکت <الف>',404)
    await send('۱۴۰۵/۸/۱',404)
    with runtime.get_connection() as conn: conn.execute("UPDATE staff_mapping SET role='staff' WHERE telegram_user_id=404")
    await send('-',404)
    assert 'غیرمجاز' in session.calls[-1].text and policies()==[]
    with runtime.get_connection() as conn: conn.execute("UPDATE staff_mapping SET role='finance' WHERE telegram_user_id=404")
    await send('-',404)
    assert policies()[0]['third_party_date']=='1405/08/01' and policies()[0]['body_date']=='-'
    assert any(isinstance(call,SendMessage) and call.chat_id==-100999 and call.message_thread_id==73 for call in session.calls)
    # Old car buttons remain usable for an active car.
    await click('inselcar_CAR-01',505)
    assert 'CAR-01' in session.calls[0].text
    # Complete manual entry and keep a failed insert retryable.
    await click('inselcar_NEW',505)
    for text in ('CAR-NEW','خودرو جدید','پلاک جدید','بیمه جدید','1405/08/02'): await send(text,505)
    with runtime.get_connection() as conn:
        conn.execute("CREATE TRIGGER fail_insurance BEFORE INSERT ON vehicle_insurances BEGIN SELECT RAISE(ABORT,'failed'); END")
    try: await send('1405/08/03',505)
    except sqlite3.IntegrityError: pass
    else: raise AssertionError('Expected insert failure')
    assert len(policies())==1 and not session.calls
    with runtime.get_connection() as conn: conn.execute('DROP TRIGGER fail_insurance')
    await send('1405/08/03',505)
    assert len(policies())==2
    # Old selection is checked again at final persistence.
    await click(f'insasset_{car}',404)
    await send('شرکت',404)
    await send('1405/08/01',404)
    with runtime.get_connection() as conn: conn.execute('UPDATE user_assets SET is_active=0 WHERE id=?',(car,))
    await send('-',404)
    assert len(policies())==2 and 'خودروی فعال' in session.calls[-1].text
    session.calls.clear()
    await deliver_alerts(runtime.get_connection,app.bot,jdatetime.datetime(1405,7,24,12))
    alerts=[call for call in session.calls if isinstance(call,SendMessage)]
    assert len(alerts)==1 and alerts[0].chat_id==101 and 'شرکت &lt;الف&gt;' in alerts[0].text
    await app.close()

asyncio.run(main())
'''
    root=Path(__file__).resolve().parents[1]
    env=dict(os.environ,PYTHONPATH=str(root),PYTHONIOENCODING='utf-8')
    result=subprocess.run([sys.executable,'-c',script],cwd=tmp_path,env=env,capture_output=True,text=True,encoding='utf-8',timeout=60)
    assert result.returncode==0,result.stdout+result.stderr
