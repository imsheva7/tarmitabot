"""Contact linking and navigation policy against synthetic SQLite data."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import sqlite3
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from erpbot.services import navigation as service
from erpbot.handlers.navigation import create_router,main_menu


def phone(db,staff_id,value):
    with db.connection() as conn:
        conn.execute('UPDATE staff_mapping SET phone_number=? WHERE staff_id=?',(value,staff_id))


def owner(db,staff_id=7):
    with db.connection() as conn:
        return conn.execute('SELECT telegram_user_id FROM staff_mapping WHERE staff_id=?',(staff_id,)).fetchone()[0]


@pytest.mark.parametrize('stored,submitted',[
    ('09120000001','+989120000001'),('+989120000001','09120000001'),
    ('۹۸۹۱۲۰۰۰۰۰۰۱','۰۹۱۲۰۰۰۰۰۰۱'),('۰۹۱۲۰۰۰۰۰۰۱','+989120000001'),
    ('0912 000 0001','989120000001'),('1234567','+1234567')])
def test_link_normalizes_contact_and_is_idempotent(assets_db,stored,submitted):
    phone(assets_db,7,stored)
    with assets_db.connection() as conn:
        first=service.link_contact(conn,707,707,submitted)
        second=service.link_contact(conn,707,707,submitted)
    assert first==second and first.id==7 and first.active==1
    assert owner(assets_db)==707


@pytest.mark.parametrize('actor,contact',[(707,None),(707,0),(707,808),(707,True),(0,0),(True,True)])
def test_contact_must_belong_to_the_actor(assets_db,actor,contact):
    phone(assets_db,7,'09120000001')
    with assets_db.connection() as conn,pytest.raises(service.LoginError):
        service.link_contact(conn,actor,contact,'09120000001')
    assert owner(assets_db) is None


@pytest.mark.parametrize('number',[None,'','+','letters','09999999999'])
def test_invalid_or_unknown_phone_does_not_link(assets_db,number):
    with assets_db.connection() as conn,pytest.raises(service.LoginError):
        service.link_contact(conn,707,707,number)
    assert owner(assets_db) is None


def test_link_cannot_take_over_or_move_an_existing_account(assets_db):
    phone(assets_db,2,'09120000002')
    phone(assets_db,7,'09120000007')
    with assets_db.connection() as conn,pytest.raises(service.LoginError):
        service.link_contact(conn,707,707,'09120000002')
    with assets_db.connection() as conn,pytest.raises(service.LoginError):
        service.link_contact(conn,202,202,'09120000007')
    assert owner(assets_db,2)==202 and owner(assets_db) is None


@pytest.mark.parametrize('inactive',[2,7])
def test_inactive_current_or_target_account_cannot_link(assets_db,inactive):
    phone(assets_db,7,'09120000007')
    with assets_db.connection() as conn:
        conn.execute('UPDATE staff_mapping SET is_active=0 WHERE staff_id=?',(inactive,))
    actor=202 if inactive==2 else 707
    with assets_db.connection() as conn,pytest.raises(service.LoginError):
        service.link_contact(conn,actor,actor,'09120000007')
    assert owner(assets_db) is None


def test_ambiguous_normalized_phone_is_blocked_even_if_one_record_is_inactive(assets_db):
    phone(assets_db,7,'09120000001')
    phone(assets_db,6,'+989120000001')
    with assets_db.connection() as conn,pytest.raises(service.LoginError,match='چند رکورد'):
        service.link_contact(conn,707,707,'09120000001')
    assert owner(assets_db) is None and owner(assets_db,6)==606


def test_storage_failure_rolls_back_without_misreporting_a_duplicate(assets_db):
    phone(assets_db,7,'09120000007')
    with assets_db.connection() as conn:
        conn.execute("CREATE TRIGGER fail_link BEFORE UPDATE OF telegram_user_id ON staff_mapping BEGIN SELECT RAISE(ABORT,'simulated storage failure'); END")
    with assets_db.connection() as conn,pytest.raises(sqlite3.IntegrityError):
        service.link_contact(conn,707,707,'09120000007')
    assert owner(assets_db) is None


def test_concurrent_claims_link_only_one_actor(assets_db):
    phone(assets_db,7,'09120000007')
    barrier=Barrier(2)
    def link(actor):
        barrier.wait(timeout=10)
        try:
            with assets_db.connection() as conn:
                service.link_contact(conn,actor,actor,'09120000007')
            return 'linked'
        except service.LoginError:
            return 'blocked'
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes=list(pool.map(link,[707,808]))
    assert sorted(outcomes)==['blocked','linked'] and owner(assets_db) in (707,808)


@pytest.mark.parametrize('actor,chat,allowed',[(999,-1001,True),(101,-1002,True),
    (404,-1002,False),(606,-1002,False),(999,-1002,False)])
def test_existing_group_policy_is_preserved(assets_db,actor,chat,allowed):
    with assets_db.connection() as conn:
        assert service.group_allowed(conn,actor,chat,-1001)==allowed


def test_menu_uses_current_role_and_escapes_names(assets_db):
    with assets_db.connection() as conn:
        conn.execute("UPDATE staff_mapping SET staff_name='<Admin>' WHERE telegram_user_id=101")
        text,keyboard=main_menu(service.active_account(conn,101))
        assert '&lt;Admin&gt;' in text
        assert 'admin_panel' in [row[0].callback_data for row in keyboard.inline_keyboard]
        conn.execute("UPDATE staff_mapping SET role='staff' WHERE telegram_user_id=101")
        _,keyboard=main_menu(service.active_account(conn,101))
        assert 'admin_panel' not in [row[0].callback_data for row in keyboard.inline_keyboard]


def test_group_exit_still_runs_when_private_warning_fails(assets_db):
    bot=SimpleNamespace(send_message=AsyncMock(side_effect=RuntimeError('Private messages blocked')),leave_chat=AsyncMock())
    router=create_router(assets_db.connection,bot,-1001)
    handler=router.my_chat_member.handlers[0].callback
    event=SimpleNamespace(from_user=SimpleNamespace(id=202),chat=SimpleNamespace(id=-1002,type='supergroup'))
    asyncio.run(handler(event))
    bot.leave_chat.assert_awaited_once_with(chat_id=-1002)


def test_unblocking_bot_in_private_chat_does_not_apply_group_policy(assets_db):
    bot=SimpleNamespace(send_message=AsyncMock(),leave_chat=AsyncMock())
    router=create_router(assets_db.connection,bot,-1001)
    event=SimpleNamespace(from_user=SimpleNamespace(id=202),chat=SimpleNamespace(id=202,type='private'))
    asyncio.run(router.my_chat_member.handlers[0].callback(event))
    bot.send_message.assert_not_awaited()
    bot.leave_chat.assert_not_awaited()


def test_committed_login_survives_ui_failure_and_holds_no_open_connection(assets_db):
    phone(assets_db,7,'09120000007')
    opened=0
    @contextmanager
    def connection():
        nonlocal opened
        with assets_db.connection() as conn:
            opened+=1
            try: yield conn
            finally: opened-=1
    async def fail(*args,**kwargs):
        assert opened==0 and owner(assets_db)==707
        raise RuntimeError('Telegram unavailable')
    router=create_router(connection,None,-1001)
    handler=next(h.callback for h in router.message.handlers if h.callback.__name__=='process_phone_contact')
    message=SimpleNamespace(from_user=SimpleNamespace(id=707),chat=SimpleNamespace(type='private'),
        contact=SimpleNamespace(user_id=707,phone_number='09120000007'),answer=AsyncMock(side_effect=fail))
    state=SimpleNamespace(clear=AsyncMock())
    with pytest.raises(RuntimeError): asyncio.run(handler(message,state))
    state.clear.assert_awaited_once()
    assert owner(assets_db)==707


def test_submenus_require_active_account_without_the_global_guard(assets_db):
    router=create_router(assets_db.connection,None,-1001)
    for handler in router.callback_query.handlers:
        event=SimpleNamespace(from_user=SimpleNamespace(id=606))
        if handler.callback.__name__=='back_to_main_menu':
            args=(event,SimpleNamespace())
        else: args=(event,)
        with pytest.raises(service.LoginError): asyncio.run(handler.callback(*args))
