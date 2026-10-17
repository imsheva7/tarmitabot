"""Real Router functions and application queries against transactional SQLite."""
import asyncio
from contextlib import contextmanager
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from erpbot.handlers.organization_memberships import create_router as membership_router
from erpbot.handlers.organization_roles import create_router as role_router
from erpbot.services.organization_access import has_unit_permission
from erpbot.services.organization_schema import migrate_organization_schema
from erpbot.services.organization_admin import OrganizationAdminError
from erpbot.services import organization_memberships as memberships, organization_roles as roles


class State:
    def __init__(self, data=None):
        self.data = dict(data or {})
        self.state = None
        self.cleared = False

    async def update_data(self, **values):
        self.data.update(values)

    async def get_data(self):
        return dict(self.data)

    async def set_state(self, state):
        self.state = state.state

    async def clear(self):
        self.data.clear()
        self.state = None
        self.cleared = True


@pytest.fixture
def management():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("""CREATE TABLE staff_mapping(staff_id INTEGER PRIMARY KEY,staff_name TEXT,
        telegram_user_id INTEGER,role TEXT,is_active INTEGER,leave_balance REAL DEFAULT 12)""")
    conn.execute("CREATE TABLE requests(id INTEGER PRIMARY KEY)")
    conn.executemany("INSERT INTO staff_mapping(staff_id,staff_name,telegram_user_id,role,is_active) VALUES(?,?,?,?,?)", [
        (1,"Admin",101,"main_admin",1), (2,"Employee",202,"staff",1),
        (3,"Finance",303,"finance",1), (4,"Disabled admin",404,"main_admin",0),
        (5,"Other admin",505,"main_admin",1), (6,"Disabled staff",606,"staff",0),
    ])
    migrate_organization_schema(conn)
    conn.executemany("INSERT INTO org_units(unit_id,unit_code,unit_name,is_active) VALUES(?,?,?,?)",
                     [(1,"office","Office",1),(2,"warehouse","Warehouse",1),(3,"inactive","Inactive",0)])
    conn.executemany("INSERT INTO staff_unit_memberships(staff_id,unit_id) VALUES(2,?)", [(1,),(2,)])
    role = conn.execute("INSERT INTO roles(role_code,role_name) VALUES('custom_viewer','Viewer')").lastrowid
    permission = conn.execute("SELECT permission_id FROM permissions WHERE permission_code='staff.view_unit'").fetchone()[0]
    conn.execute("INSERT INTO role_permissions VALUES(?,?)", (role,permission))
    conn.executemany("INSERT INTO staff_role_assignments(staff_id,role_id,unit_id) VALUES(2,?,?)", [(role,1),(role,2)])
    conn.commit()

    @contextmanager
    def connection():
        with conn:
            yield conn

    handlers = {}
    for router in (membership_router(connection), role_router(connection)):
        handlers.update({handler.callback.__name__: handler.callback
                         for handler in router.message.handlers + router.callback_query.handlers})
    yield SimpleNamespace(conn=conn, role=role, permission=permission, **handlers)
    conn.close()


def message(text="New role", user=101, chat_type="private"):
    return SimpleNamespace(text=text, from_user=SimpleNamespace(id=user), chat=SimpleNamespace(type=chat_type),
                           answer=AsyncMock(), edit_text=AsyncMock())


def callback(data, user=101):
    return SimpleNamespace(data=data, from_user=SimpleNamespace(id=user),
                           message=message(user=999), answer=AsyncMock())


def run(handler, *args):
    asyncio.run(handler(*args))


CALLBACKS = [
    ("orgmem_staff_list","orgmem_staff_0",False), ("orgmem_person","orgmem_person_2",False),
    ("orgmem_choose_unit","orgmem_addunits_2_0",False), ("orgmem_join","orgmem_join_3_1",False),
    ("orgmem_confirm_remove","orgmem_confirm_2_1",False), ("orgmem_remove","orgmem_remove_2_1",False),
    ("orgmem_unit_list","orgmem_units_0",False), ("orgmem_unit_members","orgmem_unit_1",False),
    ("orgr_menu","orgr_menu",True), ("orgr_new","orgr_new",True), ("orgr_list","orgr_list",False),
    ("orgr_view","orgr_view_{role}",False), ("orgr_perms","orgr_perms_{role}",False),
    ("orgr_toggle","orgr_toggle_{role}_{permission}_0",False), ("orgr_active","orgr_active_{role}_0",False),
    ("orgr_staff","orgr_staff_0",False), ("orgr_person","orgr_person_2",False),
    ("orgr_unit","orgr_unit_2_1",False), ("orgr_set","orgr_set_2_1_{role}_0",False),
]


@pytest.mark.parametrize("user", [202,303,404,999])
@pytest.mark.parametrize("handler,data,needs_state", CALLBACKS)
def test_every_admin_callback_denies_non_admin_disabled_and_unknown_users(management, user, handler, data, needs_state):
    event = callback(data.format(role=management.role, permission=management.permission), user)
    before = management.conn.total_changes
    args = (event, State()) if needs_state else (event,)
    run(getattr(management, handler), *args)
    assert event.answer.await_args.kwargs["show_alert"] is True
    event.message.edit_text.assert_not_awaited()
    assert management.conn.total_changes == before


