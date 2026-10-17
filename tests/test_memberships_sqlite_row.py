"""Regression: actual runtime uses sqlite3.Row, not tuple rows."""
import sqlite3
from pathlib import Path
import importlib.util

ROOT = Path(__file__).resolve().parents[1]

def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

schema = load(ROOT / 'erpbot/services/organization_schema.py', 'orgschema_row_test')
service = load(ROOT / 'erpbot/services/organization_memberships.py', 'orgmem_row_test')

def test_main_admin_can_revoke_with_runtime_row_factory():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    try:
        conn.execute('CREATE TABLE staff_mapping (staff_id INTEGER PRIMARY KEY, staff_name TEXT, role TEXT, is_active INTEGER)')
        conn.execute('CREATE TABLE requests (id INTEGER PRIMARY KEY)')
        conn.executemany('INSERT INTO staff_mapping VALUES (?,?,?,?)', [
            (1, 'admin', 'main_admin', 1),
            (2, 'employee', 'staff', 1),
        ])
        schema.migrate_organization_schema(conn)
        conn.execute("INSERT INTO org_units(unit_id,unit_code,unit_name) VALUES (1,'dispatch','Dispatch')")
        conn.execute("INSERT INTO org_units(unit_id,unit_code,unit_name) VALUES (2,'transport','Transport')")
        service.add_membership(conn, 2, 1, actor_staff_id=1)
        service.add_membership(conn, 2, 2, actor_staff_id=1)
        service.deactivate_membership(conn, 2, 2, actor_staff_id=1)
        assert [r[0] for r in service.active_memberships_for_staff(conn, 2)] == [1]
        assert conn.execute('SELECT is_active FROM staff_unit_memberships WHERE staff_id=2 AND unit_id=2').fetchone()[0] == 0
    finally:
        conn.close()
