"""Administrative backup tests use synthetic databases and mocked Telegram I/O."""
import asyncio
from contextlib import contextmanager, closing
from pathlib import Path
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from erpbot.handlers.admin_console import create_router
from erpbot.services import admin_console as service
from test_explicit_bootstrap import run_isolated


@pytest.mark.parametrize('actor', [202,404,505,606,999,None])
def test_unauthorized_backup_never_creates_snapshot(assets_db, monkeypatch, actor):
    def forbidden(*args): pytest.fail('Unauthorized snapshot creation')
    monkeypatch.setattr(service,'database_snapshot',forbidden)
    with pytest.raises(service.PersonnelError):
        with service.authorized_backup(assets_db.connection,assets_db.path,actor):
            pytest.fail('Unauthorized download')


def test_backup_contains_committed_wal_and_keeps_original(assets_db):
    source=sqlite3.connect(assets_db.path)
    try:
        source.execute('PRAGMA journal_mode=WAL')
        source.execute('PRAGMA wal_autocheckpoint=0')
        source.execute("UPDATE staff_mapping SET staff_name='WAL value' WHERE staff_id=2")
        source.commit()
        with service.authorized_backup(assets_db.connection,assets_db.path,101) as name:
            path=Path(name)
            assert path!=assets_db.path
            with closing(sqlite3.connect(path)) as copy:
                assert copy.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
                assert copy.execute('SELECT staff_name FROM staff_mapping WHERE staff_id=2').fetchone()[0]=='WAL value'
        assert not path.exists()
        assert source.execute('SELECT COUNT(*) FROM staff_mapping').fetchone()[0]==7
    finally:
        source.close()


def test_permission_revoked_while_snapshot_is_created(assets_db, monkeypatch):
    real_snapshot=service.database_snapshot
    paths=[]
    @contextmanager
    def snapshot(path):
        with real_snapshot(path) as name:
            paths.append(Path(name))
            with assets_db.connection() as conn:
                conn.execute("UPDATE staff_mapping SET role='staff' WHERE telegram_user_id=101")
            yield name
    monkeypatch.setattr(service,'database_snapshot',snapshot)
    with pytest.raises(service.PersonnelError):
        with service.authorized_backup(assets_db.connection,assets_db.path,101):
            pytest.fail('Revoked administrator received snapshot')
    assert paths and not paths[0].exists()


@pytest.mark.parametrize('result', ['success','failure','cancel'])
def test_backup_handler_cleanup_and_no_open_connection(assets_db,result):
    opened=0
    @contextmanager
    def connection():
        nonlocal opened
        with assets_db.connection() as conn:
            opened+=1
            try: yield conn
            finally: opened-=1
    paths=[]
    async def send(document,**kwargs):
        assert opened==0
        path=Path(document.path)
        assert path.exists() and path!=assets_db.path
        paths.append(path)
        if result=='failure': raise RuntimeError('Telegram unavailable')
        if result=='cancel': raise asyncio.CancelledError
    callback=SimpleNamespace(from_user=SimpleNamespace(id=101),answer=AsyncMock(),
                             message=SimpleNamespace(answer_document=AsyncMock(side_effect=send)))
    router=create_router(connection,assets_db.path)
    handler=next(h.callback for h in router.callback_query.handlers if h.callback.__name__=='admin_backup_cb')
    if result=='cancel':
        with pytest.raises(asyncio.CancelledError): asyncio.run(handler(callback))
        callback.answer.assert_not_awaited()
    else:
        asyncio.run(handler(callback))
        callback.answer.assert_awaited_once()
        assert bool(callback.answer.await_args.kwargs.get('show_alert'))==(result=='failure')
    assert paths and not paths[0].exists()


def test_handler_itself_rejects_forged_backup_without_global_guard(assets_db):
    router=create_router(assets_db.connection,assets_db.path)
    handler=next(h.callback for h in router.callback_query.handlers if h.callback.__name__=='admin_backup_cb')
    callback=SimpleNamespace(from_user=SimpleNamespace(id=404),answer=AsyncMock(),
                             message=SimpleNamespace(answer_document=AsyncMock()))
    asyncio.run(handler(callback))
    callback.message.answer_document.assert_not_awaited()
    assert callback.answer.await_args.kwargs['show_alert']


