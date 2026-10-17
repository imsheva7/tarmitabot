"""Personnel/holiday mutations use synthetic data and the existing SQLite schema."""
import ast
from pathlib import Path
import sqlite3
import pytest
from erpbot.services import personnel,holidays
from erpbot.services.leave_workflow import working_days,holidays as leave_holidays

TIME='1405/07/25 12:00'


@pytest.fixture
def personnel_db(assets_db):
    with assets_db.connection() as conn:
        conn.executescript('''CREATE UNIQUE INDEX staff_name_unique ON staff_mapping(staff_name);
            CREATE TABLE leave_ledger(id INTEGER PRIMARY KEY,staff_id INTEGER,staff_name TEXT,
                change_amount REAL,description TEXT,registered_by TEXT,created_at TEXT);
            CREATE TABLE holidays(h_date TEXT PRIMARY KEY,description TEXT);
            INSERT INTO leave_ledger(staff_id,staff_name,change_amount) SELECT staff_id,staff_name,leave_balance FROM staff_mapping;
        ''')
    return assets_db


@pytest.mark.parametrize('actor',[202,404,505,606,999])
def test_mutations_require_current_main_admin(personnel_db,actor):
    db=personnel_db
    with db.connection() as conn:
        for operation in (
            lambda:personnel.add(conn,actor,'New','09120000001','staff',5,'1405/07/25',TIME),
            lambda:personnel.edit(conn,actor,2,'leave_balance','7',TIME),
            lambda:personnel.deactivate(conn,actor,2,'1405/07/25'),
            lambda:holidays.save(conn,actor,'1405/07/25','تعطیل'),
            lambda:holidays.delete(conn,actor,'1405/07/25'),
        ):
            with pytest.raises(personnel.PersonnelError): operation()
        assert conn.execute('SELECT COUNT(*) FROM staff_mapping').fetchone()[0]==7
        assert conn.execute('SELECT COUNT(*) FROM holidays').fetchone()[0]==0


def test_add_staff_and_initial_ledger_commit_together(personnel_db):
    with personnel_db.connection() as conn:
        sid=personnel.add(conn,101,'پرسنل جدید','۰۹۱۲۰۰۰۰۰۰۱','staff','۵.۵','۱۴۰۵/۷/۲۵',TIME)
        row=conn.execute('SELECT phone_number,leave_balance,employment_date FROM staff_mapping WHERE staff_id=?',(sid,)).fetchone()
        assert tuple(row)==('09120000001',5.5,'1405/07/25')
        assert conn.execute('SELECT SUM(change_amount) FROM leave_ledger WHERE staff_id=?',(sid,)).fetchone()[0]==5.5


def test_creation_failure_rolls_back_staff_insert(personnel_db):
    with personnel_db.connection() as conn:
        conn.execute("CREATE TRIGGER fail_ledger BEFORE INSERT ON leave_ledger BEGIN SELECT RAISE(ABORT,'failed'); END")
    with personnel_db.connection() as conn:
        with pytest.raises(sqlite3.IntegrityError): personnel.add(conn,101,'New','09120000001','staff',5,'1405/07/25',TIME)
        assert conn.execute('SELECT COUNT(*) FROM staff_mapping').fetchone()[0]==7


def test_balance_edit_matches_requested_value_and_does_not_repeat_ledger_entry(personnel_db):
    with personnel_db.connection() as conn:
        personnel.edit(conn,101,2,'leave_balance','۷.۵',TIME)
        personnel.edit(conn,101,2,'leave_balance','۷.۵',TIME)
        assert conn.execute('SELECT leave_balance FROM staff_mapping WHERE staff_id=2').fetchone()[0]==7.5
        assert conn.execute('SELECT SUM(change_amount) FROM leave_ledger WHERE staff_id=2').fetchone()[0]==7.5
        assert conn.execute('SELECT COUNT(*) FROM leave_ledger WHERE staff_id=2').fetchone()[0]==2


def test_old_balance_is_authoritative_and_reconciliation_is_explicit(personnel_db):
    with personnel_db.connection() as conn:
        conn.execute('UPDATE staff_mapping SET leave_balance=10 WHERE staff_id=2')
    with personnel_db.connection() as conn:
        personnel.edit(conn,101,2,'leave_balance','20',TIME)
        assert conn.execute('SELECT leave_balance FROM staff_mapping WHERE staff_id=2').fetchone()[0]==20
        assert conn.execute('SELECT SUM(change_amount) FROM leave_ledger WHERE staff_id=2').fetchone()[0]==20
        records=conn.execute('SELECT change_amount,description FROM leave_ledger WHERE staff_id=2 ORDER BY id').fetchall()
        assert records[1][0]==5 and records[1][1]=='تطبیق مانده پیشین با دفتر مرخصی'
        assert records[2][0]==10 and records[2][1]=='ویرایش دستی مانده'