def test_confirmation_only_previews_then_removal_disables_only_same_unit_roles(management):
    preview = callback("orgmem_confirm_2_1")
    before = management.conn.total_changes
    run(management.orgmem_confirm_remove, preview)
    assert management.conn.total_changes == before
    assert "orgmem_remove_2_1" in str(preview.message.edit_text.await_args.kwargs["reply_markup"])
    run(management.orgmem_remove, callback("orgmem_remove_2_1"))
    assert not has_unit_permission(management.conn,2,1,"staff.view_unit")
    assert has_unit_permission(management.conn,2,2,"staff.view_unit")
    run(management.orgmem_join, callback("orgmem_join_2_1"))
    assert memberships.active_memberships_for_staff(management.conn,2)
    assert not has_unit_permission(management.conn,2,1,"staff.view_unit")
    assert has_unit_permission(management.conn,2,2,"staff.view_unit")
    assert management.conn.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0] == 2


def test_adding_membership_does_not_grant_roles_or_change_legacy_staff_data(management):
    before = management.conn.execute("SELECT * FROM staff_mapping").fetchall()
    run(management.orgmem_join, callback("orgmem_join_3_1"))
    assert memberships.active_memberships_for_staff(management.conn,3)
    assert not has_unit_permission(management.conn,3,1,"staff.view_unit")
    assert management.conn.execute("SELECT * FROM staff_mapping").fetchall() == before


@pytest.mark.parametrize("data", ["orgmem_join_6_1","orgmem_join_3_3","orgmem_join_2_1","orgmem_remove_3_1"])
def test_inactive_targets_duplicates_and_missing_memberships_are_rejected(management, data):
    event = callback(data)
    before = management.conn.total_changes
    handler = management.orgmem_remove if data.startswith("orgmem_remove") else management.orgmem_join
    run(handler, event)
    assert event.answer.await_args.kwargs["show_alert"] is True
    assert management.conn.total_changes == before


@pytest.mark.parametrize("user", [202,303,404,999])
def test_forged_role_creation_form_cannot_grant_admin_permission(management, user):
    state = State({"orgr_actor":user})
    before = management.conn.total_changes
    run(management.orgr_new_save, message(user=user), state)
    assert state.cleared and management.conn.total_changes == before


def test_role_creation_preserves_fsm_and_starts_without_permissions(management):
    state = State()
    run(management.orgr_new, callback("orgr_new"), state)
    assert state.state == "OrganizationRoleForm:waiting_for_role_name"
    assert state.data == {"orgr_actor":101}
    run(management.orgr_new_save, message("New supervisor"), state)
    role = management.conn.execute("SELECT role_id FROM roles WHERE role_name='New supervisor'").fetchone()[0]
    assert state.cleared
    assert management.conn.execute("SELECT COUNT(*) FROM role_permissions WHERE role_id=?", (role,)).fetchone()[0] == 0
    assert management.conn.execute("SELECT actor_staff_id FROM audit_logs").fetchone()[0] == 1


@pytest.mark.parametrize("change", ["role='staff'", "is_active=0"])
def test_admin_revoked_during_role_creation_cannot_save(management, change):
    state = State()
    run(management.orgr_new, callback("orgr_new"), state)
    management.conn.execute(f"UPDATE staff_mapping SET {change} WHERE staff_id=1")
    before = management.conn.total_changes
    run(management.orgr_new_save, message(), state)
    assert state.cleared and management.conn.total_changes == before


def test_other_admin_cannot_reuse_role_creation_form(management):
    state = State({"orgr_actor":101})
    before = management.conn.total_changes
    run(management.orgr_new_save, message(user=505), state)
    assert state.cleared and management.conn.total_changes == before


@pytest.mark.parametrize("kind", ["toggle", "active", "set"])
def test_forged_mutations_cannot_modify_system_role(management, kind):
    role = management.conn.execute("SELECT role_id FROM roles WHERE role_code='main_admin'").fetchone()[0]
    data = {"toggle":f"orgr_toggle_{role}_{management.permission}_1",
            "active":f"orgr_active_{role}_0", "set":f"orgr_set_2_1_{role}_1"}[kind]
    event = callback(data)
    before = management.conn.total_changes
    run(getattr(management, "orgr_" + kind), event)
    assert event.answer.await_args.kwargs["show_alert"] is True
    assert management.conn.total_changes == before


def test_permission_changes_take_effect_without_legacy_role_changes(management):
    before = management.conn.execute("SELECT * FROM staff_mapping").fetchall()
    run(management.orgr_toggle, callback(f"orgr_toggle_{management.role}_{management.permission}_0"))
    assert not has_unit_permission(management.conn,2,1,"staff.view_unit")
    run(management.orgr_toggle, callback(f"orgr_toggle_{management.role}_{management.permission}_1"))
    assert has_unit_permission(management.conn,2,1,"staff.view_unit")
    assert management.conn.execute("SELECT * FROM staff_mapping").fetchall() == before


