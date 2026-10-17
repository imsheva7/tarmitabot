from dataclasses import dataclass
import math


@dataclass(frozen=True)
class LeaveDecision:
    allowed: bool
    requires_override: bool
    remaining_balance: float
    reason: str


def evaluate_leave(balance, requested_days, override=False):
    """Evaluate an annual leave request without changing the database."""

    balance = float(balance)
    requested_days = float(requested_days)

    if not math.isfinite(balance) or not math.isfinite(requested_days):
        raise ValueError("Leave values must be finite numbers")

    if requested_days <= 0:
        raise ValueError("Requested leave must be greater than zero")

    remaining = balance - requested_days

    if remaining >= 0:
        return LeaveDecision(
            allowed=True,
            requires_override=False,
            remaining_balance=remaining,
            reason="normal_approval"
        )

    if override:
        return LeaveDecision(
            allowed=True,
            requires_override=False,
            remaining_balance=remaining,
            reason="exceptional_approval"
        )

    return LeaveDecision(
        allowed=False,
        requires_override=True,
        remaining_balance=remaining,
        reason="insufficient_balance"
    )
