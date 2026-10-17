"""Actual organization Router callbacks against isolated, transactional SQLite."""
import asyncio
from contextlib import contextmanager
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from erpbot.handlers.organization_units import create_router
from erpbot.services import organization_units as service
from erpbot.services.organization_schema import migrate_organization_schema


class State:
    def __init__(self, data=None):
        self.data = dict(data or {})
        self.state = None
        self.cleared = False

    async def get_data(self):
        return dict(self.data)

    async def update_data(self, **values):
        self.data.update(values)

    async def set_state(self, state):
        self.state = state.state

    async def clear(self):
        self.data.clear()
        self.state = None
        self.cleared = True


@pytest.fixture
def organization():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("""CREATE TABLE staff_mapping(staff_id INTEGER PRIMARY KEY,
        staff_name TEXT,telegram_user_id INTEGER,role TEXT,is_active INTEGER,
        leave_balance REAL DEFAULT 12)""")
    conn.execute("CREATE TABLE requests(id INTEGER PRIMARY KEY)")
    conn.executemany("INSERT INTO staff_mapping(staff_id,staff_name,telegram_user_id,role,is_active) VALUES(?,?,?,?,?)", [
        (1, "Admin", 101, "main_admin", 1),
        (2, "Staff", 202, "staff", 1),
        (3, "Finance", 303, "finance", 1),
        (4, "Inactive admin", 404, "main_admin", 0),
        (5, "Other admin", 505, "main_admin", 1),
    ])
    migrate_organization_schema(conn)
    conn.executemany("INSERT INTO org_units(unit_id,unit_code,unit_name,is_active) VALUES(?,?,?,?)", [
        (1, "office", "اداری", 1), (2, "warehouse", "انبار", 1), (3, "inactive", "غیرفعال", 0),
    ])
    conn.commit()

    @contextmanager
    def connection():
        with conn:
            yield conn

    router = create_router(connection)
    handlers = router.message.handlers + router.callback_query.handlers
    yield SimpleNamespace(conn=conn, **{handler.callback.__name__: handler.callback for handler in handlers})
    conn.close()


def message(text="واحد جدید", user=101):
    return SimpleNamespace(text=text, from_user=SimpleNamespace(id=user),
                           answer=AsyncMock(), edit_text=AsyncMock())


def callback(data, user=101):
    return SimpleNamespace(data=data, from_user=SimpleNamespace(id=user),
                           message=message(user=999), answer=AsyncMock())


def run(handler, *args):
    asyncio.run(handler(*args))


@pytest.mark.parametrize("user", [202, 303, 404, 999])
@pytest.mark.parametrize("handler,data,uses_state", [
    ("orgunits_menu", "orgunits_menu", True),
    ("orgunits_chart", "orgunits_chart", False),
    ("orgunits_choose_parent", "orgunits_choose_0", False),
    ("orgunits_pick_parent", "orgunits_pick_root", True),
])
def test_each_callback_rejects_non_admin_inactive_and_unknown_accounts(organization, user, handler, data, uses_state):
    event, state = callback(data, user), State()
    args = (event, state) if uses_state else (event,)
    before = organization.conn.total_changes
    run(getattr(organization, handler), *args)
    assert event.answer.await_args.kwargs["show_alert"] is True
    event.message.edit_text.assert_not_awaited()
    event.message.answer.assert_not_awaited()
    assert organization.conn.total_changes == before and state.data == {}


@pytest.mark.parametrize("user", [202, 303, 404, 999])
def test_forged_name_state_cannot_grant_creation_permission(organization, user):
    state = State({"orgunits_admin_id": user, "orgunits_parent_id": None})
    event = message(user=user)
    before = organization.conn.total_changes
    run(organization.orgunits_save_name, event, state)
    assert state.cleared
    assert organization.conn.total_changes == before


def test_admin_can_create_child_and_audit_with_state_and_output_unchanged(organization):
    state = State()
    run(organization.orgunits_pick_parent, callback("orgunits_pick_1"), state)
    assert state.state == "OrganizationUnitForm:waiting_for_name"
    assert state.data == {"orgunits_parent_id": 1, "orgunits_admin_id": 101}
    staff_before = organization.conn.execute("SELECT * FROM staff_mapping").fetchall()
    event = message("<واحد جدید>")
    run(organization.orgunits_save_name, event, state)
    row = organization.conn.execute("SELECT unit_id,parent_unit_id FROM org_units WHERE unit_name=?", ("<واحد جدید>",)).fetchone()
    assert row[1] == 1 and state.cleared
    audit = organization.conn.execute("SELECT actor_staff_id,action_code,entity_id FROM audit_logs").fetchone()
    assert tuple(audit) == (1, "organization.unit.create", str(row[0]))
    assert "&lt;واحد جدید&gt;" in event.answer.await_args.args[0]
    assert organization.conn.execute("SELECT * FROM staff_mapping").fetchall() == staff_before


def test_root_selection_creates_unit_without_parent(organization):
    state = State()
    run(organization.orgunits_pick_parent, callback("orgunits_pick_root"), state)
    run(organization.orgunits_save_name, message(), state)
    assert organization.conn.execute("SELECT parent_unit_id FROM org_units WHERE unit_name='واحد جدید'").fetchone()[0] is None


