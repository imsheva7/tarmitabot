"""Authorized leave use cases and calendar calculations, independent of Telegram."""
from dataclasses import dataclass
import jdatetime
from ..core.database import transaction
from ..repositories import leave as repository
from .leave_approval import approve_annual_leave, LeaveApprovalResult


class LeaveError(ValueError):
    pass


@dataclass(frozen=True)
class LeaveResult:
    outcome: str
    row: tuple | None = None
    details: str | None = None
    status_tag: str | None = None


def is_main_admin(conn, telegram_id):
    return repository.main_admin_staff_id(conn, telegram_id) is not None


def active_staff(conn, telegram_id):
    row = repository.active_staff(conn, telegram_id)
    if row is None:
        raise LeaveError("حساب پرسنلی فعال یافت نشد.")
    return row


def is_leave_request(conn, request_id):
    return repository.request_kind(conn, request_id) == "مرخصی"


def is_leave_code(conn, code):
    return repository.request_kind_by_code(conn, code) == "مرخصی"


def approval_request(conn, request_id):
    return repository.approval_request(conn, request_id)


def approve_leave(conn, request_id, actor_id, *, exceptional=False):
    row = repository.approval_request(conn, request_id)
    if row and row[2] == "مرخصی" and "استحقاقی" in (row[3] or ""):
        return approve_annual_leave(conn, request_id, exceptional=exceptional, actor_telegram_id=actor_id)
    with transaction(conn):
        if not is_main_admin(conn, actor_id):
            return LeaveApprovalResult("forbidden")
        row = repository.notification_request(conn, request_id)
        if row is None:
            return LeaveApprovalResult("not_found")
        if row[5] != "مرخصی" or exceptional:
            return LeaveApprovalResult("not_annual_leave")
        current = repository.approval_request(conn, request_id)
        if "استحقاقی" in (current[3] or ""):
            # A changed type must never enter the approval path without a debit.
            return LeaveApprovalResult("not_annual_leave")
        if "در انتظار" not in (row[4] or ""):
            return LeaveApprovalResult("already_processed")
        replacement = repository.replacement_response(conn, request_id)
        if replacement and replacement[0] != "approved":
            return LeaveApprovalResult("replacement_pending")
        if repository.approve_pending(conn, request_id) != 1:
            raise RuntimeError("Request status changed unexpectedly")
        return LeaveApprovalResult("approved")


def rejection_request(conn, request_id, actor_id):
    if not is_main_admin(conn, actor_id):
        return LeaveResult("forbidden")
    row = repository.notification_request(conn, request_id)
    if row is None or row[5] != "مرخصی":
        return LeaveResult("not_found")
    return LeaveResult("pending" if "در انتظار" in (row[4] or "") else "already_processed", tuple(row))


def reject_leave(conn, request_id, actor_id, reason):
    with transaction(conn):
        result = rejection_request(conn, request_id, actor_id)
        if result.outcome != "pending":
            return result
        if not isinstance(reason, str) or not reason.strip():
            return LeaveResult("invalid_reason")
        if repository.reject_pending(conn, request_id, reason.strip()) != 1:
            raise RuntimeError("Request status changed unexpectedly")
        return LeaveResult("rejected", result.row)


def cancel_leave(conn, code, actor_id):
    with transaction(conn):
        row = repository.cancellation_request(conn, code)
        if (repository.active_staff(conn, actor_id) is None or row is None or row[1] != actor_id
                or row[5] != "مرخصی" or "در انتظار" not in (row[2] or "")):
            return LeaveResult("forbidden")
        if repository.cancel_pending(conn, row[0], actor_id) != 1:
            raise RuntimeError("Request status changed unexpectedly")
        return LeaveResult("cancelled", tuple(row))


def respond_replacement(conn, request_id, actor_id, approved):
    with transaction(conn):
        row = repository.request_for_replacement(conn, request_id)
        if row is None or not is_leave_request(conn, request_id):
            return LeaveResult("not_found")
        if "در انتظار" not in (row[7] or ""):
            return LeaveResult("already_processed")
        assignment = repository.replacement_assignment(conn, request_id)
        actor = repository.active_staff(conn, actor_id)
        if not assignment or not actor or assignment[0] != actor[0]:
            return LeaveResult("forbidden")
        if assignment[1] is not None:
            return LeaveResult("already_answered")
        if repository.set_replacement_response(conn, request_id, "approved" if approved else "rejected") != 1:
            raise RuntimeError("Replacement response changed unexpectedly")
        tag = (f"تأیید شده توسط جانشین ({actor[1]}) ✅" if approved
               else f"رد شده توسط جانشین ({actor[1]}) ❌")
        base = (row[4] or "").split("| وضعیت جانشین:")[0]
        details = f"{base} | وضعیت جانشین: {tag}"
        if repository.update_replacement_status(conn, request_id, details, approved) != 1:
            raise RuntimeError("Request status changed unexpectedly")
        return LeaveResult("approved" if approved else "rejected", tuple(row), details, tag)


def working_days(start, end, holidays):
    first = jdatetime.date(*map(int, start.split('/')))
    last = jdatetime.date(*map(int, end.split('/')))
    if last < first:
        raise LeaveError("تاریخ پایان نمی‌تواند قبل از تاریخ شروع باشد.")
    days, current = 0, first
    while current <= last:
        if current.weekday() != 6 and current.strftime("%Y/%m/%d") not in holidays:
            days += 1
        current += jdatetime.timedelta(days=1)
    return float(days) if days else 1.0


def pending_days(conn, telegram_id):
    return repository.pending_days(conn, telegram_id)


def holidays(conn):
    return repository.holidays(conn)


def replacement_candidates(conn, telegram_id):
    active_staff(conn, telegram_id)
    return repository.replacement_candidates(conn, telegram_id)


def replacement_name(conn, staff_id, telegram_id):
    active_staff(conn, telegram_id)
    row = repository.replacement_staff(conn, staff_id)
    if row is None or row[1] == telegram_id or row[1] is None:
        raise LeaveError("جانشین فعال و متصل پیدا نشد.")
    return row[0]
