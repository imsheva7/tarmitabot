"""Maintenance confirmation and Telegram failure tests; synthetic data only."""
import ast
import asyncio
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import jdatetime
import pytest
from erpbot.handlers.maintenance import create_router
from erpbot.services import maintenance as service
from test_explicit_bootstrap import run_isolated
from test_maintenance import maintenance_db,digest


class State:
    def __init__(self): self.data={}
    async def clear(self): self.data={}
    async def get_data(self): return dict(self.data)
    async def update_data(self,**values): self.data.update(values)


def callback(data,user=101):
    return SimpleNamespace(data=data,from_user=SimpleNamespace(id=user),answer=AsyncMock(),
        message=SimpleNamespace(chat=SimpleNamespace(type='private'),answer=AsyncMock(),
            answer_document=AsyncMock(),edit_text=AsyncMock()))


def handlers(db,now):
    router=create_router(db.connection,db.path,lambda:jdatetime.datetime(1405,7,25,12),monotonic=lambda:now[0])
    return {h.callback.__name__:h.callback for h in router.callback_query.handlers}


async def prompt(actions,state):
    event=callback('confreset_requests')
    await actions['admin_confirm_reset_prompt'](event,state)
    button=event.message.edit_text.await_args.kwargs['reply_markup'].inline_keyboard[0][0]
    assert len(button.callback_data.encode())<=64
    return button.callback_data


@pytest.mark.parametrize('mode',['old_button','expired','forged','wrong_actor','cancelled'])
def test_invalid_confirmation_never_prepares_or_deletes(maintenance_db,mode):
    db=maintenance_db
    before=digest(db)
    now=[100.0]
    actions=handlers(db,now)
    state=State()
    async def run():
        data=await prompt(actions,state)
        actor=101
        if mode=='old_button': data='doreset_requests'
        elif mode=='expired': now[0]+=301
        elif mode=='forged': data='doreset_requests:جعلی'
        elif mode=='wrong_actor': actor=404
        else: await state.clear()
        event=callback(data,actor)
        await actions['admin_execute_selective_reset'](event,state)
        event.message.answer_document.assert_not_awaited()
        assert event.answer.await_args.kwargs['show_alert']
    asyncio.run(run())
    assert digest(db)==before


@pytest.mark.parametrize('mode',['delivery_failed','data_changed','role_revoked','form_cancelled','task_cancelled'])
def test_backup_failure_or_invalidated_confirmation_blocks_deletion(maintenance_db,mode):
    db=maintenance_db
    now=[100.0]
    actions=handlers(db,now)
    state=State()
    paths=[]
    async def run():
        data=await prompt(actions,state)
        event=callback(data)
        async def send(document,**kwargs):
            path=Path(document.path)
            assert path.exists() and path!=db.path
            paths.append(path)
            if mode=='delivery_failed': raise RuntimeError('Telegram unavailable')
            if mode=='data_changed':
                with db.connection() as conn: conn.execute("UPDATE reminders SET text_content='Concurrent change'")
            elif mode=='role_revoked':
                with db.connection() as conn: conn.execute("UPDATE staff_mapping SET role='staff' WHERE telegram_user_id=101")
            elif mode=='form_cancelled': await state.clear()
            elif mode=='task_cancelled': raise asyncio.CancelledError
        event.message.answer_document.side_effect=send
        if mode=='task_cancelled':
            with pytest.raises(asyncio.CancelledError): await actions['admin_execute_selective_reset'](event,state)
        else: await actions['admin_execute_selective_reset'](event,state)
        assert await state.get_data()=={}
        # A consumed confirmation must not send a second backup.
        await actions['admin_execute_selective_reset'](callback(data),state)
    asyncio.run(run())
    with db.connection() as conn:
        assert conn.execute('SELECT COUNT(*) FROM requests').fetchone()[0]==1
        assert conn.execute("SELECT COUNT(*) FROM audit_logs WHERE action_code='database.reset'").fetchone()[0]==0
    assert paths and all(not path.exists() for path in paths)


def test_simultaneous_double_click_runs_only_one_reset(maintenance_db):
    db=maintenance_db
    actions=handlers(db,[100.0])
    state=State()
    async def run():
        data=await prompt(actions,state)
        events=[callback(data),callback(data)]
        await asyncio.gather(*(actions['admin_execute_selective_reset'](event,state) for event in events))
        assert sum(event.message.answer_document.await_count for event in events)==1
        assert sum(bool(event.answer.await_args.kwargs.get('show_alert')) for event in events)==1
    asyncio.run(run())
    with db.connection() as conn:
        assert conn.execute('SELECT COUNT(*) FROM requests').fetchone()[0]==0
        assert conn.execute("SELECT COUNT(*) FROM audit_logs WHERE action_code='database.reset'").fetchone()[0]==1


