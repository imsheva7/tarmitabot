"""Isolated tests: no bot token, Telegram, or company database required."""
import importlib.util
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / 'erpbot' / 'services' / 'organization_schema.py'
spec = importlib.util.spec_from_file_location('organization_schema', MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def make_conn():
    conn = sqlite3.connect(':memory:')
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('CREATE TABLE staff_mapping(staff_id INTEGER PRIMARY KEY, staff_name TEXT, role TEXT)')
    conn.execute('CREATE TABLE requests(id INTEGER PRIMARY KEY, status TEXT)')
    conn.execute("INSERT INTO staff_mapping VALUES (1,'مدیر اصلی','main_admin')")
    conn.execute("INSERT INTO staff_mapping VALUES (2,'کارمند','staff')")
    conn.execute("INSERT INTO requests VALUES (100,'pending')")
    conn.commit()
    return conn


def test_migration_additive_idempotent():
    with closing(make_conn()) as conn:
        module.migrate_organization_schema(conn)
        conn.commit()
        module.migrate_organization_schema(conn)
        conn.commit()
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {'org_units','staff_unit_memberships','roles','permissions',
                'role_permissions','staff_role_assignments','approval_policies',
                'approval_actions','audit_logs'} <= tables
        assert conn.execute('SELECT COUNT(*) FROM roles').fetchone()[0] == 4
        assert conn.execute('SELECT COUNT(*) FROM permissions').fetchone()[0] == 8
        assert conn.execute('SELECT COUNT(*) FROM staff_mapping').fetchone()[0] == 2
        assert conn.execute('SELECT COUNT(*) FROM role_permissions').fetchone()[0] == 0
        assert conn.execute('SELECT COUNT(*) FROM staff_role_assignments').fetchone()[0] == 0


def test_one_person_multiple_units_roles_scoped():
    with closing(make_conn()) as conn:
        module.migrate_organization_schema(conn)
        conn.executemany('INSERT INTO org_units(unit_code,unit_name) VALUES (?,?)',
                         [('dispatch','پخش'),('warehouse','انبار')])
        conn.executemany('INSERT INTO staff_unit_memberships(staff_id,unit_id) VALUES (2,?)', [(1,),(2,)])
        conn.execute("INSERT INTO roles(role_code,role_name) VALUES ('supervisor','سرپرست')")
        role_id = conn.execute("SELECT role_id FROM roles WHERE role_code='supervisor'").fetchone()[0]
        conn.execute('INSERT INTO staff_role_assignments(staff_id,role_id,unit_id) VALUES (2,?,1)', (role_id,))
        conn.execute("INSERT INTO staff_role_assignments(staff_id,role_id,unit_id) VALUES (2,(SELECT role_id FROM roles WHERE role_code='staff'),2)")
        assert conn.execute('SELECT COUNT(*) FROM staff_unit_memberships WHERE staff_id=2').fetchone()[0] == 2
        assert conn.execute('SELECT COUNT(*) FROM staff_role_assignments WHERE staff_id=2').fetchone()[0] == 2


def test_assignment_must_have_unit_membership():
    with closing(make_conn()) as conn:
        module.migrate_organization_schema(conn)
        conn.execute("INSERT INTO org_units(unit_code,unit_name) VALUES ('warehouse','انبار')")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO staff_role_assignments(staff_id,role_id,unit_id) VALUES (2,(SELECT role_id FROM roles WHERE role_code='staff'),1)")


def test_invalid_approval_action_rejected():
    with closing(make_conn()) as conn:
        module.migrate_organization_schema(conn)
        conn.execute("INSERT INTO org_units(unit_code,unit_name) VALUES ('dispatch','پخش')")
        conn.execute("INSERT INTO approval_policies(policy_code,request_kind,permission_id,unit_id) VALUES ('leave-unit','leave',(SELECT permission_id FROM permissions WHERE permission_code='leave.approve_unit'),1)")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO approval_actions(policy_id,request_id,actor_staff_id,unit_id,decision) VALUES (1,100,2,1,'magic')")
        conn.execute("INSERT INTO approval_actions(policy_id,request_id,actor_staff_id,unit_id,decision) VALUES (1,100,2,1,'approved')")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO approval_actions(policy_id,request_id,actor_staff_id,unit_id,decision) VALUES (1,100,2,1,'approved')")


def test_fail_closed_without_foreign_keys():
    conn = sqlite3.connect(':memory:')
    try:
        with pytest.raises(RuntimeError, match='foreign key'):
            module.migrate_organization_schema(conn)
    finally:
        conn.close()


def test_admin_legacy_role_unchanged():
    with closing(make_conn()) as conn:
        module.migrate_organization_schema(conn)
        assert conn.execute('SELECT role FROM staff_mapping WHERE staff_id=1').fetchone()[0] == 'main_admin'
        assert conn.execute("SELECT is_protected FROM roles WHERE role_code='main_admin'").fetchone()[0] == 1
