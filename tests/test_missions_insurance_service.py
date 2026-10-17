"""Mission decisions and insurance rules on real isolated SQLite."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import sqlite3
import jdatetime
import pytest
from erpbot.services import missions,insurance


@pytest.mark.parametrize('start,end,days',[
    ('۱۴۰۵/۷/۲۴','1405/07/24',1),('1405/07/24','1405/07/25',2),
    ('1403/12/29','1404/01/01',3),
])
def test_mission_days_are_inclusive_and_include_fridays(start,end,days):
    first,last,count=missions.date_range(start,end)
    assert count==days and len(first)==len(last)==10


@pytest.mark.parametrize('start,end',[
    ('1405/07/25','1405/07/24'),('1405/12/30','1406/01/01'),(None,'1405/07/24'),('bad','bad'),
])
def test_invalid_mission_date_ranges_are_rejected(start,end):
    with pytest.raises(missions.MissionError): missions.date_range(start,end)


@pytest.mark.parametrize('actor',[202,303,404,505,606,999])
def test_mission_approval_is_main_admin_only(assets_db,actor):
    rid=assets_db.request('ماموریت')
    with assets_db.connection() as conn:
        with pytest.raises(missions.MissionError): missions.approve(conn,actor,rid)
    assert 'در انتظار' in assets_db.status(rid)


@pytest.mark.parametrize('status',['❌ رد شده','❌ لغو شده توسط پرسنل','✅ تأیید شده قطعی'])
def test_completed_mission_cannot_be_approved_again(assets_db,status):
    rid=assets_db.request('ماموریت')
    with assets_db.connection() as conn:
        conn.execute('UPDATE requests SET status=? WHERE id=?',(status,rid))
    with assets_db.connection() as conn:
        assert missions.approve(conn,101,rid).outcome=='already_processed'
    assert assets_db.status(rid)==status


def test_mission_approval_rejects_other_request_types_and_pending_replacement(assets_db):
    other=assets_db.request('مساعده')
    rid=assets_db.request('ماموریت')
    with assets_db.connection() as conn:
        conn.execute('INSERT INTO request_replacements VALUES(?,3,NULL)',(rid,))
    with assets_db.connection() as conn:
        assert missions.approve(conn,101,other).outcome=='not_found'
        assert missions.approve(conn,101,rid).outcome=='replacement_pending'


def test_simultaneous_mission_approval_commits_once(assets_db):
    rid=assets_db.request('ماموریت')
    barrier=Barrier(2)
    def approve():
        with assets_db.connection() as conn:
            barrier.wait(timeout=10)
            return missions.approve(conn,101,rid).outcome
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(approve),pool.submit(approve)]
        assert sorted(f.result(timeout=15) for f in futures)==['already_processed','approved']


def test_mission_approval_failure_rolls_back(assets_db):
    rid=assets_db.request('ماموریت')
    with assets_db.connection() as conn:
        conn.execute("CREATE TRIGGER fail_mission BEFORE UPDATE ON requests BEGIN SELECT RAISE(ABORT,'failed'); END")
    with assets_db.connection() as conn:
        with pytest.raises(sqlite3.IntegrityError): missions.approve(conn,101,rid)
        assert not conn.in_transaction
    assert 'در انتظار' in assets_db.status(rid)


def test_mission_submission_rechecks_active_staff(assets_db):
    with assets_db.connection() as conn:
        conn.execute('UPDATE staff_mapping SET is_active=0 WHERE staff_id=2')
    with pytest.raises(missions.MissionError): assets_db.request('ماموریت')


@pytest.mark.parametrize('actor',[101,404,505])
def test_existing_admin_roles_can_register_insurance(assets_db,actor):
    with assets_db.connection() as conn:
        insurance.save(conn,actor,'CAR','خودرو','پلاک','شرکت','۱۴۰۵/۷/۳','-')
    with assets_db.connection() as conn:
        row=conn.execute('SELECT third_party_date,body_date FROM vehicle_insurances').fetchone()
    assert tuple(row)==('1405/07/03','-')


@pytest.mark.parametrize('actor',[202,303,606,999])
def test_ordinary_disabled_or_unknown_cannot_register_or_choose_car(assets_db,actor):
    with assets_db.connection() as conn:
        with pytest.raises(insurance.InsuranceError): insurance.cars(conn,actor)
        with pytest.raises(insurance.InsuranceError): insurance.save(conn,actor,'CAR','Car','Plate','Company','1405/07/24','-')
    with assets_db.connection() as conn:
        assert conn.execute('SELECT COUNT(*) FROM vehicle_insurances').fetchone()[0]==0


@pytest.mark.parametrize('third,body',[
    ('bad','-'),('1405/12/30','-'),('1405/07/24','bad'),(None,'-'),
])
def test_invalid_insurance_date_cannot_be_saved(assets_db,third,body):
    with assets_db.connection() as conn:
        with pytest.raises(insurance.InsuranceError): insurance.save(conn,101,'CAR','Car','Plate','Company',third,body)
    with assets_db.connection() as conn:
        assert conn.execute('SELECT COUNT(*) FROM vehicle_insurances').fetchone()[0]==0


def test_car_selection_supports_old_codes_and_rechecks_activity_on_final_save(assets_db):
    with assets_db.connection() as conn:
        aid=conn.execute("INSERT INTO user_assets(asset_type,details,is_active) VALUES('خودروی سازمانی','کد: CAR-01 | پلاک: A',1)").lastrowid
    with assets_db.connection() as conn:
        assert insurance.cars(conn,101)==[(aid,'CAR-01')]
        assert insurance.selected_car(conn,101,'CAR-01')=='CAR-01'
        assert insurance.selected_car(conn,101,asset_id=aid)=='CAR-01'
        conn.execute('UPDATE user_assets SET is_active=0 WHERE id=?',(aid,))
    with assets_db.connection() as conn:
        with pytest.raises(insurance.InsuranceError): insurance.selected_car(conn,101,'CAR-01')
        with pytest.raises(insurance.InsuranceError): insurance.save(conn,101,'CAR-01','Car','Plate','Company','1405/07/24','-',asset_id=aid)


@pytest.mark.parametrize('selector',['id_0','id_-1','id_'+'9'*100,'id_bad','forged-code'])
def test_invalid_car_callback_is_rejected(assets_db,selector):
    with assets_db.connection() as conn:
        with pytest.raises(insurance.InsuranceError): insurance.selected_car(conn,101,selector)


def test_insurance_insert_failure_rolls_back(assets_db):
    with assets_db.connection() as conn:
        conn.execute("CREATE TRIGGER fail_insurance BEFORE INSERT ON vehicle_insurances BEGIN SELECT RAISE(ABORT,'failed'); END")
    with assets_db.connection() as conn:
        with pytest.raises(sqlite3.IntegrityError): insurance.save(conn,101,'CAR','Car','Plate','Company','1405/07/24','-')
        assert not conn.in_transaction