def test_post_commit_cleanup_error_does_not_report_a_failed_reset(maintenance_db,monkeypatch):
    db=maintenance_db
    real=service.prepared_backup
    @contextmanager
    def snapshot(*args):
        with real(*args) as result: yield result
        raise OSError('simulated post-commit cleanup failure')
    monkeypatch.setattr(service,'prepared_backup',snapshot)
    actions=handlers(db,[100.0])
    state=State()
    async def run():
        data=await prompt(actions,state)
        event=callback(data)
        await actions['admin_execute_selective_reset'](event,state)
        assert '✅' in event.message.edit_text.await_args.args[0]
        assert await state.get_data()=={}
    asyncio.run(run())
    with db.connection() as conn:
        assert conn.execute('SELECT COUNT(*) FROM requests').fetchone()[0]==0


@pytest.mark.parametrize('layer',['handlers','services','repositories'])
def test_maintenance_module_boundaries(layer):
    path=Path(__file__).resolve().parents[1]/'erpbot'/layer/'maintenance.py'
    tree=ast.parse(path.read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if isinstance(node,ast.ImportFrom):
            assert 'runtime' not in (node.module or '')
            assert all(alias.name!='*' for alias in node.names)
        if layer!='repositories' and isinstance(node,ast.Attribute):
            assert node.attr not in ('execute','executemany','executescript') or (layer=='handlers' and isinstance(node.value,ast.Name) and node.value.id=='service')


def test_loader_has_no_dynamic_legacy_import_or_namespace_injection():
    path=Path(__file__).resolve().parents[1]/'erpbot/loader.py'
    source=path.read_text(encoding='utf-8')
    assert 'importlib' not in source and 'setattr(' not in source and 'vars(' not in source


def test_real_dispatcher_reset_and_old_id_safety(tmp_path):
    run_isolated(tmp_path,r'''
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock
from erpbot.handlers.maintenance import create_router
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
Message.answer_document=AsyncMock()
CallbackQuery.answer=AsyncMock()
Bot.send_message=AsyncMock()
async def main():
    app=initialize_runtime(Settings.from_env({'BOT_TOKEN':'123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk',
        'FERNET_KEY':Fernet.generate_key().decode()},data_directory=Path.cwd()),configure_logging=False)
    runtime.init_db()
    with runtime.get_connection() as conn:
        conn.executemany('INSERT INTO staff_mapping(staff_name,telegram_user_id,role,leave_balance) VALUES(?,?,?,?)',[
            ('Admin',101,'main_admin',7),('Staff',202,'staff',5),('Finance',404,'finance',5)])
        rid=conn.execute("INSERT INTO requests(telegram_user_id,req_code,request_type,status) VALUES(202,'REQ-1405-00001','درخواست قدیمی','در انتظار')").lastrowid
        conn.execute("INSERT INTO request_effects VALUES(?,'test')",(rid,))
        conn.execute("INSERT INTO holidays VALUES('1405/08/01','Holiday')")
    assert register_handlers()==26
    assert len(app.dispatcher.sub_routers)==19
    assert not any(name.startswith('erpbot.handlers.') and name.rsplit('.',1)[-1][:3].isdigit() for name in sys.modules)
    sequence=0
    async def click(data,user=101,group=False):
        nonlocal sequence
        sequence+=1
        for mock in (Message.answer,Message.edit_text,Message.answer_document,CallbackQuery.answer): mock.reset_mock()
        event={'message_id':sequence,'date':0,'chat':{'id':-10099 if group else user,'type':'supergroup' if group else 'private'},
               'text':'Menu','from':{'id':user,'is_bot':False,'first_name':'Test'}}
        query={'id':str(sequence),'from':event['from'],'chat_instance':'test','data':data,'message':event}
        await app.dispatcher.feed_update(app.bot,Update.model_validate({'update_id':sequence,'callback_query':query}))
    await click('confreset_requests',user=404)
    assert CallbackQuery.answer.await_args.kwargs['show_alert']
    await click('confreset_requests',group=True)
    assert CallbackQuery.answer.await_args.kwargs['show_alert']
    await click('doreset_requests')
    Message.answer_document.assert_not_awaited()
    await click('confreset_all_except_staff')
    data=Message.edit_text.await_args.kwargs['reply_markup'].inline_keyboard[0][0].callback_data
    await click(data)
    Message.answer_document.assert_awaited_once()
    assert not Path(Message.answer_document.await_args.args[0].path).exists()
    with runtime.get_connection() as conn:
        assert conn.execute('SELECT COUNT(*) FROM requests').fetchone()[0]==0
        assert conn.execute('SELECT COUNT(*) FROM request_effects').fetchone()[0]==0
        assert conn.execute('SELECT COUNT(*) FROM holidays').fetchone()[0]==0
        assert conn.execute('SELECT leave_balance FROM staff_mapping WHERE telegram_user_id=101').fetchone()[0]==7
        assert conn.execute('SELECT SUM(change_amount) FROM leave_ledger WHERE staff_name=?',('Admin',)).fetchone()[0]==7
        new_id=conn.execute("INSERT INTO requests(telegram_user_id,req_code,request_type,status) VALUES(202,'REQ-1405-00002','درخواست قدیمی','در انتظار')").lastrowid
        assert new_id>rid
    await click(data)
    Message.answer_document.assert_not_awaited()
    with runtime.get_connection() as conn:
        assert conn.execute('SELECT COUNT(*) FROM requests').fetchone()[0]==1
    await app.close()
asyncio.run(main())
''')