def test_balance_update_failure_rolls_back_new_ledger_entry(personnel_db):
    with personnel_db.connection() as conn:
        conn.execute("CREATE TRIGGER fail_balance BEFORE UPDATE ON staff_mapping BEGIN SELECT RAISE(ABORT,'failed'); END")
    with personnel_db.connection() as conn:
        with pytest.raises(sqlite3.IntegrityError): personnel.edit(conn,101,2,'leave_balance','7',TIME)
        assert conn.execute('SELECT SUM(change_amount) FROM leave_ledger WHERE staff_id=2').fetchone()[0]==5


@pytest.mark.parametrize('value',['nan','inf','-inf','bad',None])
def test_nonfinite_or_invalid_balance_is_rejected(value):
    with pytest.raises(personnel.PersonnelError): personnel.balance_value(value)


def test_edit_does_not_allow_role_or_sql_field_injection(personnel_db):
    with personnel_db.connection() as conn:
        for field in ('role','is_active','staff_name = NULL; --'):
            with pytest.raises(personnel.PersonnelError): personnel.edit(conn,101,2,field,'main_admin',TIME)
        assert conn.execute('SELECT role FROM staff_mapping WHERE staff_id=2').fetchone()[0]=='staff'


def test_duplicate_phone_forms_and_names_are_rejected(personnel_db):
    with personnel_db.connection() as conn:
        personnel.add(conn,101,'New','09120000001','staff',0,'1405/07/25',TIME)
        with pytest.raises(personnel.PersonnelError): personnel.add(conn,101,'Second','+989120000001','staff',0,'1405/07/25',TIME)
        with pytest.raises(personnel.PersonnelError): personnel.add(conn,101,'New','09120000002','staff',0,'1405/07/25',TIME)
        with pytest.raises(personnel.PersonnelError): personnel.edit(conn,101,2,'phone_number','۹۸۹۱۲۰۰۰۰۰۰۱',TIME)


def test_settlement_preserves_records_balance_and_ledger_but_revokes_account_and_assets(personnel_db):
    personnel_db.assign()
    with personnel_db.connection() as conn:
        personnel.deactivate(conn,101,2,'1405/07/25')
        assert tuple(conn.execute('SELECT is_active,telegram_user_id,deactivation_date,leave_balance FROM staff_mapping WHERE staff_id=2').fetchone())==(0,None,'1405/07/25',5)
        assert conn.execute('SELECT is_active FROM user_assets').fetchone()[0]==0
        assert conn.execute('SELECT SUM(change_amount) FROM leave_ledger WHERE staff_id=2').fetchone()[0]==5
        with pytest.raises(personnel.PersonnelError): personnel.deactivate(conn,101,2,'1405/07/26')


def test_settlement_failure_rolls_back_disconnection_and_assets(personnel_db):
    personnel_db.assign()
    with personnel_db.connection() as conn:
        conn.execute("CREATE TRIGGER fail_assets BEFORE UPDATE ON user_assets BEGIN SELECT RAISE(ABORT,'failed'); END")
    with personnel_db.connection() as conn:
        with pytest.raises(sqlite3.IntegrityError): personnel.deactivate(conn,101,2,'1405/07/25')
        assert tuple(conn.execute('SELECT is_active,telegram_user_id FROM staff_mapping WHERE staff_id=2').fetchone())==(1,202)
        assert conn.execute('SELECT is_active FROM user_assets').fetchone()[0]==1


def test_holiday_upsert_delete_and_leave_calendar_use_same_existing_table(personnel_db):
    with personnel_db.connection() as conn:
        holidays.save(conn,101,'۱۴۰۵/۷/۲۵','اول')
        holidays.save(conn,101,'1405/07/25','دوم')
        assert [tuple(row) for row in holidays.recent(conn,101)]==[('1405/07/25','دوم')]
        assert working_days('1405/07/25','1405/07/26',leave_holidays(conn))==1
        holidays.delete(conn,101,'1405/07/25')
        assert working_days('1405/07/25','1405/07/26',leave_holidays(conn))==2


def test_holiday_invalid_date_and_legacy_unpadded_delete(personnel_db):
    with personnel_db.connection() as conn:
        with pytest.raises(personnel.PersonnelError): holidays.save(conn,101,'1405/12/30','invalid')
        conn.execute("INSERT INTO holidays VALUES('1405/7/25','legacy')")
    with personnel_db.connection() as conn:
        assert holidays.delete(conn,101,'1405/7/25')==1


@pytest.mark.parametrize('path',['handlers/personnel.py','handlers/holidays.py','services/personnel.py','services/holidays.py'])
def test_new_controllers_and_services_have_no_sql_or_runtime_import(path):
    tree=ast.parse((Path(__file__).resolve().parents[1]/'erpbot'/path).read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if isinstance(node,ast.ImportFrom):
            assert 'runtime' not in (node.module or '')
            assert all(alias.name!='*' for alias in node.names)
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute):
            assert node.func.attr not in ('execute','executemany','executescript','cursor','commit','rollback')
