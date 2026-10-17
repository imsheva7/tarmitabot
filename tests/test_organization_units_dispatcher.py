"""Real aiogram FSM, middleware and legacy navigation with no Telegram network."""
import os
from pathlib import Path
import subprocess
import sys


def test_units_router_through_dispatcher_and_legacy_navigation(tmp_path):
    script = r'''
import asyncio
from pathlib import Path
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage
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

    async def close(self):
        pass

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, AnswerCallbackQuery):
            return True
        assert isinstance(method, (SendMessage, EditMessageText)), type(method)
        return Message(message_id=10, date=0, chat={'id':101,'type':'private'}, text=method.text)

    async def stream_content(self, *args, **kwargs):
        raise AssertionError('Network disabled')
        yield b''


async def main():
    settings = Settings.from_env({
        'BOT_TOKEN':'123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk',
        'FERNET_KEY':Fernet.generate_key().decode(),
    }, data_directory=Path.cwd())
    app = initialize_runtime(settings, configure_logging=False)
    runtime.init_db()
    with runtime.get_connection() as conn:
        conn.executemany('INSERT INTO staff_mapping(staff_name,telegram_user_id,role) VALUES(?,?,?)',
                         [('Test admin',101,'main_admin'),('Test staff',202,'staff')])
    register_handlers()
    session = OfflineSession()
    app.bot.session = session
    app.bot._me = User(id=123456789, is_bot=True, first_name='Test Bot', username='test_bot')
    sequence = 0

    async def click(data, user=101):
        nonlocal sequence
        sequence += 1
        session.calls.clear()
        query = {'id':str(sequence),'from':{'id':user,'is_bot':False,'first_name':'Test'},
                 'chat_instance':'test','data':data,'message':{
                     'message_id':10,'date':0,'chat':{'id':user,'type':'private'},
                     'from':{'id':123456789,'is_bot':True,'first_name':'Bot'},'text':'Menu'}}
        await app.dispatcher.feed_update(app.bot, Update.model_validate({'update_id':sequence,'callback_query':query}))

    async def send(text, user=101):
        nonlocal sequence
        sequence += 1
        session.calls.clear()
        message = {'message_id':sequence+10,'date':0,'chat':{'id':user,'type':'private'},
                   'from':{'id':user,'is_bot':False,'first_name':'Test'},'text':text}
        await app.dispatcher.feed_update(app.bot, Update.model_validate({'update_id':sequence,'message':message}))

    await click('orgunits_menu', user=202)
    assert len(session.calls) == 1 and session.calls[0].show_alert
    await click('orgunits_menu')
    assert isinstance(session.calls[0], EditMessageText)
    await click('orgunits_pick_root')
    context = app.dispatcher.fsm.get_context(bot=app.bot, chat_id=101, user_id=101)
    assert await context.get_state() == 'OrganizationUnitForm:waiting_for_name'
    await send('واحد یکپارچه')
    assert isinstance(session.calls[0], SendMessage) and '✅' in session.calls[0].text
    assert await context.get_state() is None
    with runtime.get_connection() as conn:
        unit_id = conn.execute('SELECT unit_id FROM org_units WHERE unit_name=?', ('واحد یکپارچه',)).fetchone()[0]
        assert conn.execute('SELECT COUNT(*) FROM audit_logs').fetchone()[0] == 1
    await click('orgmem_staff_0')
    assert isinstance(session.calls[0], EditMessageText)
    assert any(button.callback_data.startswith('orgmem_person_')
               for row in session.calls[0].reply_markup.inline_keyboard for button in row)
    await click('orgunits_menu')
    await click('orgr_menu')
    assert any(button.callback_data == 'orgr_new'
               for row in session.calls[0].reply_markup.inline_keyboard for button in row)
    await click('orgr_new')
    assert await context.get_state() == 'OrganizationRoleForm:waiting_for_role_name'
    await send('سرپرست یکپارچه')
    assert await context.get_state() is None
    with runtime.get_connection() as conn:
        role_id = conn.execute('SELECT role_id FROM roles WHERE role_name=?', ('سرپرست یکپارچه',)).fetchone()[0]
        staff_id = conn.execute('SELECT staff_id FROM staff_mapping WHERE telegram_user_id=202').fetchone()[0]
        permission_id = conn.execute("SELECT permission_id FROM permissions WHERE permission_code='staff.view_unit'").fetchone()[0]
        assert conn.execute('SELECT COUNT(*) FROM role_permissions WHERE role_id=?',(role_id,)).fetchone()[0] == 0
    await click(f'orgr_toggle_{role_id}_{permission_id}_1')
    await click(f'orgmem_join_{staff_id}_{unit_id}')
    await click(f'orgr_set_{staff_id}_{unit_id}_{role_id}_1')
    await send('/unitstaff', user=202)
    assert session.calls[0].reply_markup.inline_keyboard[0][0].callback_data == f'unitstaff_view_{unit_id}'
    await send('/myunits', user=202)
    assert 'واحد یکپارچه' in session.calls[0].text
    await click(f'unitstaff_view_{unit_id}', user=202)
    assert isinstance(session.calls[0], EditMessageText) and 'Test staff' in session.calls[0].text
    await click(f'orgmem_confirm_{staff_id}_{unit_id}')
    await click(f'unitstaff_view_{unit_id}', user=202)
    assert isinstance(session.calls[0], EditMessageText)
    await click(f'orgmem_remove_{staff_id}_{unit_id}')
    await click(f'unitstaff_view_{unit_id}', user=202)
    assert len(session.calls) == 1 and session.calls[0].show_alert
    await click(f'orgmem_join_{staff_id}_{unit_id}')
    await click(f'unitstaff_view_{unit_id}', user=202)
    assert len(session.calls) == 1 and session.calls[0].show_alert
    await click(f'orgr_set_{staff_id}_{unit_id}_{role_id}_1')
    await click(f'orgr_active_{role_id}_0')
    await click(f'orgr_active_{role_id}_1')
    await click(f'unitstaff_view_{unit_id}', user=202)
    assert len(session.calls) == 1 and session.calls[0].show_alert
    await click(f'orgr_set_{staff_id}_{unit_id}_{role_id}_1')
    await click(f'orgr_toggle_{role_id}_{permission_id}_0')
    await click(f'unitstaff_view_{unit_id}', user=202)
    assert len(session.calls) == 1 and session.calls[0].show_alert
    await click(f'orgr_toggle_{role_id}_{permission_id}_1')
    await click(f'unitstaff_view_{unit_id}', user=202)
    assert isinstance(session.calls[0], EditMessageText)
    with runtime.get_connection() as conn:
        assert conn.execute('SELECT role FROM staff_mapping WHERE staff_id=?',(staff_id,)).fetchone()[0] == 'staff'
        before_audit = conn.execute('SELECT COUNT(*) FROM audit_logs').fetchone()[0]
    await click(f'orgunits_pick_{unit_id}')
    with runtime.get_connection() as conn:
        conn.execute("UPDATE staff_mapping SET role='staff' WHERE telegram_user_id=101")
    await send('نباید ثبت شود')
    assert 'فقط مدیر اصلی' in session.calls[0].text
    assert await context.get_state() is None
    with runtime.get_connection() as conn:
        assert conn.execute('SELECT COUNT(*) FROM org_units').fetchone()[0] == 1
        assert conn.execute('SELECT COUNT(*) FROM audit_logs').fetchone()[0] == before_audit
    await app.close()


asyncio.run(main())
'''
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, PYTHONPATH=str(root), PYTHONIOENCODING="utf-8")
    result = subprocess.run([sys.executable, "-c", script], cwd=tmp_path, env=env,
                            capture_output=True, text=True, encoding="utf-8", timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
