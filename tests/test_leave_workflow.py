"""Authorization, idempotency, rollback and competing leave decisions on SQLite."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import sqlite3
import pytest
from erpbot.services import leave_workflow as workflow
from erpbot.services.requests import RequestSubmissionError


def test_replacement_and_approval_are_bound_to_active_assigned_staff(leave_db):
    rid, _ = leave_db.request(replacement=3)
    for actor in (101,202,404,505,999):
        with leave_db.connection() as conn:
            assert workflow.respond_replacement(conn,rid,actor,True).outcome == "forbidden"
    with leave_db.connection() as conn:
        assert workflow.approve_leave(conn,rid,101).outcome == "replacement_pending"
        assert workflow.respond_replacement(conn,rid,303,True).outcome == "approved"
        assert workflow.respond_replacement(conn,rid,303,False).outcome == "already_answered"
        assert workflow.approve_leave(conn,rid,101).outcome == "approved"
        assert workflow.approve_leave(conn,rid,101).outcome == "already_processed"
    assert leave_db.effects() == (2,1,1)


@pytest.mark.parametrize("actor", [202,303,404,505,999])
def test_approval_and_rejection_require_current_main_admin(leave_db, actor):
    rid,_ = leave_db.request()
    with leave_db.connection() as conn:
        assert workflow.approve_leave(conn,rid,actor,exceptional=True).outcome == "forbidden"
        assert workflow.reject_leave(conn,rid,actor,"دلیل").outcome == "forbidden"
    assert leave_db.effects() == (5,0,0)
    assert "در انتظار" in leave_db.row(rid)["status"]


def test_replacement_rejection_blocks_all_later_decisions(leave_db):
    rid,code = leave_db.request(replacement=3)
    with leave_db.connection() as conn:
        result = workflow.respond_replacement(conn,rid,303,False)
        assert result.outcome == "rejected" and "جانشین <الف>" in result.details
        assert workflow.approve_leave(conn,rid,101,exceptional=True).outcome == "already_processed"
        assert workflow.reject_leave(conn,rid,101,"دلیل").outcome == "already_processed"
        assert workflow.cancel_leave(conn,code,202).outcome == "forbidden"
    assert leave_db.effects() == (5,0,0)


def test_replacement_activity_is_rechecked_on_old_button(leave_db):
    rid,_ = leave_db.request(replacement=3)
    with leave_db.connection() as conn:
        conn.execute("UPDATE staff_mapping SET is_active=0 WHERE staff_id=3")
    with leave_db.connection() as conn:
        assert workflow.respond_replacement(conn,rid,303,True).outcome == "forbidden"
        assert workflow.approve_leave(conn,rid,101).outcome == "replacement_pending"
    assert leave_db.effects() == (5,0,0)


def test_leave_services_do_not_mutate_other_request_types(leave_db):
    rid,code = leave_db.request(kind="ماموریت")
    with leave_db.connection() as conn:
        assert workflow.approve_leave(conn,rid,101).outcome == "not_annual_leave"
        assert workflow.reject_leave(conn,rid,101,"دلیل").outcome == "not_found"
        assert workflow.respond_replacement(conn,rid,303,True).outcome == "not_found"
        assert workflow.cancel_leave(conn,code,202).outcome == "forbidden"
    assert "در انتظار" in leave_db.row(rid)["status"]
    assert leave_db.effects() == (5,0,0)


@pytest.mark.parametrize("col1", ["نوع: استعلاجی", "نوع: ساعتی", "نوع: بدون حقوق"])
def test_nonannual_leave_never_changes_balance_or_ledger(leave_db,col1):
    rid,_ = leave_db.request(col1=col1,replacement=3)
    with leave_db.connection() as conn:
        assert workflow.approve_leave(conn,rid,101).outcome == "replacement_pending"
        workflow.respond_replacement(conn,rid,303,True)
        assert workflow.approve_leave(conn,rid,101,exceptional=True).outcome == "not_annual_leave"
        assert workflow.approve_leave(conn,rid,101).outcome == "approved"
    assert leave_db.effects() == (5,0,0)


def test_shortage_only_debits_on_explicit_exceptional_approval(leave_db):
    rid,_ = leave_db.request(days="7")
    with leave_db.connection() as conn:
        assert workflow.approve_leave(conn,rid,101).outcome == "needs_override"
    assert leave_db.effects() == (5,0,0)
    with leave_db.connection() as conn:
        assert workflow.approve_leave(conn,rid,101,exceptional=True).outcome == "exceptional_approved"
    assert leave_db.effects() == (-2,1,1)


@pytest.mark.parametrize("mutation", ["reject", "cancel"])
def test_completed_requests_cannot_be_debited_or_changed(leave_db,mutation):
    rid,code = leave_db.request()
    with leave_db.connection() as conn:
        if mutation == "reject":
            assert workflow.reject_leave(conn,rid,101," علت ").outcome == "rejected"
        else:
            assert workflow.cancel_leave(conn,code,101).outcome == "forbidden"
            assert workflow.cancel_leave(conn,code,202).outcome == "cancelled"
        assert workflow.approve_leave(conn,rid,101,exceptional=True).outcome == "already_processed"
    assert leave_db.effects() == (5,0,0)


def test_blank_rejection_and_wrong_owner_do_not_mutate(leave_db):
    rid,code = leave_db.request()
    with leave_db.connection() as conn:
        assert workflow.reject_leave(conn,rid,101,"  ").outcome == "invalid_reason"
        assert workflow.cancel_leave(conn,code,303).outcome == "forbidden"
    assert "در انتظار" in leave_db.row(rid)["status"]


def test_replacement_rollback_keeps_response_and_request_consistent(leave_db):
    rid,_ = leave_db.request(replacement=3)
    with leave_db.connection() as conn:
        conn.execute("CREATE TRIGGER fail_status BEFORE UPDATE ON requests BEGIN SELECT RAISE(ABORT,'test failure'); END")
    with leave_db.connection() as conn:
        with pytest.raises(sqlite3.IntegrityError,match="test failure"):
            workflow.respond_replacement(conn,rid,303,False)
        assert not conn.in_transaction
        assert conn.execute("SELECT response FROM request_replacements").fetchone()[0] is None
    assert "در انتظار" in leave_db.row(rid)["status"]


@pytest.mark.parametrize("table", ["leave_ledger", "staff_mapping", "requests"])
def test_debit_failure_rolls_back_entire_effect(leave_db,table):
    rid,_ = leave_db.request()
    action = "INSERT" if table == "leave_ledger" else "UPDATE"
    with leave_db.connection() as conn:
        conn.execute(f"CREATE TRIGGER fail_debit BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'debit failure'); END")
    with leave_db.connection() as conn:
        with pytest.raises(sqlite3.IntegrityError,match="debit failure"):
            workflow.approve_leave(conn,rid,101)
        assert not conn.in_transaction
    assert leave_db.effects() == (5,0,0)
    assert "در انتظار" in leave_db.row(rid)["status"]


def test_workflow_does_not_rollback_callers_open_transaction(leave_db):
    rid,_ = leave_db.request()
    with leave_db.connection() as conn:
        conn.execute("UPDATE staff_mapping SET staff_name='caller change' WHERE staff_id=2")
        with pytest.raises(RuntimeError,match="active transaction"):
            workflow.approve_leave(conn,rid,101)
        assert conn.in_transaction
        assert conn.execute("SELECT staff_name FROM staff_mapping WHERE staff_id=2").fetchone()[0] == "caller change"


@pytest.mark.parametrize("other", ["approve", "cancel", "reject"])
def test_competing_connections_only_commit_one_terminal_decision(leave_db,other):
    rid,code = leave_db.request()
    barrier = Barrier(2)
    def decide(action):
        with leave_db.connection() as conn:
            barrier.wait(timeout=10)
            if action == "approve":
                return workflow.approve_leave(conn,rid,101).outcome
            if action == "cancel":
                return workflow.cancel_leave(conn,code,202).outcome
            return workflow.reject_leave(conn,rid,101,"دلیل").outcome
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(decide,"approve")
        second = pool.submit(decide,other)
        outcomes = [first.result(timeout=15),second.result(timeout=15)]
    assert sum(value in ("approved","cancelled","rejected") for value in outcomes) == 1
    assert leave_db.effects() == ((2,1,1) if "approved" in outcomes else (5,0,0))


@pytest.mark.parametrize("replacement", [2,5,6,999])
def test_invalid_replacement_cannot_be_persisted(leave_db,replacement):
    with pytest.raises(RequestSubmissionError):
        leave_db.request(replacement=replacement)
    with leave_db.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM requests").fetchone()[0] == 0


def test_submission_rechecks_employee_activity(leave_db):
    with leave_db.connection() as conn:
        conn.execute("UPDATE staff_mapping SET is_active=0 WHERE staff_id=2")
    with pytest.raises(RequestSubmissionError):
        leave_db.request()


def test_calendar_preserves_friday_holidays_and_minimum_one_day():
    # 1405/07/24 is Friday, 25 is Saturday.
    assert workflow.working_days("1405/07/24","1405/07/25",[]) == 1
    assert workflow.working_days("1405/07/25","1405/07/26",["1405/07/25"]) == 1
    assert workflow.working_days("1405/07/24","1405/07/24",[]) == 1
    with pytest.raises(workflow.LeaveError):
        workflow.working_days("1405/07/25","1405/07/24",[])
