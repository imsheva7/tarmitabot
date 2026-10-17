"""Isolated multiunit membership tests; never connects to company DB."""
import importlib.util
import sqlite3
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
def load(p,name):
    spec=importlib.util.spec_from_file_location(name,p)
    obj=importlib.util.module_from_spec(spec);spec.loader.exec_module(obj);return obj
schema=load(ROOT/'erpbot/services/organization_schema.py','schema_org3')
m=load(ROOT/'erpbot/services/organization_memberships.py','membership_org3')
@pytest.fixture
def db():
    c=sqlite3.connect(':memory:');c.execute('PRAGMA foreign_keys=ON')
    c.execute('CREATE TABLE staff_mapping (staff_id INTEGER PRIMARY KEY,staff_name TEXT,role TEXT,is_active INTEGER)')
    c.execute('CREATE TABLE requests (id INTEGER PRIMARY KEY)')
    c.executemany('INSERT INTO staff_mapping VALUES (?,?,?,?)', [(1,'admin','main_admin',1),(2,'staff','staff',1),(3,'manager','finance',1),(4,'inactive','staff',0)])
    schema.migrate_organization_schema(c)
    c.executemany('INSERT INTO org_units(unit_id,unit_code,unit_name,is_active) VALUES (?,?,?,?)', [(1,'aa','A',1),(2,'bb','B',1),(3,'cc','C',0)])
    yield c;c.close()
def test_multiple_memberships(db):
    m.add_membership(db,2,1,actor_staff_id=1);m.add_membership(db,2,2,actor_staff_id=1)
    assert {x[0] for x in m.active_memberships_for_staff(db,2)}=={1,2}
    assert m.active_members_of_unit(db,1)==[(2,'staff')]
def test_no_legacy_role_changes(db):
    m.add_membership(db,2,1,actor_staff_id=1)
    assert db.execute('SELECT role FROM staff_mapping WHERE staff_id=2').fetchone()[0]=='staff'
def test_duplicate_rejected(db):
    m.add_membership(db,2,1,actor_staff_id=1)
    with pytest.raises(m.MembershipError):m.add_membership(db,2,1,actor_staff_id=1)
def test_invalid_actor_denied(db):
    with pytest.raises(m.MembershipError):m.add_membership(db,2,1,actor_staff_id=3)
    with pytest.raises(m.MembershipError):m.deactivate_membership(db,2,1,actor_staff_id=3)
def test_inactive_unit_denied(db):
    with pytest.raises(m.MembershipError):m.add_membership(db,2,3,actor_staff_id=1)
def test_inactive_staff_denied(db):
    with pytest.raises(m.MembershipError):m.add_membership(db,4,1,actor_staff_id=1)
def test_remove_and_restore(db):
    m.add_membership(db,2,1,actor_staff_id=1)
    m.deactivate_membership(db,2,1,actor_staff_id=1)
    assert m.active_memberships_for_staff(db,2)==[]
    assert db.execute('SELECT left_at FROM staff_unit_memberships WHERE staff_id=2 AND unit_id=1').fetchone()[0]
    m.add_membership(db,2,1,actor_staff_id=1)
    assert m.active_memberships_for_staff(db,2)==[(1,'A')]
def test_removed_membership_disables_scoped_role(db):
    m.add_membership(db,2,1,actor_staff_id=1)
    rid=db.execute("SELECT role_id FROM roles WHERE role_code='staff'").fetchone()[0]
    db.execute('INSERT INTO staff_role_assignments(staff_id,role_id,unit_id) VALUES (2,?,1)',(rid,))
    m.deactivate_membership(db,2,1,actor_staff_id=1)
    assert db.execute('SELECT is_active FROM staff_role_assignments').fetchone()[0]==0
    m.add_membership(db,2,1,actor_staff_id=1)
    assert db.execute('SELECT is_active FROM staff_role_assignments').fetchone()[0]==0
def test_audit_trail(db):
    m.add_membership(db,2,1,actor_staff_id=1);m.deactivate_membership(db,2,1,actor_staff_id=1)
    assert db.execute('SELECT COUNT(*) FROM audit_logs').fetchone()[0]==2
def test_no_delete(db):
    m.add_membership(db,2,1,actor_staff_id=1);m.deactivate_membership(db,2,1,actor_staff_id=1)
    assert db.execute('SELECT COUNT(*) FROM staff_unit_memberships').fetchone()[0]==1
@pytest.mark.parametrize('bad',[0,-2,True,'1',None])
def test_invalid_ids(db,bad):
    with pytest.raises(m.MembershipError):m.add_membership(db,bad,1,actor_staff_id=1)
