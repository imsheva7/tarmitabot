"""Real Dispatcher/FSM against synthetic data; Telegram methods are mocked."""
from test_explicit_bootstrap import run_isolated


def test_personnel_and_holidays_through_dispatcher(tmp_path):
    run_isolated(tmp_path,r'''
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock
import jdatetime
from aiogram import Bot
from aiogram.types import Message,CallbackQuery,Update
from cryptography.fernet import Fernet
from erpbot.bootstrap import initialize_runtime
from erpbot.core import runtime
from erpbot.core.settings import Settings
from erpbot.loader import register_handlers

Message.answer=AsyncMock()
Message.edit_text=AsyncMock()
CallbackQuery.answer=AsyncMock()
Bot.send_message=AsyncMock()

async def main():
    app=initialize_runtime(Settings.from_env({'BOT_TOKEN':'123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk',
        'FERNET_KEY':Fernet.generate_key().decode()},data_directory=Path.cwd()),configure_logging=False)
    runtime.init_db()
    runtime.get_current_tehran_time=lambda:jdatetime.datetime(1405,7,25,12)
    with runtime.get_connection() as conn:
        conn.executemany('INSERT INTO staff_mapping(staff_name,telegram_user_id,role) VALUES(?,?,?)',[
            ('Admin',101,'main_admin'),('Staff',202,'staff'),('Finance',404,'finance')])
    register_handlers()
    sequence=0
    async def feed(*,text=None,data=None,user=101):
        nonlocal sequence
        sequence+=1
        CallbackQuery.answer.reset_mock()
        Message.answer.reset_mock()
        Message.edit_text.reset_mock()
        event={'message_id':sequence,'date':0,'chat':{'id':user,'type':'private'},'text':text or 'Menu',
               'from':{'id':user,'is_bot':False,'first_name':'Test'}}
        update={'update_id':sequence}
        if data:
            update['callback_query']={'id':str(sequence),'from':event['from'],'chat_instance':'test','data':data,'message':event}
        else: update['message']=event
        await app.dispatcher.feed_update(app.bot,Update.model_validate(update))
    ctx=app.dispatcher.fsm.get_context(bot=app.bot,chat_id=101,user_id=101)
    await feed(data='adm_cat_staff',user=404)
    Message.edit_text.assert_awaited_once()
    await feed(data='admin_add_staff',user=404)
    assert CallbackQuery.answer.await_args.kwargs['show_alert']
    await feed(data='admin_add_staff')
    for text in ('New employee','۰۹۱۲۰۰۰۰۰۰۱'): await feed(text=text)
    await feed(data='role_staff')
    await feed(text='nan')
    assert await ctx.get_state()=='AdminForm:add_staff_balance'
    await feed(text='۵')
    with runtime.get_connection() as conn:
        conn.execute("UPDATE staff_mapping SET role='staff' WHERE telegram_user_id=101")
    await feed(text='-')
    assert 'غیرمجاز' in Message.answer.await_args.args[0]
    with runtime.get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM staff_mapping WHERE staff_name='New employee'").fetchone()[0]==0
        conn.execute("UPDATE staff_mapping SET role='main_admin' WHERE telegram_user_id=101")
    await feed(text='-')
    assert await ctx.get_state() is None
    with runtime.get_connection() as conn:
        sid=conn.execute("SELECT staff_id FROM staff_mapping WHERE staff_name='New employee'").fetchone()[0]
        assert conn.execute('SELECT SUM(change_amount) FROM leave_ledger WHERE staff_id=?',(sid,)).fetchone()[0]==5
        conn.execute('UPDATE staff_mapping SET leave_balance=10 WHERE staff_id=?',(sid,))
    await feed(data=f'editstaff_{sid}')
    await feed(data='edfield_leave_balance')
    await feed(text='۱۲')
    with runtime.get_connection() as conn:
        assert conn.execute('SELECT leave_balance FROM staff_mapping WHERE staff_id=?',(sid,)).fetchone()[0]==12
        assert conn.execute('SELECT SUM(change_amount) FROM leave_ledger WHERE staff_id=?',(sid,)).fetchone()[0]==12
        assert conn.execute("SELECT COUNT(*) FROM leave_ledger WHERE staff_id=? AND description='تطبیق مانده پیشین با دفتر مرخصی'",(sid,)).fetchone()[0]==1
    await feed(data='admin_holidays_menu')
    await feed(data='add_holiday_start')
    await feed(text='۱۴۰۵/۷/۲۵')
    with runtime.get_connection() as conn:
        conn.execute("UPDATE staff_mapping SET role='staff' WHERE telegram_user_id=101")
    await feed(text='تعطیل آزمایشی')
    with runtime.get_connection() as conn:
        assert conn.execute('SELECT COUNT(*) FROM holidays').fetchone()[0]==0
        conn.execute("UPDATE staff_mapping SET role='main_admin' WHERE telegram_user_id=101")
    await feed(text='تعطیل آزمایشی')
    await feed(data='delhol_1405/07/25',user=404)
    assert CallbackQuery.answer.await_args.kwargs['show_alert']
    await feed(data='delhol_1405/07/25')
    assert CallbackQuery.answer.await_count==1
    with runtime.get_connection() as conn:
        assert conn.execute('SELECT COUNT(*) FROM holidays').fetchone()[0]==0
        conn.execute("INSERT INTO user_assets(staff_id,staff_name,asset_type,is_active) VALUES(?,'New employee','Car',1)",(sid,))
    await feed(data=f'deact_{sid}')
    with runtime.get_connection() as conn:
        assert conn.execute('SELECT is_active FROM staff_mapping WHERE staff_id=?',(sid,)).fetchone()[0]==0
        assert conn.execute('SELECT is_active FROM user_assets WHERE staff_id=?',(sid,)).fetchone()[0]==0
        assert conn.execute('SELECT SUM(change_amount) FROM leave_ledger WHERE staff_id=?',(sid,)).fetchone()[0]==12
    for data in ('editstaff_bad','deact_'+str(2**64),'edfield_role'):
        await feed(data=data)
        assert CallbackQuery.answer.await_args.kwargs['show_alert']
    await app.close()

asyncio.run(main())
''')
