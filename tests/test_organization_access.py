"""Phase 5A tests: isolated, in-memory DB, no Telegram or production data."""
import importlib.util
from pathlib import Path
import sqlite3
import pytest

ROOT = Path(__file__).resolve().parents[1]

def load(path, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

schema = load('erpbot/services/organization_schema.py', 'p5_schema')
access = load('erpbot/services/organization_access.py', 'p5_access')

@pytest.fixture
def db():
    c = sqlite3.connect(':memory:')
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    c.execute('CREATE TABLE staff_mapping(staff_id INTEGER PRIMARY KEY, role TEXT, is_active INTEGER)')
    c.execute('CREATE TABLE requests(id INTEGER PRIMARY KEY)')
    c.executemany('INSERT INTO staff_mapping VALUES(?,?,?)', [(1,'main_admin',1),(2,'staff',1),(3,'staff',0)])
    schema.migrate_organization_schema(c)
    c.executemany('INSERT INTO org_units(unit_id,unit_code,unit_name) VALUES(?,?,?)', [(1,'dispatch','Dispatch'),(2,'warehouse','Warehouse')])
    c.execute('INSERT INTO staff_unit_memberships(staff_id,unit_id) VALUES(2,1)')
    c.execute("INSERT INTO roles(role_code,role_name) VALUES('testrole','Test role')")
    role = c.execute("SELECT role_id FROM roles WHERE role_code='testrole'").fetchone()[0]
    perm = c.execute("SELECT permission_id FROM permissions WHERE permission_code='staff.view_unit'").fetchone()[0]
    c.execute('INSERT INTO role_permissions VALUES(?,?)', (role,perm))
    c.execute('INSERT INTO staff_role_assignments(staff_id,role_id,unit_id) VALUES(2,?,1)', (role,))
    yield c,role,perm
    c.close()

def allowed(db):
    return access.has_unit_permission(db[0],2,1,'staff.view_unit')

def test_allow_correct_scope(db): assert allowed(db)
def test_deny_other_unit(db): assert not access.has_unit_permission(db[0],2,2,'staff.view_unit')
def test_deny_other_permission(db): assert not access.has_unit_permission(db[0],2,1,'leave.approve_unit')
def test_deny_unknown_and_inactive_staff(db):
    assert not access.has_unit_permission(db[0],3,1,'staff.view_unit')
    assert not access.has_unit_permission(db[0],999,1,'staff.view_unit')
def test_no_implicit_admin_bypass(db): assert not access.has_unit_permission(db[0],1,1,'staff.view_unit')
def test_revoked_assignment(db):
    db[0].execute('UPDATE staff_role_assignments SET is_active=0')
    assert not allowed(db)
def test_inactive_membership(db):
    db[0].execute('UPDATE staff_unit_memberships SET is_active=0')
    assert not allowed(db)
def test_inactive_unit(db):
    db[0].execute('UPDATE org_units SET is_active=0 WHERE unit_id=1')
    assert not allowed(db)
def test_inactive_role(db):
    db[0].execute('UPDATE roles SET is_active=0 WHERE role_id=?',(db[1],))
    assert not allowed(db)
def test_inactive_permission(db):
    db[0].execute('UPDATE permissions SET is_active=0 WHERE permission_id=?',(db[2],))
    assert not allowed(db)
def test_invalid_inputs(db):
    for sid,uid,code in [(True,1,'staff.view_unit'),(2,True,'staff.view_unit'),(0,1,'staff.view_unit'),(2,1,''),(2,1,None)]:
        assert not access.has_unit_permission(db[0],sid,uid,code)
def test_missing_schema_fails_closed():
    c=sqlite3.connect(':memory:')
    assert not access.has_unit_permission(c,2,1,'staff.view_unit')
    c.close()
def test_require_raises(db):
    access.require_unit_permission(db[0],2,1,'staff.view_unit')
    with pytest.raises(PermissionError): access.require_unit_permission(db[0],2,2,'staff.view_unit')
