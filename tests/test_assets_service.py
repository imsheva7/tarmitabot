"""Asset authorization and atomic persistence with real isolated SQLite connections."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import sqlite3
import pytest
from erpbot.services import assets

TIME='1405/07/24 12:00'


@pytest.mark.parametrize('actor',[101,404,505])
def test_existing_admin_roles_can_assign_edit_and_return(assets_db,actor):
    aid=assets_db.assign(actor)
    with assets_db.connection() as conn:
        assert assets.recent(conn,actor)[0][0]==aid
        assets.edit(conn,actor,aid,'ویرایش')
        assets.return_by_admin(conn,actor,aid,'1405/07/25')
    assert assets_db.rows()[0]['details']=='ویرایش'
    assert assets_db.rows()[0]['return_date']=='1405/07/25'


@pytest.mark.parametrize('actor',[202,303,606,999])
@pytest.mark.parametrize('operation',['assign','edit','return','list','staff'])
def test_nonadmin_or_inactive_cannot_manage_assets(assets_db,actor,operation):
    aid=assets_db.assign()
    with assets_db.connection() as conn:
        with pytest.raises(assets.AssetError):
            if operation=='assign': assets.assign(conn,actor,2,'کارت سوخت','شرح',TIME)
            elif operation=='edit': assets.edit(conn,actor,aid,'new')
            elif operation=='return': assets.return_by_admin(conn,actor,aid,'1405/07/25')
            elif operation=='list': assets.recent(conn,actor)
            else: assets.staff_list(conn,actor)
    assert len(assets_db.rows())==1 and assets_db.rows()[0]['details']=='جزئیات'
    assert assets_db.rows()[0]['is_active']==1


def test_only_active_owner_can_confirm_once(assets_db):
    aid=assets_db.assign()
    with assets_db.connection() as conn:
        for actor in (101,303,606,999):
            with pytest.raises(assets.AssetError): assets.confirm_receipt(conn,actor,aid,TIME)
        assets.confirm_receipt(conn,202,aid,TIME)
        with pytest.raises(assets.AssetError): assets.confirm_receipt(conn,202,aid,TIME)
    assert 'تأیید قطعی توسط پرسنل' in assets_db.rows()[0]['approval_status']


def test_returned_asset_cannot_be_confirmed_or_requested_again(assets_db):
    aid=assets_db.assign()
    with assets_db.connection() as conn:
        assets.return_by_admin(conn,101,aid,'1405/07/24')
        with pytest.raises(assets.AssetError): assets.confirm_receipt(conn,202,aid,TIME)
    with pytest.raises(assets.AssetError): assets_db.request('عودت اموال',str(aid))


@pytest.mark.parametrize('owner',[6,999])
def test_inactive_or_missing_recipient_cannot_receive_asset(assets_db,owner):
    with pytest.raises(assets.AssetError): assets_db.assign(owner=owner)
    assert assets_db.rows()==[]


def test_active_unlinked_staff_can_still_receive_assignment(assets_db):
    aid=assets_db.assign(owner=7)
    assert assets_db.rows()[0]['id']==aid


def test_return_request_rechecks_ownership_at_submission_and_approval(assets_db):
    aid=assets_db.assign()
    with pytest.raises(assets.AssetError): assets_db.request('عودت اموال',str(aid),owner=303)
    rid=assets_db.request('عودت اموال',str(aid))
    with assets_db.connection() as conn:
        conn.execute('UPDATE user_assets SET staff_id=3 WHERE id=?',(aid,))
    with assets_db.connection() as conn:
        with pytest.raises(assets.AssetError): assets.approve(conn,101,rid,TIME)
    assert 'در انتظار' in assets_db.status(rid) and assets_db.rows()[0]['is_active']==1


def test_asset_request_approval_copies_encrypted_secret_and_is_idempotent(assets_db):
    rid=assets_db.request()
    with assets_db.connection() as conn:
        assert assets.approve(conn,101,rid,TIME).outcome=='approved'
        assert assets.approve(conn,101,rid,TIME).outcome=='already_processed'
    assert len(assets_db.rows())==1
    assert assets_db.rows()[0]['encrypted_password']=='encrypted-secret'
    assert 'تأیید قطعی توسط مدیر' in assets_db.rows()[0]['approval_status']


@pytest.mark.parametrize('actor',[202,404,505,606,999])
def test_final_approval_remains_main_admin_only(assets_db,actor):
    rid=assets_db.request()
    with assets_db.connection() as conn:
        with pytest.raises(assets.AssetError): assets.approve(conn,actor,rid,TIME)
    assert assets_db.rows()==[] and 'در انتظار' in assets_db.status(rid)


def test_return_approval_changes_request_and_asset_together(assets_db):
    aid=assets_db.assign()
    rid=assets_db.request('عودت اموال',str(aid))
    with assets_db.connection() as conn:
        assert assets.approve(conn,101,rid,TIME).outcome=='approved'
    assert assets_db.rows()[0]['is_active']==0 and assets_db.rows()[0]['return_date']=='1405/07/24'
    assert 'تأیید شده قطعی' in assets_db.status(rid)


@pytest.mark.parametrize('kind',['تحویل اموال','عودت اموال'])
@pytest.mark.parametrize('fail_table',['user_assets','requests'])
def test_failed_approval_rolls_back_asset_and_request(assets_db,kind,fail_table):
    aid=assets_db.assign() if kind=='عودت اموال' else None
    rid=assets_db.request(kind,str(aid) if aid else 'کارت سوخت')
    action='INSERT' if kind=='تحویل اموال' and fail_table=='user_assets' else 'UPDATE'
    with assets_db.connection() as conn:
        conn.execute(f"CREATE TRIGGER fail_asset BEFORE {action} ON {fail_table} BEGIN SELECT RAISE(ABORT,'asset failure'); END")
    with assets_db.connection() as conn:
        with pytest.raises(sqlite3.IntegrityError): assets.approve(conn,101,rid,TIME)
        assert not conn.in_transaction
    assert len(assets_db.rows())==(1 if aid else 0)
    if aid: assert assets_db.rows()[0]['is_active']==1
    assert 'در انتظار' in assets_db.status(rid)


def test_concurrent_approvals_create_only_one_asset(assets_db):
    rid=assets_db.request()
    barrier=Barrier(2)
    def approve():
        with assets_db.connection() as conn:
            barrier.wait(timeout=10)
            return assets.approve(conn,101,rid,TIME).outcome
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(approve),pool.submit(approve)]
        outcomes=[future.result(timeout=15) for future in futures]
    assert sorted(outcomes)==['already_processed','approved']
    assert len(assets_db.rows())==1


@pytest.mark.parametrize('bad_id',[None,True,0,-1,2**63,'1'])
def test_invalid_asset_ids_are_rejected_before_storage(assets_db,bad_id):
    with assets_db.connection() as conn:
        with pytest.raises(assets.AssetError): assets.owned_asset(conn,202,bad_id)


def test_final_submit_rechecks_requester_activity(assets_db):
    with assets_db.connection() as conn:
        conn.execute('UPDATE staff_mapping SET is_active=0 WHERE staff_id=2')
    with pytest.raises(assets.AssetError): assets_db.request()


@pytest.mark.parametrize('status',['❌ رد شده','❌ لغو شده توسط پرسنل'])
def test_rejected_or_cancelled_request_does_not_create_asset(assets_db,status):
    rid=assets_db.request()
    with assets_db.connection() as conn:
        conn.execute("UPDATE requests SET status=? WHERE id=?",(status,rid))
    with assets_db.connection() as conn:
        assert assets.approve(conn,101,rid,TIME).outcome=='already_processed'
    assert assets_db.rows()==[]


def test_requester_activity_is_rechecked_at_manager_approval(assets_db):
    rid=assets_db.request()
    with assets_db.connection() as conn:
        conn.execute('UPDATE staff_mapping SET is_active=0 WHERE staff_id=2')
    with assets_db.connection() as conn:
        with pytest.raises(assets.AssetError): assets.approve(conn,101,rid,TIME)
    assert assets_db.rows()==[] and 'در انتظار' in assets_db.status(rid)


@pytest.mark.parametrize('payload,expected',[
    ('poschg_yes','دارد'),('admprchg_no','ندارد'),('admposchg_invalid',None),('prchg_yes_extra',None),
])
def test_charger_selector_rejects_unknown_options(payload,expected):
    from erpbot.handlers.assets_common import charger_value
    if expected is None:
        with pytest.raises(assets.AssetError): charger_value(payload)
    else:
        assert charger_value(payload)==expected