def test_missing_database_returns_error_without_creating_file(assets_db,tmp_path):
    missing=tmp_path/'missing.db'
    router=create_router(assets_db.connection,missing)
    handler=next(h.callback for h in router.callback_query.handlers if h.callback.__name__=='admin_backup_cb')
    callback=SimpleNamespace(from_user=SimpleNamespace(id=101),answer=AsyncMock(),
                             message=SimpleNamespace(answer_document=AsyncMock()))
    asyncio.run(handler(callback))
    callback.message.answer_document.assert_not_awaited()
    assert callback.answer.await_args.kwargs['show_alert'] and not missing.exists()


def test_import_has_no_runtime_or_file_side_effects(tmp_path):
    run_isolated(tmp_path,"""
import sys
from pathlib import Path
from erpbot.handlers.admin_console import create_router
from erpbot.services.admin_console import authorized_backup
assert 'erpbot.core.runtime' not in sys.modules
router=create_router(None,None)
assert list(Path.cwd().iterdir())==[]
""")


def test_admin_panel_and_backup_through_real_dispatcher(tmp_path):
    run_isolated(tmp_path,r'''
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock
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

async def main():
    app=initialize_runtime(Settings.from_env({'BOT_TOKEN':'123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk',
        'FERNET_KEY':Fernet.generate_key().decode()},data_directory=Path.cwd()),configure_logging=False)
    runtime.init_db()
    with runtime.get_connection() as conn:
        conn.executemany('INSERT INTO staff_mapping(staff_name,telegram_user_id,role,is_active) VALUES(?,?,?,?)',[
            ('Admin',101,'main_admin',1),('Staff',202,'staff',1),('Finance',404,'finance',1),
            ('Purchase',505,'purchase',1),('Disabled',606,'main_admin',0)])
    register_handlers()
    sequence=0
    async def feed(user=101,text=None,data=None):
        nonlocal sequence
        sequence+=1
        for mock in (Message.answer,Message.edit_text,Message.answer_document,CallbackQuery.answer): mock.reset_mock()
        event={'message_id':sequence,'date':0,'chat':{'id':user,'type':'private'},'text':text or 'Menu',
               'from':{'id':user,'is_bot':False,'first_name':'Test'}}
        update={'update_id':sequence}
        if data: update['callback_query']={'id':str(sequence),'from':event['from'],'chat_instance':'test','data':data,'message':event}
        else: update['message']=event
        await app.dispatcher.feed_update(app.bot,Update.model_validate(update))
    for user in (101,404,505):
        ctx=app.dispatcher.fsm.get_context(bot=app.bot,chat_id=user,user_id=user)
        await ctx.set_state('AdminForm:add_staff_name')
        await feed(user=user,data='admin_panel')
        assert await ctx.get_state() is None
        Message.edit_text.assert_awaited_once()
        buttons=Message.edit_text.await_args.kwargs['reply_markup'].inline_keyboard
        assert [row[0].callback_data for row in buttons]==['admin_pending_reqs','adm_cat_staff','admin_assign_asset',
            'admin_add_insurance','admin_holidays_menu','adm_cat_excel','admin_selective_reset_menu','admin_get_backup','back_to_main']
        await feed(user=user,text='/admin')
        Message.answer.assert_awaited_once()
    for user in (202,606,999):
        await feed(user=user,data='admin_panel')
        Message.edit_text.assert_not_awaited()
        await feed(user=user,data='admin_get_backup')
        Message.answer_document.assert_not_awaited()
    for user in (404,505):
        await feed(user=user,data='admin_get_backup')
        Message.answer_document.assert_not_awaited()
    await feed(data='admin_get_backup')
    Message.answer_document.assert_awaited_once()
    document=Message.answer_document.await_args.args[0]
    assert document.filename=='erpbot_backup.sqlite3'
    assert not Path(document.path).exists()
    CallbackQuery.answer.assert_awaited_once()
    await app.close()
asyncio.run(main())
''')
