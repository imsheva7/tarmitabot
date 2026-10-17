"""Maintenance semantics on synthetic SQLite data with real RBAC foreign keys."""
import sqlite3
from types import SimpleNamespace
import pytest
from erpbot.services import maintenance as service
from erpbot.services.organization_schema import migrate_organization_schema

STAMP='1405/07/25 12:00'


@pytest.fixture
def maintenance_db(assets_db):
    db=assets_db
    rid=db.request('درخواست قدیمی')
    db.assign()
    with db.connection() as conn:
        conn.executescript('''
            CREATE TABLE leave_ledger(id INTEGER PRIMARY KEY,staff_id INTEGER,staff_name TEXT,
                change_amount REAL,description TEXT,registered_by TEXT,created_at TEXT);
            INSERT INTO leave_ledger(staff_id,staff_name,change_amount) SELECT staff_id,staff_name,leave_balance FROM staff_mapping;
            CREATE TABLE holidays(h_date TEXT PRIMARY KEY,description TEXT);
            INSERT INTO holidays VALUES('1405/08/01','Holiday');
            CREATE TABLE reminders(id INTEGER PRIMARY KEY,text_content TEXT);
            INSERT INTO reminders VALUES(1,'Preserve reminder');
            CREATE TABLE request_effects(request_id INTEGER REFERENCES requests(id),effect_type TEXT,PRIMARY KEY(request_id,effect_type));
            INSERT INTO vehicle_insurances(car_code,car_name) VALUES('car','Car');
        ''')
        migrate_organization_schema(conn)
        unit=conn.execute("INSERT INTO org_units(unit_code,unit_name) VALUES('TEST','Test unit')").lastrowid
        conn.execute('INSERT INTO staff_unit_memberships(staff_id,unit_id) VALUES(2,?)',(unit,))
        permission=conn.execute("SELECT permission_id FROM permissions WHERE permission_code='leave.approve_unit'").fetchone()[0]
        policy=conn.execute("INSERT INTO approval_policies(policy_code,request_kind,permission_id,unit_id) VALUES('TEST','مرخصی',?,?)",(permission,unit)).lastrowid
        conn.execute("INSERT INTO approval_actions(policy_id,request_id,actor_staff_id,unit_id,decision) VALUES(?,?,1,?,'approved')",(policy,rid,unit))
        conn.execute("INSERT INTO request_effects VALUES(?,'test-effect')",(rid,))
        conn.execute("INSERT INTO request_replacements VALUES(?,3,'approved')",(rid,))
        conn.execute("INSERT INTO audit_logs(actor_staff_id,action_code,entity_type,entity_id) VALUES(1,'test.seed','test','1')")
        # Preserve current balance, even if historical ledger differs.
        conn.execute('UPDATE staff_mapping SET leave_balance=10 WHERE staff_id=2')
    return db


def digest(db):
    with db.connection() as conn: return service.fingerprint(conn)


def rows(conn,table):
    return [tuple(row) for row in conn.execute(f'SELECT * FROM {table}')]


@pytest.mark.parametrize('target',list(service.TITLES))
def test_reset_only_changes_approved_scope_and_preserves_schema(maintenance_db,target):
    db=maintenance_db
    preserved=('staff_mapping','org_units','staff_unit_memberships','roles','permissions','approval_policies','reminders')
    with db.connection() as conn:
        original={table:rows(conn,table) for table in preserved}
        schema=rows(conn,'sqlite_master')
        audit_count=conn.execute('SELECT COUNT(*) FROM audit_logs').fetchone()[0]
    with service.prepared_backup(db.connection,db.path,101) as (_,backup_digest):
        with db.connection() as conn:
            counts=service.execute(conn,101,target,backup_digest,STAMP)
    with db.connection() as conn:
        assert rows(conn,'sqlite_master')==schema
        assert conn.execute('PRAGMA foreign_key_check').fetchall()==[]
        for table in preserved:
            if table=='staff_mapping' and target=='leaves':
                assert all(row[0]==0 for row in conn.execute('SELECT leave_balance FROM staff_mapping'))
                current=rows(conn,table)
                # Only the leave_balance column changes.
                index=[col[1] for col in conn.execute('PRAGMA table_info(staff_mapping)')].index('leave_balance')
                assert [r[:index]+r[index+1:] for r in current]==[r[:index]+r[index+1:] for r in original[table]]
            else: assert rows(conn,table)==original[table]
        for table in counts:
            if table!='leave_ledger' or target!='all_except_staff':
                assert conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]==0
        if target=='all_except_staff':
            for sid,balance in conn.execute('SELECT staff_id,leave_balance FROM staff_mapping'):
                assert conn.execute('SELECT COALESCE(SUM(change_amount),0) FROM leave_ledger WHERE staff_id=?',(sid,)).fetchone()[0]==balance
            assert conn.execute('SELECT description FROM leave_ledger WHERE staff_id=2').fetchone()[0]=='مانده افتتاحیه پس از پاکسازی جامع'
        assert conn.execute('SELECT COUNT(*) FROM audit_logs').fetchone()[0]==audit_count+1
        assert conn.execute("SELECT COUNT(*) FROM audit_logs WHERE action_code='database.reset'").fetchone()[0]==1


