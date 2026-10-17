"""Offline checks for the interactive test bot's isolated onboarding controls."""
import asyncio
from contextlib import contextmanager
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram import Dispatcher
from aiogram.filters import CommandObject
import pytest

from erpbot.services.organization_access import has_unit_permission
from erpbot.services.organization_schema import migrate_organization_schema
from phase5b_live_test import configure_handlers, explain_failure, validate_test_token, validate_test_bot


def test_group_mode_seeds_balanced_admin_and_uses_no_production_topics(tmp_path):
    from test_explicit_bootstrap import run_isolated
    run_isolated(tmp_path, r'''
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from aiogram.filters import CommandObject
from cryptography.fernet import Fernet
from erpbot.bootstrap import initialize_runtime
from erpbot.core import runtime
from erpbot.core.settings import Settings
from phase5b_live_test import configure_handlers, configure_test_group, TEST_GROUP_ID
app=initialize_runtime(Settings.from_env({'BOT_TOKEN':'123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk',
    'GROUP_ID':str(TEST_GROUP_ID),'FERNET_KEY':Fernet.generate_key().decode()},data_directory=Path.cwd()),configure_logging=False)
runtime.init_db()
try:
    configure_test_group(runtime, -123)
except ValueError:
    pass
else:
    raise AssertionError('Unexpected group accepted')
configure_test_group(runtime, TEST_GROUP_ID)
assert runtime.GROUP_ID==TEST_GROUP_ID
assert runtime.TOPIC_LEAVE is None and runtime.TOPIC_ASSETS is None
configure_handlers(runtime,'secret',admin_mode=True,group_id=TEST_GROUP_ID)
message=SimpleNamespace(chat=SimpleNamespace(type='private'),from_user=SimpleNamespace(id=202),answer=AsyncMock())
asyncio.run(runtime.dp.message.handlers[0].callback(message,CommandObject(command='start',args='secret')))
with runtime.get_connection() as conn:
    sid,role,balance=conn.execute('SELECT staff_id,role,leave_balance FROM staff_mapping WHERE telegram_user_id=202').fetchone()
    assert role=='main_admin' and balance==10
    assert conn.execute('SELECT SUM(change_amount) FROM leave_ledger WHERE staff_id=?',(sid,)).fetchone()[0]==10
asyncio.run(app.close())
''')


@pytest.mark.parametrize("username", ["Armitaoibot", "other_bot", None, ""])
def test_live_runner_rejects_every_bot_except_named_test_bot(username):
    with pytest.raises(RuntimeError, match="Only @ArmitaAmani_bot"):
        validate_test_bot(username)


def test_live_runner_accepts_test_bot_username_case_insensitively():
    validate_test_bot("ArmitaAmani_bot")


@pytest.fixture
def sandbox():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("""CREATE TABLE staff_mapping(staff_id INTEGER PRIMARY KEY,
        staff_name TEXT, telegram_user_id INTEGER, role TEXT DEFAULT 'staff',
        is_active INTEGER DEFAULT 1)""")
    conn.execute("CREATE TABLE requests(id INTEGER PRIMARY KEY)")
    migrate_organization_schema(conn)

    @contextmanager
    def connection():
        with conn:
            yield conn

    runtime = SimpleNamespace(dp=Dispatcher(), get_connection=connection)
    configure_handlers(runtime, "private-test-code")
    handlers = [handler.callback for handler in runtime.dp.message.handlers]
    yield conn, handlers
    conn.close()


def msg(user=202):
    return SimpleNamespace(chat=SimpleNamespace(type="private"),
                           from_user=SimpleNamespace(id=user), answer=AsyncMock())


def invoke(handler, event, command, args=None):
    asyncio.run(handler(event, CommandObject(command=command, args=args)))


def test_invalid_join_code_and_unbound_controls_cannot_create_data(sandbox):
    conn, (join, controls) = sandbox
    invoke(join, msg(), "start", "wrong-code")
    invoke(controls, msg(), "test_grant")
    assert conn.execute("SELECT COUNT(*) FROM staff_mapping").fetchone()[0] == 0


