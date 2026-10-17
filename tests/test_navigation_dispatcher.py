"""Real Dispatcher/FSM login and navigation; all Telegram methods are mocked."""
import ast
from pathlib import Path
import pytest
from test_explicit_bootstrap import run_isolated


@pytest.mark.parametrize('layer',['handlers','services','repositories'])
def test_navigation_module_boundaries(layer):
    source=(Path(__file__).resolve().parents[1]/'erpbot'/layer/'navigation.py').read_text(encoding='utf-8')
    for node in ast.walk(ast.parse(source)):
        if isinstance(node,ast.ImportFrom):
            assert 'runtime' not in (node.module or '')
            assert all(alias.name!='*' for alias in node.names)
        if layer!='repositories' and isinstance(node,ast.Attribute):
            assert node.attr not in ('execute','executemany','executescript')


def test_login_menus_and_group_policy_through_dispatcher(tmp_path):
    run_isolated(tmp_path,r'''
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock
from erpbot.handlers.navigation import create_router
assert 'erpbot.core.runtime' not in sys.modules
assert list(Path.cwd().iterdir())==[]
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
Bot.leave_chat=AsyncMock()

async def main():
    app=initialize_runtime(Settings.from_env({'BOT_TOKEN':'123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk',
        'FERNET_KEY':Fernet.generate_key().decode(),'GROUP_ID':'-100999'},data_directory=Path.cwd()),configure_logging=False)
    runtime.init_db()
    with runtime.get_connection() as conn:
        conn.executemany('INSERT INTO staff_mapping(staff_name,telegram_user_id,phone_number,role,is_active) VALUES(?,?,?,?,?)',[
            ('Admin',101,None,'main_admin',1),('Disabled',606,'09120000006','main_admin',0),
            ('<New>',None,'+989120000007','staff',1)])
    register_handlers()
    sequence=0
    async def feed(*,user=707,text=None,data=None,contact=None,group=None):
        nonlocal sequence
        sequence+=1
        for mock in (Message.answer,Message.edit_text,CallbackQuery.answer): mock.reset_mock()
        event={'message_id':sequence,'date':0,'chat':{'id':group or user,'type':'supergroup' if group else 'private'},
               'from':{'id':user,'is_bot':False,'first_name':'Test'}}
        if contact:
            event['contact']={'phone_number':'۰۹۱۲۰۰۰۰۰۰۷','first_name':'Contact','user_id':contact}
        else: event['text']=text or 'Menu'
        update={'update_id':sequence}
        if data: update['callback_query']={'id':str(sequence),'from':event['from'],'chat_instance':'test','data':data,'message':event}
        else: update['message']=event
        await app.dispatcher.feed_update(app.bot,Update.model_validate(update))
    ctx=app.dispatcher.fsm.get_context(bot=app.bot,chat_id=707,user_id=707)
    await feed(text='/start')
    assert await ctx.get_state()=='Form:waiting_for_phone'
    assert Message.answer.await_args.kwargs['reply_markup'].keyboard[0][0].request_contact
    await feed(contact=808)
    assert await ctx.get_state() is None
    with runtime.get_connection() as conn:
        assert conn.execute("SELECT telegram_user_id FROM staff_mapping WHERE staff_name='<New>'").fetchone()[0] is None
    await feed(text='/start')
    await feed(contact=707)
    assert await ctx.get_state() is None
    assert '&lt;New&gt;' in Message.answer.await_args.args[0]
    with runtime.get_connection() as conn:
        assert conn.execute("SELECT telegram_user_id FROM staff_mapping WHERE staff_name='<New>'").fetchone()[0]==707
    assert runtime.get_staff_info_by_telegram_id(707)[1]=='<New>'
    assert runtime.get_staff_info_by_telegram_id(999)[0] is None
    for data,expected in [('menu_admin_finance','req_leave'),('menu_assets_purchase','req_asset')]:
        await feed(data=data)
        buttons=Message.edit_text.await_args.kwargs['reply_markup'].inline_keyboard
        assert expected in [row[0].callback_data for row in buttons]
    await ctx.set_state('Form:waiting_for_phone')
    await feed(data='back_to_main')
    assert await ctx.get_state() is None
    admin_ctx=app.dispatcher.fsm.get_context(bot=app.bot,chat_id=101,user_id=101)
    await admin_ctx.set_state('AdminForm:add_staff_name')
    await feed(user=101,text='/start')
    assert await admin_ctx.get_state() is None
    assert 'admin_panel' in [row[0].callback_data for row in Message.answer.await_args.kwargs['reply_markup'].inline_keyboard]
    with runtime.get_connection() as conn:
        conn.execute("UPDATE staff_mapping SET role='staff' WHERE telegram_user_id=101")
    await feed(user=101,data='back_to_main')
    assert 'admin_panel' not in [row[0].callback_data for row in Message.edit_text.await_args.kwargs['reply_markup'].inline_keyboard]
    Message.edit_text.side_effect=RuntimeError('Old menu cannot be edited')
    await feed(data='back_to_main')
    Message.answer.assert_awaited_once()
    Message.edit_text.side_effect=None
    await feed(user=606,text='/start')
    assert 'مسدود' in Message.answer.await_args.args[0]
    await feed(user=999,text='/start',group=-100555)
    assert 'چت خصوصی' in Message.answer.await_args.args[0]
    assert 'reply_markup' not in Message.answer.await_args.kwargs
    await feed(text='/start reminder_-100999_77')
    assert await ctx.get_state()=='Form:interactive_reminder_type'
    await feed(text='/start')
    assert await ctx.get_state() is None
    with runtime.get_connection() as conn:
        conn.execute('UPDATE staff_mapping SET is_active=0 WHERE telegram_user_id=707')
    await feed(data='menu_admin_finance')
    Message.edit_text.assert_not_awaited()
    assert CallbackQuery.answer.await_args.kwargs['show_alert']
    bot_user={'id':123456789,'is_bot':True,'first_name':'Test Bot'}
    event={'chat':{'id':-100555,'type':'supergroup'},'from':{'id':999,'is_bot':False,'first_name':'Inviter'},'date':0,
           'old_chat_member':{'status':'left','user':bot_user},'new_chat_member':{'status':'member','user':bot_user}}
    Bot.send_message.side_effect=RuntimeError('Private messages blocked')
    await app.dispatcher.feed_update(app.bot,Update.model_validate({'update_id':1000,'my_chat_member':event}))
    Bot.leave_chat.assert_awaited_once_with(chat_id=-100555)
    Bot.send_message.side_effect=None
    await app.close()
asyncio.run(main())
''')
