"""Atomic shared decisions on synthetic SQLite data; no Telegram traffic."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import sqlite3
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from erpbot.services import request_decisions as service
from erpbot.handlers.request_decisions import create_router


def details(db,rid):
    with db.connection() as conn:
        return conn.execute('SELECT req_code,rejection_reason FROM requests WHERE id=?',(rid,)).fetchone()


@pytest.mark.parametrize('actor',[202,404,505,606,999])
def test_only_current_active_main_admin_can_decide(assets_db,actor):
    rid=assets_db.request('درخواست قدیمی')
    for action in ('approve','inspect','reject'):
        with assets_db.connection() as conn,pytest.raises(service.PersonnelError):
            if action=='approve': service.approve(conn,actor,rid)
            elif action=='inspect': service.inspect_decision(conn,actor,rid,'reject')
            else: service.reject(conn,actor,rid,'Reason')
    assert 'در انتظار' in assets_db.status(rid)


@pytest.mark.parametrize('kind',['مرخصی','ماموریت','مساعده','تنخواه','خرید ملزومات','تحویل اموال','عودت اموال'])
def test_shared_approval_cannot_bypass_specialized_workflows(assets_db,kind):
    # Insert directly to avoid specialized submission prerequisites.
    with assets_db.connection() as conn:
        rid=conn.execute("INSERT INTO requests(telegram_user_id,request_type,status) VALUES(202,?,'در انتظار')",(kind,)).lastrowid
    with assets_db.connection() as conn:
        assert service.approve(conn,101,rid).outcome=='invalid_type'
    assert assets_db.status(rid)=='در انتظار'


@pytest.mark.parametrize('status',['✅ تأیید شده قطعی','❌ رد شده','❌ لغو شده توسط پرسنل',None])
def test_final_or_missing_status_cannot_be_overwritten(assets_db,status):
    rid=assets_db.request('درخواست قدیمی')
    code=details(assets_db,rid)[0]
    with assets_db.connection() as conn:
        conn.execute('UPDATE requests SET status=? WHERE id=?',(status,rid))
    with assets_db.connection() as conn:
        assert service.approve(conn,101,rid).outcome=='already_processed'
        assert service.reject(conn,101,rid,'reason').outcome=='already_processed'
        assert service.cancel(conn,202,code).outcome=='cannot_cancel'
    assert assets_db.status(rid)==status


def test_fallback_resolves_actual_id_for_approval_and_rejection(assets_db):
    first=assets_db.request('درخواست قدیمی')
    second=assets_db.request('درخواست قدیمی')
    with assets_db.connection() as conn:
        result=service.approve(conn,101,9999,details(assets_db,first)[0])
        assert result.outcome=='approved' and result.request.id==first
        result=service.inspect_decision(conn,101,9999,'reject',details(assets_db,second)[0])
        assert result.outcome=='ready' and result.request.id==second
        assert service.reject(conn,101,result.request.id,' دلیل ').outcome=='rejected'
    assert details(assets_db,second)[1]=='دلیل'


def test_fallback_cannot_approve_specialized_request(assets_db):
    rid=assets_db.request('مساعده')
    with assets_db.connection() as conn:
        assert service.approve(conn,101,9999,details(assets_db,rid)[0]).outcome=='invalid_type'
        assert service.approve(conn,101,9998,'missing').outcome=='not_found'
    assert 'در انتظار' in assets_db.status(rid)


def test_pending_replacement_blocks_shared_approval(assets_db):
    rid=assets_db.request('درخواست قدیمی')
    with assets_db.connection() as conn:
        conn.execute('INSERT INTO request_replacements VALUES(?,?,?)',(rid,3,'pending'))
    with assets_db.connection() as conn:
        assert service.approve(conn,101,rid).outcome=='replacement_pending'
        conn.execute("UPDATE request_replacements SET response='approved' WHERE request_id=?",(rid,))
    with assets_db.connection() as conn:
        assert service.approve(conn,101,rid).outcome=='approved'


def test_cancel_checks_owner_activity_and_preserves_other_data(assets_db):
    asset=assets_db.assign()
    rid=assets_db.request('مساعده')
    code=details(assets_db,rid)[0]
    with assets_db.connection() as conn:
        assert service.cancel(conn,303,code).outcome=='cannot_cancel'
        conn.execute('UPDATE staff_mapping SET is_active=0 WHERE telegram_user_id=202')
    with assets_db.connection() as conn,pytest.raises(service.PersonnelError):
        service.cancel(conn,202,code)
    with assets_db.connection() as conn:
        conn.execute('UPDATE staff_mapping SET is_active=1 WHERE telegram_user_id=202')
    with assets_db.connection() as conn:
        assert service.cancel(conn,202,code).outcome=='cancelled'
        assert service.cancel(conn,202,code).outcome=='cannot_cancel'
        assert conn.execute('SELECT is_active FROM user_assets WHERE id=?',(asset,)).fetchone()[0]==1
        assert conn.execute('SELECT leave_balance FROM staff_mapping WHERE staff_id=2').fetchone()[0]==5


def test_service_rejects_leave_even_with_forged_rejection_state(assets_db):
    with assets_db.connection() as conn:
        rid=conn.execute("INSERT INTO requests(telegram_user_id,req_code,request_type,status) VALUES(202,'leave-code','مرخصی','در انتظار')").lastrowid
    with assets_db.connection() as conn:
        assert service.reject(conn,101,rid,'reason').outcome=='invalid_type'
        assert service.cancel(conn,202,'leave-code').outcome=='invalid_type'


@pytest.mark.parametrize('number',[None,True,-1,2**63,'1'])
def test_invalid_request_ids_are_rejected(assets_db,number):
    with assets_db.connection() as conn,pytest.raises(service.DecisionError):
        service.approve(conn,101,number)


@pytest.mark.parametrize('action',['approve','reject','cancel'])
def test_storage_error_rolls_back_decision(assets_db,action):
    rid=assets_db.request('درخواست قدیمی')
    code=details(assets_db,rid)[0]
    with assets_db.connection() as conn:
        conn.execute("CREATE TRIGGER fail_decision BEFORE UPDATE OF status ON requests BEGIN SELECT RAISE(ABORT,'simulated failure'); END")
    with assets_db.connection() as conn,pytest.raises(sqlite3.IntegrityError):
        if action=='approve': service.approve(conn,101,rid)
        elif action=='reject': service.reject(conn,101,rid,'reason')
        else: service.cancel(conn,202,code)
    assert 'در انتظار' in assets_db.status(rid)
    assert details(assets_db,rid)[1] is None


def test_concurrent_owner_cancel_and_approval_commit_only_one(assets_db):
    rid=assets_db.request('درخواست قدیمی')
    code=details(assets_db,rid)[0]
    barrier=Barrier(2)
    def run(action):
        barrier.wait(timeout=10)
        with assets_db.connection() as conn:
            return (service.approve(conn,101,rid) if action=='approve' else service.cancel(conn,202,code)).outcome
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes=list(pool.map(run,['approve','cancel']))
    assert sum(value in ('approved','cancelled') for value in outcomes)==1
    assert 'در انتظار' not in assets_db.status(rid)


@pytest.mark.parametrize('reason',[None,'','   '])
def test_blank_rejection_reason_keeps_request_pending(assets_db,reason):
    rid=assets_db.request('درخواست قدیمی')
    with assets_db.connection() as conn,pytest.raises(service.DecisionError):
        service.reject(conn,101,rid,reason)
    assert 'در انتظار' in assets_db.status(rid)


def test_notification_failures_do_not_undo_or_repeat_committed_approval(assets_db):
    rid=assets_db.request('درخواست قدیمی')
    opened=0
    @contextmanager
    def connection():
        nonlocal opened
        with assets_db.connection() as conn:
            opened+=1
            try: yield conn
            finally: opened-=1
    async def fail(**kwargs):
        assert opened==0 and 'تأیید شده قطعی' in assets_db.status(rid)
        raise RuntimeError('Telegram unavailable')
    bot=SimpleNamespace(send_message=AsyncMock(side_effect=fail))
    router=create_router(connection,bot)
    handler=next(h.callback for h in router.callback_query.handlers if h.callback.__name__=='handle_request_decision')
    callback=SimpleNamespace(data=f'approve_{rid}',from_user=SimpleNamespace(id=101),answer=AsyncMock(),
        message=SimpleNamespace(text='Request',caption=None,photo=True,edit_caption=AsyncMock(side_effect=fail)))
    state=SimpleNamespace()
    asyncio.run(handler(callback,state))
    assert 'تأیید شده قطعی' in assets_db.status(rid)
    asyncio.run(handler(callback,state))
    bot.send_message.assert_awaited_once()
    assert callback.answer.await_args.kwargs['show_alert']