@pytest.mark.parametrize("change", [
    "UPDATE staff_mapping SET role='staff' WHERE staff_id=1",
    "UPDATE staff_mapping SET is_active=0 WHERE staff_id=1",
])
def test_revoked_admin_between_selection_and_save_cannot_create(organization, change):
    state = State()
    run(organization.orgunits_pick_parent, callback("orgunits_pick_1"), state)
    organization.conn.execute(change)
    event = message()
    run(organization.orgunits_save_name, event, state)
    assert state.cleared
    assert organization.conn.execute("SELECT COUNT(*) FROM org_units").fetchone()[0] == 3
    assert organization.conn.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0] == 0


def test_other_admin_cannot_use_someone_elses_form(organization):
    state = State({"orgunits_admin_id": 101, "orgunits_parent_id": 1})
    event = message(user=505)
    run(organization.orgunits_save_name, event, state)
    assert state.cleared
    assert event.answer.await_args.args[0] == "نشست مدیریتی نامعتبر است."


def test_parent_revoked_after_selection_blocks_save(organization):
    state = State()
    run(organization.orgunits_pick_parent, callback("orgunits_pick_1"), state)
    organization.conn.execute("UPDATE org_units SET is_active=0 WHERE unit_id=1")
    run(organization.orgunits_save_name, message(), state)
    assert not state.cleared
    assert organization.conn.execute("SELECT COUNT(*) FROM org_units").fetchone()[0] == 3
    assert organization.conn.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0] == 0


def test_duplicate_name_does_not_create_or_audit(organization):
    state = State({"orgunits_admin_id": 101, "orgunits_parent_id": None})
    event = message("اداری")
    run(organization.orgunits_save_name, event, state)
    assert not state.cleared
    assert organization.conn.execute("SELECT COUNT(*) FROM org_units").fetchone()[0] == 3
    assert organization.conn.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0] == 0


def test_audit_failure_rolls_back_unit_in_same_transaction(organization):
    organization.conn.execute("""CREATE TRIGGER fail_audit BEFORE INSERT ON audit_logs
        BEGIN SELECT RAISE(ABORT,'test audit failure'); END""")
    state = State({"orgunits_admin_id": 101, "orgunits_parent_id": None})
    run(organization.orgunits_save_name, message(), state)
    assert organization.conn.execute("SELECT COUNT(*) FROM org_units").fetchone()[0] == 3
    assert organization.conn.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0] == 0
    assert not state.cleared


@pytest.mark.parametrize("raw", ["", "-1", "²", "abc", "9" * 100, "9223372036854775808"])
@pytest.mark.parametrize("kind", ["choose", "pick"])
def test_malformed_callback_does_not_crash_or_change_state(organization, kind, raw):
    event = callback(f"orgunits_{kind}_{raw}")
    state = State()
    handler = organization.orgunits_choose_parent if kind == "choose" else organization.orgunits_pick_parent
    args = (event,) if kind == "choose" else (event, state)
    before = organization.conn.total_changes
    run(handler, *args)
    assert event.answer.await_args.kwargs["show_alert"] is True
    event.message.edit_text.assert_not_awaited()
    assert organization.conn.total_changes == before and state.data == {}


@pytest.mark.parametrize("parent", [3, 999])
def test_inactive_or_missing_parent_cannot_be_selected(organization, parent):
    event, state = callback(f"orgunits_pick_{parent}"), State()
    run(organization.orgunits_pick_parent, event, state)
    assert event.answer.await_args.kwargs["show_alert"] is True
    assert state.data == {}


def test_parent_pagination_and_invalid_page(organization):
    organization.conn.executemany("INSERT INTO org_units(unit_code,unit_name) VALUES(?,?)",
                                 [(f"extra{i}", f"Extra {i}") for i in range(10)])
    event = callback("orgunits_choose_1")
    run(organization.orgunits_choose_parent, event)
    buttons = [button.callback_data for row in event.message.edit_text.await_args.kwargs["reply_markup"].inline_keyboard for button in row]
    assert "orgunits_choose_0" in buttons and "orgunits_pick_root" in buttons
    assert len([data for data in buttons if data.startswith("orgunits_pick_")]) == 5
    invalid = callback("orgunits_choose_99")
    run(organization.orgunits_choose_parent, invalid)
    invalid.message.edit_text.assert_not_awaited()
    assert invalid.answer.await_args.kwargs["show_alert"] is True


def test_large_chart_is_split_without_dropping_units(organization):
    names = [f"{i:03d}" + "X" * 75 for i in range(100)]
    organization.conn.executemany("INSERT INTO org_units(unit_code,unit_name) VALUES(?,?)",
                                 [(f"chart{i}", name) for i, name in enumerate(names)])
    event = callback("orgunits_chart")
    run(organization.orgunits_chart, event)
    chunks = [call.args[0] for call in event.message.answer.await_args_list]
    assert len(chunks) > 1 and all(len(chunk) <= 3500 for chunk in chunks)
    assert all(name in "".join(chunks) for name in names)


@pytest.mark.parametrize("operation,args", [
    (service.active_units_for_admin, ()), (service.chart_for_admin, ()),
    (service.parent_name_for_admin, (1,)), (service.create_unit_for_admin, ("Denied unit",)),
])
def test_service_use_cases_reject_unauthorized_callers_even_without_router(organization, operation, args):
    before = organization.conn.total_changes
    with pytest.raises(service.OrganizationUnitPermissionError):
        operation(organization.conn, 202, *args)
    assert organization.conn.total_changes == before