def test_join_creates_only_ordinary_test_staff_and_one_unit_permission(sandbox):
    conn, (join, controls) = sandbox
    invoke(join, msg(), "start", "private-test-code")
    invoke(join, msg(), "start", "private-test-code")
    invoke(join, msg(user=999), "start", "private-test-code")
    staff = conn.execute("SELECT staff_id,role FROM staff_mapping WHERE telegram_user_id=202").fetchone()
    assert staff[1] == "staff"
    assert conn.execute("SELECT COUNT(*) FROM staff_mapping").fetchone()[0] == 4
    assert conn.execute("SELECT COUNT(*) FROM staff_mapping WHERE telegram_user_id=999").fetchone()[0] == 0
    units = dict(conn.execute("SELECT unit_code,unit_id FROM org_units"))
    assert has_unit_permission(conn, staff[0], units['test-office'], 'staff.view_unit')
    assert not has_unit_permission(conn, staff[0], units['test-warehouse'], 'staff.view_unit')


def test_only_bound_tester_can_revoke_and_restore_test_permission(sandbox):
    conn, (join, controls) = sandbox
    invoke(join, msg(), "start", "private-test-code")
    invoke(controls, msg(user=999), "test_revoke")
    assert conn.execute("SELECT is_active FROM staff_role_assignments").fetchone()[0] == 1
    invoke(controls, msg(), "test_revoke")
    assert conn.execute("SELECT is_active FROM staff_role_assignments").fetchone()[0] == 0
    invoke(controls, msg(user=999), "test_grant")
    assert conn.execute("SELECT is_active FROM staff_role_assignments").fetchone()[0] == 0
    invoke(controls, msg(), "test_grant")
    assert conn.execute("SELECT is_active FROM staff_role_assignments").fetchone()[0] == 1


def test_admin_mode_binds_only_secret_link_owner_and_disables_scope_controls(sandbox):
    conn, _ = sandbox

    @contextmanager
    def connection():
        with conn:
            yield conn

    runtime = SimpleNamespace(dp=Dispatcher(), get_connection=connection)
    configure_handlers(runtime, "admin-secret", admin_mode=True)
    join, controls, identify_group = [item.callback for item in runtime.dp.message.handlers]
    invoke(join, msg(user=999), "start", "wrong")
    assert conn.execute("SELECT COUNT(*) FROM staff_mapping").fetchone()[0] == 0
    invoke(join, msg(), "start", "admin-secret")
    invoke(join, msg(user=999), "start", "admin-secret")
    invoke(join, msg(), "start")
    assert conn.execute("SELECT telegram_user_id FROM staff_mapping WHERE role='main_admin'").fetchall() == [(202,)]
    assert conn.execute("SELECT COUNT(*) FROM staff_mapping").fetchone()[0] == 4
    invoke(controls, msg(), "test_revoke")
    assert conn.execute("SELECT is_active FROM staff_role_assignments").fetchone()[0] == 1
    for user, chat_type, expected in [(999, 'supergroup', False), (202, 'private', False),
                                      (202, 'supergroup', True), (202, 'group', True)]:
        event = msg(user=user)
        event.chat = SimpleNamespace(type=chat_type, id=-1001234567890)
        asyncio.run(identify_group(event))
        assert event.answer.await_count == int(expected)
        if expected:
            assert '-1001234567890' in event.answer.await_args.args[0]


@pytest.mark.parametrize("token", ["", "https://api.telegram.org/bot123:ABC", "bot123:ABC", "'123:ABC'"])
def test_invalid_token_format_rejected_without_echoing_it(token):
    with pytest.raises(ValueError) as error:
        validate_test_token(token)
    assert str(error.value) == "Enter only the bot token copied from BotFather, without quotes or a URL."


def test_telegram_error_explanation_does_not_echo_credentials():
    from aiogram.exceptions import TelegramNotFound
    from aiogram.methods import GetMe
    secret = "123456789:SECRET_EXAMPLE_DO_NOT_PRINT"
    output = explain_failure(TelegramNotFound(method=GetMe(), message=secret))
    assert secret not in output
    assert "BotFather" in output
