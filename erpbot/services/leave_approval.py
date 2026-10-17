"""Atomic, idempotent annual leave approval, independent of Telegram."""
import math
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo
from ..core.database import transaction
from ..repositories import leave as repository
from .leave_service import evaluate_leave


@dataclass(frozen=True)
class LeaveApprovalResult:
    outcome: str
    balance: float | None = None


def approve_annual_leave(conn, request_id: int, *, exceptional: bool = False,
                         actor_telegram_id: int | None = None):
    """Own a fresh transaction for debit, ledger and status.

    Application callers provide actor_telegram_id, checked inside the lock.
    Legacy callers omitting it retain responsibility for authorization and
    separate confirmation before exceptional=True.
    """
    with transaction(conn):
        if actor_telegram_id is not None and repository.main_admin_staff_id(conn, actor_telegram_id) is None:
            return LeaveApprovalResult("forbidden")
        row = repository.annual_request(conn, request_id)
        if row is None:
            return LeaveApprovalResult("not_found")
        telegram_id, staff_name, req_code, request_type, col1, location, status, staff_id, balance = row
        if request_type != "مرخصی" or "استحقاقی" not in (col1 or ""):
            return LeaveApprovalResult("not_annual_leave")
        if "در انتظار" not in (status or ""):
            return LeaveApprovalResult("already_processed")
        replacement = repository.replacement_response(conn, request_id)
        if replacement and replacement[0] != "approved":
            return LeaveApprovalResult("replacement_pending")
        if staff_id is None or balance is None:
            return LeaveApprovalResult("staff_not_found")
        try:
            days = float(location)
            if not math.isfinite(days) or days <= 0:
                raise ValueError("Invalid leave days")
        except (TypeError, ValueError):
            return LeaveApprovalResult("invalid_days")
        decision = evaluate_leave(balance, days, override=exceptional)
        if not decision.allowed:
            return LeaveApprovalResult("needs_override", float(balance))
        if repository.mark_debit(conn, request_id) != 1:
            return LeaveApprovalResult("already_processed")
        timestamp = datetime.now(ZoneInfo("Asia/Tehran")).strftime("%Y/%m/%d %H:%M")
        approval_type = "استثنایی" if exceptional else "عادی"
        description = f"مرخصی استحقاقی {approval_type} تأیید شده ({req_code})"
        repository.record_debit(conn, staff_id, staff_name, days, description, timestamp)
        new_balance = float(decision.remaining_balance)
        if repository.set_balance(conn, staff_id, new_balance) != 1:
            raise RuntimeError("Staff balance update failed")
        if repository.approve_pending(conn, request_id) != 1:
            raise RuntimeError("Request status changed unexpectedly")
        return LeaveApprovalResult("exceptional_approved" if exceptional else "approved", new_balance)