def test_role_deactivation_and_reactivation_do_not_restore_assignments(management):
    run(management.orgr_active, callback(f"orgr_active_{management.role}_0"))
    run(management.orgr_active, callback(f"orgr_active_{management.role}_1"))
    assert not has_unit_permission(management.conn,2,1,"staff.view_unit")
    assert not has_unit_permission(management.conn,2,2,"staff.view_unit")


def test_assign_and_revoke_stay_scoped_and_require_membership(management):
    denied = callback(f"orgr_set_3_1_{management.role}_1")
    run(management.orgr_set, denied)
    assert denied.answer.await_args.kwargs["show_alert"] is True
    run(management.orgr_set, callback(f"orgr_set_2_1_{management.role}_0"))
    assert not has_unit_permission(management.conn,2,1,"staff.view_unit")
    assert has_unit_permission(management.conn,2,2,"staff.view_unit")
    run(management.orgr_set, callback(f"orgr_set_2_1_{management.role}_1"))
    assert has_unit_permission(management.conn,2,1,"staff.view_unit")


@pytest.mark.parametrize("user", [202,303,606,999])
def test_myunits_is_personal_and_does_not_require_admin(management, user):
    event = message(user=user)
    run(management.my_organization_units, event)
    text = event.answer.await_args.args[0]
    if user == 202:
        assert "Office" in text and "Warehouse" in text
    elif user == 303:
        assert "هنوز عضو واحدی نیستید" in text
    else:
        assert "حساب پرسنلی فعال یافت نشد" in text


def test_myunits_ignores_group_messages(management):
    event = message(user=202, chat_type="group")
    run(management.my_organization_units, event)
    event.answer.assert_not_awaited()


@pytest.mark.parametrize("handler,data,needs_state", [item for item in CALLBACKS if any(char.isdigit() for char in item[1]) or "{role}" in item[1]])
def test_malformed_numeric_callbacks_do_not_crash_or_mutate(management, handler, data, needs_state):
    data = data.format(role=management.role, permission=management.permission)
    parts = data.split("_")
    index = next(i for i, part in enumerate(parts) if part.isdecimal())
    parts[index] = "²"
    event = callback("_".join(parts))
    before = management.conn.total_changes
    args = (event, State()) if needs_state else (event,)
    run(getattr(management, handler), *args)
    assert event.answer.await_args.kwargs["show_alert"] is True
    assert management.conn.total_changes == before


@pytest.mark.parametrize("handler,data", [
    ("orgr_toggle","orgr_toggle_{role}_{permission}_2"), ("orgr_active","orgr_active_{role}_2"),
    ("orgr_set","orgr_set_2_1_{role}_2"), ("orgmem_join","orgmem_join_9223372036854775808_1"),
])
def test_invalid_flags_and_oversized_ids_are_rejected(management, handler, data):
    event = callback(data.format(role=management.role, permission=management.permission))
    before = management.conn.total_changes
    run(getattr(management, handler), event)
    assert event.answer.await_args.kwargs["show_alert"] is True
    assert management.conn.total_changes == before


@pytest.mark.parametrize("handler,data", [
    ("orgmem_remove","orgmem_remove_2_1"), ("orgmem_join","orgmem_join_3_1"),
    ("orgr_set","orgr_set_2_1_{role}_0"), ("orgr_toggle","orgr_toggle_{role}_{permission}_0"),
    ("orgr_active","orgr_active_{role}_0"),
])
def test_audit_failure_rolls_back_memberships_permissions_and_assignments(management, handler, data):
    tables = ("staff_mapping","staff_unit_memberships","staff_role_assignments","roles","role_permissions","audit_logs")
    before = {table:management.conn.execute(f"SELECT * FROM {table}").fetchall() for table in tables}
    management.conn.execute("CREATE TRIGGER fail_audit BEFORE INSERT ON audit_logs BEGIN SELECT RAISE(ABORT,'audit fixture'); END")
    run(getattr(management, handler), callback(data.format(role=management.role,permission=management.permission)))
    after = {table:management.conn.execute(f"SELECT * FROM {table}").fetchall() for table in tables}
    assert before == after


@pytest.mark.parametrize("operation,args", [
    (memberships.staff_for_admin,()), (memberships.person_for_admin,(2,)),
    (memberships.units_for_admin,()), (memberships.active_unit_for_admin,(1,)),
    (roles.roles_for_admin,()), (roles.permissions_for_admin,()), (roles.role_for_admin,(1,)),
    (roles.owned_for_admin,(1,)), (roles.membership_for_admin,(2,1)),
])
def test_application_reads_require_admin_even_without_transport(management, operation, args):
    with pytest.raises(OrganizationAdminError):
        operation(management.conn,202,*args)
