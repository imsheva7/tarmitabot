"""Phase 4 security/behavior tests using in-memory SQLite only."""
import importlib.util
from pathlib import Path
import sqlite3
import pytest
ROOT=Path(__file__).resolve().parents[1]
def load(relative,name):
    spec=importlib.util.spec_from_file_location(name,ROOT/relative)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
schema=load('erpbot/services/organization_schema.py','phase4_schema')
roles=load('erpbot/services/organization_roles.py','phase4_roles')
member=load('erpbot/services/organization_memberships.py','phase4_members')
@pytest.fixture
def db():
    c=sqlite3.connect(':memory:')
    c.row_factory=sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    c.execute('CREATE TABLE staff_mapping(staff_id INTEGER PRIMARY KEY,staff_name TEXT,role TEXT,is_active INTEGER)')
    c.execute('CREATE TABLE requests(id INTEGER PRIMARY KEY)')
    c.executemany('INSERT INTO staff_mapping VALUES(?,?,?,?)',[(1,'Admin','main_admin',1),(2,'Employee','staff',1),(3,'Other','finance',1),(4,'Disabled','main_admin',0)])
    schema.migrate_organization_schema(c)
    c.executemany('INSERT INTO org_units(unit_id,unit_code,unit_name,is_active) VALUES(?,?,?,?)',[(1,'unit_a','A',1),(2,'unit_b','B',1),(3,'unit_c','C',0)])
    member.add_membership(c,2,1,actor_staff_id=1)
    member.add_membership(c,2,2,actor_staff_id=1)
    yield c
    c.close()
def created(db):return roles.create_role(db,'سرپرست پخش',actor_staff_id=1)
def test_role_default_has_no_perms(db):
    r=created(db)
    assert db.execute('SELECT COUNT(*) FROM role_permissions WHERE role_id=?',(r,)).fetchone()[0]==0
def test_duplicate_role_refused(db):
    created(db)
    with pytest.raises(roles.RoleError):created(db)
def test_row_factory_admin_authorized(db):assert created(db)>0
def test_other_staff_and_disabled_admin_denied(db):
    for actor in (2,3,4):
        with pytest.raises(roles.RoleError):roles.create_role(db,'test',actor_staff_id=actor)
def test_system_role_protected(db):
    system=db.execute("SELECT role_id FROM roles WHERE role_code='main_admin'").fetchone()[0]
    perm=roles.list_permissions(db)[0][0]
    for fn in (lambda:roles.set_role_permission(db,system,perm,True,actor_staff_id=1),lambda:roles.set_role_active(db,system,False,actor_staff_id=1),lambda:roles.assign_role(db,2,1,system,actor_staff_id=1)):
        with pytest.raises(roles.RoleError):fn()
def test_permissions_toggle(db):
    r=created(db); p=roles.list_permissions(db)[0][0]
    roles.set_role_permission(db,r,p,True,actor_staff_id=1)
    assert db.execute('SELECT COUNT(*) FROM role_permissions WHERE role_id=?',(r,)).fetchone()[0]==1
    roles.set_role_permission(db,r,p,False,actor_staff_id=1)
    assert db.execute('SELECT COUNT(*) FROM role_permissions WHERE role_id=?',(r,)).fetchone()[0]==0
def test_cannot_grant_unknown_permission(db):
    with pytest.raises(roles.RoleError):roles.set_role_permission(db,created(db),999,True,actor_staff_id=1)
def test_multiunit_roles_scoped(db):
    r=created(db)
    roles.assign_role(db,2,1,r,actor_staff_id=1)
    assert len(roles.staff_unit_roles(db,2,1))==1
    assert len(roles.staff_unit_roles(db,2,2))==0
    roles.assign_role(db,2,2,r,actor_staff_id=1)
    assert len(roles.staff_unit_roles(db,2,2))==1
    roles.revoke_role(db,2,1,r,actor_staff_id=1)
    assert roles.staff_unit_roles(db,2,1)==[]
    assert len(roles.staff_unit_roles(db,2,2))==1
def test_membership_required(db):
    r=created(db)
    with pytest.raises(roles.RoleError):roles.assign_role(db,3,1,r,actor_staff_id=1)
    with pytest.raises(roles.RoleError):roles.assign_role(db,2,3,r,actor_staff_id=1)
def test_deactivation_disables_assignment(db):
    r=created(db)
    roles.assign_role(db,2,1,r,actor_staff_id=1)
    roles.set_role_active(db,r,False,actor_staff_id=1)
    assert roles.staff_unit_roles(db,2,1)==[]
    roles.set_role_active(db,r,True,actor_staff_id=1)
    assert roles.staff_unit_roles(db,2,1)==[]
def test_rejoin_does_not_restore_role(db):
    r=created(db)
    roles.assign_role(db,2,1,r,actor_staff_id=1)
    member.deactivate_membership(db,2,1,actor_staff_id=1)
    member.add_membership(db,2,1,actor_staff_id=1)
    assert roles.staff_unit_roles(db,2,1)==[]
def test_audit_and_legacy_role_unchanged(db):
    r=created(db);roles.assign_role(db,2,1,r,actor_staff_id=1)
    assert db.execute('SELECT role FROM staff_mapping WHERE staff_id=2').fetchone()[0]=='staff'
    assert db.execute("SELECT COUNT(*) FROM audit_logs WHERE action_code LIKE 'organization.role.%'").fetchone()[0]==2
    assert db.execute('PRAGMA foreign_key_check').fetchall()==[]
def test_invalid_bool_or_ids(db):
    r=created(db);p=roles.list_permissions(db)[0][0]
    with pytest.raises(roles.RoleError):roles.set_role_permission(db,r,p,1,actor_staff_id=1)
    with pytest.raises(roles.RoleError):roles.assign_role(db,True,1,r,actor_staff_id=1)
