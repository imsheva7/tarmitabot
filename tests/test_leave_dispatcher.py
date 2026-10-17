"""Real Dispatcher, FSM, middleware and legacy request routing, with an offline bot."""
import os
from pathlib import Path
import subprocess
import sys


def test_full_leave_workflow_and_legacy_requests_through_dispatcher(tmp_path):
    script = r'''
import asyncio
from pathlib import Path
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery, EditMessageText, EditMessageReplyMarkup, SendMessage
from aiogram.types import Message, Update, User
from cryptography.fernet import Fernet
from erpbot.bootstrap import initialize_runtime
from erpbot.core import runtime
from erpbot.core.settings import Settings
from erpbot.loader import register_handlers

class OfflineSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls = []
        self.sequence = 1000
    async def close(self):
        pass
    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, AnswerCallbackQuery):
            return True
        assert isinstance(method,(SendMessage, EditMessageText, EditMessageReplyMarkup)), type(method)
        self.sequence += 1
        return Message(message_id=self.sequence,date=0,
            chat={'id':method.chat_id,'type':'private'},text=getattr(method,'text','') or 'Menu')
    async def stream_content(self, *args, **kwargs):
        raise AssertionError('Network disabled')
        yield b''

async def main():
    settings = Settings.from_env({
        'BOT_TOKEN':'123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk',
        'FERNET_KEY':Fernet.generate_key().decode(), 'GROUP_ID':'-100999',
    },data_directory=Path.cwd())
    app = initialize_runtime(settings,configure_logging=False)
    runtime.init_db()
    with runtime.get_connection() as conn:
        conn.executemany('INSERT INTO staff_mapping(staff_name,telegram_user_id,role,leave_balance) VALUES(?,?,?,?)',[
            ('Admin',101,'main_admin',5), ('Employee',202,'staff',5),
            ('Replacement <test>',303,'staff',5), ('Finance',404,'finance',5), ('Purchase',505,'purchase',5),
        ])
        replacement = conn.execute('SELECT staff_id FROM staff_mapping WHERE telegram_user_id=303').fetchone()[0]
    register_handlers()
    session = OfflineSession()
    app.bot.session = session
    app.bot._me = User(id=123456789,is_bot=True,first_name='Test Bot',username='test_bot')
    sequence = 0
    async def click(data,user=202,message_id=10,chat_id=None):
        nonlocal sequence
        sequence += 1
        session.calls.clear()
        query = {'id':str(sequence),'from':{'id':user,'is_bot':False,'first_name':'Test'},
                 'chat_instance':'test','data':data,'message':{
                    'message_id':message_id,'date':0,'chat':{'id':chat_id or user,'type':'private'},
                    'from':{'id':123456789,'is_bot':True,'first_name':'Bot'},'text':'Menu'}}
        await app.dispatcher.feed_update(app.bot,Update.model_validate({'update_id':sequence,'callback_query':query}))
    async def send(text,user=202):
        nonlocal sequence
        sequence += 1
        session.calls.clear()
        message = {'message_id':sequence+10,'date':0,'chat':{'id':user,'type':'private'},
                   'from':{'id':user,'is_bot':False,'first_name':'Test'},'text':text}
        await app.dispatcher.feed_update(app.bot,Update.model_validate({'update_id':sequence,'message':message}))
    def row(rid):
        with runtime.get_connection() as conn:
            return conn.execute('SELECT * FROM requests WHERE id=?',(rid,)).fetchone()
    def effects():
        with runtime.get_connection() as conn:
            return (conn.execute('SELECT leave_balance FROM staff_mapping WHERE telegram_user_id=202').fetchone()[0],
                    conn.execute('SELECT COUNT(*) FROM leave_ledger').fetchone()[0],
                    conn.execute('SELECT COUNT(*) FROM request_effects').fetchone()[0])
    async def form(kind='estheghaghi',repl=True,start='۱۴۰۵/۰۷/۲۵',end='۱۴۰۵/۰۷/۲۶'):
        await click('req_leave')
        context = app.dispatcher.fsm.get_context(bot=app.bot,chat_id=202,user_id=202)
        assert await context.get_state() == 'Form:waiting_for_leave_type'
        await click('ltype_'+kind)
        if kind == 'saati':
            await send(start)
            await send('۰۹:۰۰ تا ۱۳:۰۰')
        else:
            await send(start)
            await send(end)
        assert await context.get_state() == 'Form:waiting_for_replacement'
        await click('repl_'+(str(replacement) if repl else 'None'))
        assert await context.get_state() == 'Form:waiting_for_leave_preview'
        await click('leave_submit_final')
        assert await context.get_state() is None
        with runtime.get_connection() as conn:
            return conn.execute('SELECT MAX(id) FROM requests').fetchone()[0]

    rid = await form()
    assert row(rid)['location'] == '2.0'
    assert row(rid)['start_date'] == '1405/07/25'
    assert effects() == (5,0,0)
    await click('approve_'+str(rid),user=101)
    assert 'جانشین' in session.calls[-1].text
    await click('replapp_'+str(rid),user=202)
    assert session.calls[-1].show_alert
    await click('replapp_'+str(rid),user=303)
    admin_edit = next(c for c in session.calls if isinstance(c,EditMessageText) and c.chat_id == -100999)
    assert '&lt;test&gt;' in admin_edit.text
    await click('approve_'+str(rid),user=404)
    assert effects() == (5,0,0)
    await click('approve_'+str(rid),user=101)
    assert effects() == (3,1,1)
    await click('approve_'+str(rid),user=101)
    assert effects() == (3,1,1)

    # Insufficient balance -> contextual second confirmation, cancel and old buttons.
    rid = await form(repl=False,end='۱۴۰۵/۰۸/۰۵')
    before = effects()
    await click('leaveoverride_'+str(rid),user=101)
    assert effects() == before
    await click('approve_'+str(rid),user=101)
    assert any(isinstance(c,SendMessage) and 'کسری' in c.text for c in session.calls)
    context = app.dispatcher.fsm.get_context(bot=app.bot,chat_id=101,user_id=101)
    saved = await context.get_data()
    warning = saved['leave_override_message_id']
    with runtime.get_connection() as conn:
        conn.execute("UPDATE staff_mapping SET role='staff' WHERE telegram_user_id=101")
    await click('leaveoverride_'+str(rid),user=101,message_id=warning)
    assert effects() == before and session.calls[-1].show_alert
    with runtime.get_connection() as conn:
        conn.execute("UPDATE staff_mapping SET role='main_admin' WHERE telegram_user_id=101")
    await click('leaveoverride_'+str(rid),user=101,message_id=warning-1)
    assert effects() == before
    await click('leavecancel_'+str(rid),user=101,message_id=warning)
    assert (await context.get_data())['leave_override_request_id'] is None
    await click('leaveoverride_'+str(rid),user=101,message_id=warning)
    assert effects() == before
    await click('approve_'+str(rid),user=101)
    warning = (await context.get_data())['leave_override_message_id']
    await click('leaveoverride_'+str(rid),user=101,message_id=warning)
    assert effects()[0] == before[0] - float(row(rid)['location'])
    assert effects()[1:] == (2,2)
    after = effects()
    await click('leaveoverride_'+str(rid),user=101,message_id=warning)
    assert effects() == after

    # Hourly leave never debits; employee cancellation and reason rejection use new handlers.
    rid = await form(kind='saati',repl=False)
    await click('approve_'+str(rid),user=101)
    assert effects() == after and 'تأیید شده قطعی' in row(rid)['status']
    rid = await form(kind='estelaji',repl=False)
    await click('cancel_'+row(rid)['req_code'],user=303)
    assert 'در انتظار' in row(rid)['status']
    await click('cancel_'+row(rid)['req_code'])
    assert 'لغو شده' in row(rid)['status']
    rid = await form(kind='without_pay',repl=False)
    await click('reject_'+str(rid),user=101)
    assert await context.get_state() == 'AdminForm:rejection_reason'
    await send('علت <آزمایش>',user=101)
    assert row(rid)['rejection_reason'] == 'علت <آزمایش>'
    assert await context.get_state() is None and effects() == after

    # Recheck activity during a form message, not just at the first callback.
    await click('req_leave')
    await click('ltype_estheghaghi')
    with runtime.get_connection() as conn:
        conn.execute('UPDATE staff_mapping SET is_active=0 WHERE telegram_user_id=202')
    await send('1405/07/25')
    assert len(session.calls) == 1 and 'فعال' in session.calls[0].text
    with runtime.get_connection() as conn:
        conn.execute('UPDATE staff_mapping SET is_active=1 WHERE telegram_user_id=202')
    await click('back_to_main')

    # Shared delivery and generic legacy decision callbacks still handle finance and purchase.
    def legacy_request(kind):
        with runtime.get_connection() as conn:
            rid = conn.execute("INSERT INTO requests(telegram_user_id,user_name,request_type,col1,col2,col3,status) VALUES(202,'Employee',?,'اطلاعات','شرح','جزئیات','⏳ در انتظار تأیید نهایی مدیریت')",(kind,)).lastrowid
            conn.execute('UPDATE requests SET req_code=? WHERE id=?',(f'REQ-1405-{rid:05d}',rid))
            return rid
    rid = legacy_request('مساعده')
    await click('approve_'+str(rid),user=101)
    assert 'تأیید شده قطعی' in row(rid)['status']
    assert any(isinstance(c,SendMessage) and c.chat_id == 404 and 'دستور پرداخت' in c.text for c in session.calls)
    await click('paid_'+str(rid),user=404)
    assert 'پرداخت شده' in row(rid)['status']
    await click('req_purchase')
    await send('کالای آزمایشی')
    await send('2')
    await send('شرح خرید')
    await click('purch_submit_final')
    with runtime.get_connection() as conn:
        rid = conn.execute('SELECT MAX(id) FROM requests').fetchone()[0]
    assert row(rid)['request_type'] == 'خرید ملزومات'
    assert row(rid)['admin_msg_id'] is not None
    await click('approve_'+str(rid),user=101)
    assert any(isinstance(c,SendMessage) and c.chat_id == 505 and 'دستور خرید' in c.text for c in session.calls)
    await click('bought_'+str(rid),user=505)
    assert 'خریداری شده' in row(rid)['status']
    rid = legacy_request('ماموریت')
    await click('reject_'+str(rid),user=101)
    await send('legacy rejection',user=101)
    assert row(rid)['rejection_reason'] == 'legacy rejection'
    rid = legacy_request('ماموریت')
    await click('cancel_'+row(rid)['req_code'])
    assert 'لغو شده' in row(rid)['status']
    assert effects() == after
    for payload in ('approve_'+'9'*100,'replapp_invalid','leavecancel_²','leaveoverride_-1'):
        await click(payload,user=101)
        assert session.calls[-1].show_alert
    await app.close()

asyncio.run(main())
'''
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, PYTHONPATH=str(root), PYTHONIOENCODING="utf-8")
    result = subprocess.run([sys.executable,"-c",script],cwd=tmp_path,env=env,
                            capture_output=True,text=True,encoding="utf-8",timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
