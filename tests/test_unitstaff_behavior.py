"""Exercise the actual directory handlers with SQLite and mocked Telegram I/O."""
import asyncio
from contextlib import contextmanager
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from erpbot.services.staff_directory import visible_units_for_user, directory_for_user
from erpbot.services.organization_schema import migrate_organization_schema
from erpbot.handlers.unit_staff import create_router


@pytest.fixture
def directory():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("""CREATE TABLE staff_mapping (
        staff_id INTEGER PRIMARY KEY, staff_name TEXT, telegram_user_id INTEGER,
        role TEXT, is_active INTEGER)""")
    conn.execute("CREATE TABLE requests(id INTEGER PRIMARY KEY)")
    conn.executemany("INSERT INTO staff_mapping VALUES(?,?,?,?,?)", [
        (1, "Main admin", 101, "main_admin", 1),
        (2, "Unit viewer", 202, "staff", 1),
        (3, "Allowed colleague", 303, "staff", 1),
        (4, "Other unit colleague", 404, "staff", 1),
        (5, "Inactive colleague", 505, "staff", 0),
    ])
    migrate_organization_schema(conn)
    conn.executemany(
        "INSERT INTO org_units(unit_id,unit_code,unit_name) VALUES(?,?,?)",
        [(1, "office", "Office"), (2, "warehouse", "Warehouse")],
    )
    conn.executemany(
        "INSERT INTO staff_unit_memberships(staff_id,unit_id) VALUES(?,?)",
        [(2, 1), (2, 2), (3, 1), (4, 2), (5, 1)],
    )
    conn.execute("INSERT INTO roles(role_code,role_name) VALUES('viewer','Viewer')")
    role_id = conn.execute("SELECT role_id FROM roles WHERE role_code='viewer'").fetchone()[0]
    conn.execute("""INSERT INTO role_permissions(role_id,permission_id)
        SELECT ?,permission_id FROM permissions WHERE permission_code='staff.view_unit'""", (role_id,))
    conn.execute("""INSERT INTO staff_role_assignments(staff_id,role_id,unit_id)
        VALUES(2,?,1)""", (role_id,))
    conn.commit()

    @contextmanager
    def connection():
        yield conn

    router = create_router(connection)
    handlers = router.message.handlers + router.callback_query.handlers
    env = {handler.callback.__name__: handler.callback for handler in handlers}
    yield SimpleNamespace(conn=conn, **env)
    conn.close()


def message(user=202, chat_type="private"):
    return SimpleNamespace(
        from_user=SimpleNamespace(id=user), chat=SimpleNamespace(type=chat_type),
        answer=AsyncMock(), edit_text=AsyncMock(),
    )


def callback(data="unitstaff_view_1", user=202, chat_type="private"):
    # The message author is the bot: authorization must use the callback sender.
    return SimpleNamespace(data=data, from_user=SimpleNamespace(id=user),
                           message=message(user=999, chat_type=chat_type), answer=AsyncMock())


def run(handler, event):
    asyncio.run(handler(event))


def buttons(mock):
    return [button.callback_data for row in mock.await_args.kwargs["reply_markup"].inline_keyboard
            for button in row]


def test_non_admin_only_sees_permitted_units(directory):
    event = message()
    run(directory.scoped_unit_staff_command, event)
    assert buttons(event.answer) == ["unitstaff_view_1"]


def test_non_admin_sees_only_active_members_of_selected_unit(directory):
    event = callback()
    before = directory.conn.total_changes
    run(directory.scoped_unit_staff_view, event)
    text = event.message.edit_text.await_args.args[0]
    assert "Allowed colleague" in text and "Unit viewer" in text
    assert "Other unit colleague" not in text and "Inactive colleague" not in text
    assert directory.conn.total_changes == before
    event.answer.assert_awaited_once()


@pytest.mark.parametrize("user", [101, 404, 999])
def test_admin_and_other_users_cannot_reuse_viewer_button(directory, user):
    event = callback(user=user)
    run(directory.scoped_unit_staff_view, event)
    event.message.edit_text.assert_not_awaited()
    assert event.answer.await_args.kwargs["show_alert"] is True


def test_forged_unit_button_is_denied_even_with_membership(directory):
    event = callback("unitstaff_view_2")
    run(directory.scoped_unit_staff_view, event)
    event.message.edit_text.assert_not_awaited()
    assert event.answer.await_args.kwargs["show_alert"] is True


@pytest.mark.parametrize("revoke", [
    "UPDATE staff_role_assignments SET is_active=0 WHERE staff_id=2",
    "UPDATE staff_unit_memberships SET is_active=0 WHERE staff_id=2 AND unit_id=1",
    "UPDATE staff_mapping SET is_active=0 WHERE staff_id=2",
    "UPDATE org_units SET is_active=0 WHERE unit_id=1",
    "UPDATE roles SET is_active=0 WHERE role_code='viewer'",
    "UPDATE permissions SET is_active=0 WHERE permission_code='staff.view_unit'",
])
def test_revocation_after_menu_blocks_old_buttons_and_back(directory, revoke):
    initial = message()
    run(directory.scoped_unit_staff_command, initial)
    assert buttons(initial.answer) == ["unitstaff_view_1"]
    directory.conn.execute(revoke)
    event = callback()
    run(directory.scoped_unit_staff_view, event)
    event.message.edit_text.assert_not_awaited()
    assert event.answer.await_args.kwargs["show_alert"] is True
    back = callback("unitstaff_back")
    run(directory.scoped_unit_staff_back, back)
    assert "reply_markup" not in back.message.edit_text.await_args.kwargs


def test_back_rebuilds_allowed_units_from_callback_sender(directory):
    event = callback("unitstaff_back")
    run(directory.scoped_unit_staff_back, event)
    assert buttons(event.message.edit_text) == ["unitstaff_view_1"]


@pytest.mark.parametrize("raw", ["0", "-1", "abc", "۱", "1 OR 1=1", "99999999999"])
def test_invalid_unit_id_does_not_query_database(directory, raw):
    event = callback("unitstaff_view_" + raw)
    queries = []
    directory.conn.set_trace_callback(queries.append)
    run(directory.scoped_unit_staff_view, event)
    assert queries == []
    event.message.edit_text.assert_not_awaited()
    assert event.answer.await_args.kwargs["show_alert"] is True


def test_group_events_do_not_query_database(directory):
    queries = []
    directory.conn.set_trace_callback(queries.append)
    msg = message(chat_type="group")
    run(directory.scoped_unit_staff_command, msg)
    msg.answer.assert_not_awaited()
    for name in ("scoped_unit_staff_view", "scoped_unit_staff_back"):
        event = callback(chat_type="group")
        run(getattr(directory, name), event)
        event.message.edit_text.assert_not_awaited()
        assert event.answer.await_args.kwargs["show_alert"] is True
    assert queries == []


def test_denied_service_request_never_reads_unit_members(directory):
    queries = []
    directory.conn.set_trace_callback(queries.append)
    result = directory_for_user(directory.conn, 202, 2)
    assert result.outcome == "denied"
    assert result.member_names == ()
    assert not any("s.staff_name" in query for query in queries)


@pytest.mark.parametrize("user", [505, 999])
def test_inactive_or_unknown_user_cannot_open_unit_menu(directory, user):
    event = message(user=user)
    run(directory.scoped_unit_staff_command, event)
    assert event.answer.await_args.args[0] == "حساب پرسنلی فعال یافت نشد."
    assert "reply_markup" not in event.answer.await_args.kwargs