@pytest.mark.parametrize('actor',[202,404,505,606,999])
def test_reset_and_preview_require_current_main_admin(maintenance_db,actor):
    db=maintenance_db
    before=digest(db)
    with db.connection() as conn,pytest.raises(service.PersonnelError): service.preview(conn,actor,'requests')
    with db.connection() as conn,pytest.raises(service.PersonnelError): service.execute(conn,actor,'requests',before,STAMP)
    assert digest(db)==before


@pytest.mark.parametrize('target',['unknown','requests; DROP TABLE staff_mapping',None])
def test_invalid_targets_are_rejected(maintenance_db,target):
    db=maintenance_db
    before=digest(db)
    with db.connection() as conn,pytest.raises(service.MaintenanceError): service.execute(conn,101,target,before,STAMP)
    assert digest(db)==before


def test_concurrent_write_after_snapshot_blocks_reset(maintenance_db):
    db=maintenance_db
    with service.prepared_backup(db.connection,db.path,101) as (_,backup_digest):
        with db.connection() as conn:
            conn.execute("UPDATE reminders SET text_content='New data not in backup'")
        before=digest(db)
        with db.connection() as conn,pytest.raises(service.MaintenanceError,match='تغییر'):
            service.execute(conn,101,'all_except_staff',backup_digest,STAMP)
    assert digest(db)==before


def test_role_revoked_after_backup_blocks_reset(maintenance_db):
    db=maintenance_db
    with service.prepared_backup(db.connection,db.path,101) as (_,backup_digest):
        with db.connection() as conn: conn.execute("UPDATE staff_mapping SET role='staff' WHERE telegram_user_id=101")
        before=digest(db)
        with db.connection() as conn,pytest.raises(service.PersonnelError): service.execute(conn,101,'requests',backup_digest,STAMP)
    assert digest(db)==before


@pytest.mark.parametrize('failure',['delete','ledger','audit'])
def test_failure_at_any_late_step_rolls_back_entire_reset(maintenance_db,failure):
    db=maintenance_db
    table,operation={'delete':('leave_ledger','DELETE'),'ledger':('leave_ledger','INSERT'),'audit':('audit_logs','INSERT')}[failure]
    with db.connection() as conn:
        conn.execute(f"CREATE TRIGGER fail_reset BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT,'simulated failure'); END")
    before=digest(db)
    with service.prepared_backup(db.connection,db.path,101) as (_,backup_digest):
        with db.connection() as conn,pytest.raises(sqlite3.IntegrityError):
            service.execute(conn,101,'all_except_staff',backup_digest,STAMP)
    assert digest(db)==before


def test_old_backup_cannot_be_reused_for_second_reset(maintenance_db):
    db=maintenance_db
    with service.prepared_backup(db.connection,db.path,101) as (_,backup_digest):
        with db.connection() as conn: service.execute(conn,101,'requests',backup_digest,STAMP)
        before=digest(db)
        with db.connection() as conn,pytest.raises(service.MaintenanceError): service.execute(conn,101,'requests',backup_digest,STAMP)
    assert digest(db)==before


@pytest.mark.parametrize('backup_digest',[None,'','x'*64,'ش'*64])
def test_missing_or_malformed_backup_digest_cannot_reset(maintenance_db,backup_digest):
    db=maintenance_db
    before=digest(db)
    with db.connection() as conn,pytest.raises(service.MaintenanceError): service.execute(conn,101,'requests',backup_digest,STAMP)
    assert digest(db)==before
