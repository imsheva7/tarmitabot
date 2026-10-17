"""Shared request callbacks through the real offline Dispatcher and FSM."""
import ast
from pathlib import Path
import pytest
from test_explicit_bootstrap import run_isolated


@pytest.mark.parametrize('layer',['handlers','services','repositories'])
def test_shared_decision_module_boundaries(layer):
    source=(Path(__file__).resolve().parents[1]/'erpbot'/layer/'request_decisions.py').read_text(encoding='utf-8')
    tree=ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node,ast.ImportFrom):
            assert 'runtime' not in (node.module or '')
            assert all(alias.name!='*' for alias in node.names)
        if layer!='repositories' and isinstance(node,ast.Attribute):
            assert node.attr not in ('execute','executemany','executescript')


def test_shared_decisions_through_real_dispatcher(tmp_path):
    run_isolated(tmp_path,r'''
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock
from erpbot.handlers.request_decisions import create_router
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
Message.edit_caption=AsyncMock()
CallbackQuery.answer=AsyncMock()
Bot.send_message=AsyncMock()
Bot.edit_message_text=AsyncMock()

async def main():
    app=initialize_runtime(Settings.from_env({'BOT_TOKEN':'123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk',
        'FERNET_KEY':Fernet.generate_key().decode()},data_directory=Path.cwd()),configure_logging=False)
    runtime.init_db()
    with runtime.get_connection() as conn:
        conn.executemany('INSERT INTO staff_mapping(staff_name,telegram_user_id,role,is_active) VALUES(?,?,?,?)',[
            ('Admin',101,'main_admin',1),('Staff',202,'staff',1),('Other',303,'staff',1),('Finance',404,'finance',1)])
        for rid,kind in [(1,'درخواست قدیمی'),(2,'مساعده'),(3,'ماموریت'),(4,'درخواست قدیمی'),(5,'مساعده'),(6,'درخواست قدیمی')]:
            conn.execute('INSERT INTO requests(id,telegram_user_id,user_name,req_code,request_type,status,admin_chat_id,admin_msg_id) VALUES(?,202,?,?,?,?,-100999,?)',
                (rid,'Staff',f'REQ-1405-{rid:05d}',kind,'در انتظار تأیید',rid))
    register_handlers()
    sequence=0
    async def feed(*,data=None,text=None,user=101,photo=False,content='Request'):
        nonlocal sequence
        sequence+=1
        for mock in (Message.answer,Message.edit_text,Message.edit_caption,CallbackQuery.answer,Bot.send_message,Bot.edit_message_text):
            mock.reset_mock()
        event={'message_id':sequence,'date':0,'chat':{'id':user,'type':'private'},
               'from':{'id':user,'is_bot':False,'first_name':'Test'}}
        if photo:
            event.update(caption=content,photo=[{'file_id':'test','file_unique_id':'unique','width':1,'height':1}])
        else: event['text']=text if text is not None else content
        update={'update_id':sequence}
        if data: update['callback_query']={'id':str(sequence),'from':event['from'],'chat_instance':'test','data':data,'message':event}
        else: update['message']=event
        await app.dispatcher.feed_update(app.bot,Update.model_validate(update))
    def status(rid):
        with runtime.get_connection() as conn:
            return conn.execute('SELECT status FROM requests WHERE id=?',(rid,)).fetchone()[0]
    ctx=app.dispatcher.fsm.get_context(bot=app.bot,chat_id=101,user_id=101)
    await feed(data='reject_1',user=404)
    assert CallbackQuery.answer.await_args.kwargs['show_alert'] and 'در انتظار' in status(1)
    await feed(data='reject_1')
    assert await ctx.get_state()=='AdminForm:rejection_reason'
    await feed(text='   ')
    assert await ctx.get_state()=='AdminForm:rejection_reason'
    with runtime.get_connection() as conn:
        conn.execute("UPDATE staff_mapping SET role='staff' WHERE telegram_user_id=101")
    await feed(text='reason')
    assert 'غیرمجاز' in Message.answer.await_args.args[0] and 'در انتظار' in status(1)
    with runtime.get_connection() as conn:
        conn.execute("UPDATE staff_mapping SET role='main_admin' WHERE telegram_user_id=101")
    await feed(text='<reason>')
    assert status(1)=='❌ رد شده' and await ctx.get_state() is None
    assert '&lt;reason&gt;' in Bot.send_message.await_args.kwargs['text']
    await feed(data='reject_1')
    assert CallbackQuery.answer.await_args.kwargs['show_alert'] and await ctx.get_state() is None
    await feed(data='cancel_REQ-1405-00002',user=303)
    assert 'در انتظار' in status(2)
    with runtime.get_connection() as conn:
        conn.execute('UPDATE staff_mapping SET is_active=0 WHERE telegram_user_id=202')
    await feed(data='cancel_REQ-1405-00002',user=202)
    assert 'در انتظار' in status(2)
    with runtime.get_connection() as conn:
        conn.execute('UPDATE staff_mapping SET is_active=1 WHERE telegram_user_id=202')
    await feed(data='cancel_REQ-1405-00002',user=202,photo=True)
    assert 'لغو شده' in status(2)
    Message.edit_caption.assert_awaited_once()
    await feed(data='approve_2')
    assert 'لغو شده' in status(2) and CallbackQuery.answer.await_args.kwargs['show_alert']
    await feed(data='reject_3')
    await feed(text='mission reason')
    assert status(3)=='❌ رد شده'
    await feed(data='approve_9999',content='REQ-1405-00004',photo=True)
    assert status(4)=='✅ تأیید شده قطعی'
    Message.edit_caption.assert_awaited_once()
    await feed(data='approve_9999',content='REQ-1405-00005')
    assert 'در انتظار' in status(5) and CallbackQuery.answer.await_args.kwargs['show_alert']
    await feed(data='reject_9999',content='REQ-1405-00005')
    assert (await ctx.get_data())['rejecting_req_id']==5
    await feed(text='financial reason')
    assert status(5)=='❌ رد شده'
    with runtime.get_connection() as conn:
        conn.execute("CREATE TRIGGER fail_decision BEFORE UPDATE OF status ON requests WHEN OLD.id=6 BEGIN SELECT RAISE(ABORT,'simulated failure'); END")
    await feed(data='approve_6')
    assert 'در انتظار' in status(6) and CallbackQuery.answer.await_args.kwargs['show_alert']
    Bot.send_message.assert_not_awaited()
    with runtime.get_connection() as conn: conn.execute('DROP TRIGGER fail_decision')
    await feed(data='approve_6')
    assert status(6)=='✅ تأیید شده قطعی'
    await app.close()
asyncio.run(main())
''')
