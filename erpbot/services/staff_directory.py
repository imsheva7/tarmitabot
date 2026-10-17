"""Unit-scoped directory use cases, independent of Telegram and runtime.

Every invocation rechecks current authorization. No cached menus or legacy
administrator role can grant implicit access. The caller owns the transaction.
"""
from dataclasses import dataclass
from typing import Literal

from ..repositories import staff_directory as repository
from .organization_access import has_unit_permission


@dataclass(frozen=True)
class UnitDirectoryResult:
    outcome: Literal["allowed", "denied", "unit_not_found"]
    unit_name: str | None = None
    member_names: tuple[str, ...] = ()


def visible_units_for_user(conn, telegram_user_id):
    """Return authorized (id, name) tuples, or None for an inactive/unknown user."""
    staff_id = repository.active_staff_id_for_telegram(conn, telegram_user_id)
    if staff_id is None:
        return None
    return tuple(
        (row[0], row[1])
        for row in repository.active_units_for_staff(conn, staff_id)
        if has_unit_permission(conn, staff_id, row[0], "staff.view_unit")
    )


def directory_for_user(conn, telegram_user_id, unit_id):
    """Read members only after authorizing the actual requesting user."""
    staff_id = repository.active_staff_id_for_telegram(conn, telegram_user_id)
    if staff_id is None or not has_unit_permission(conn, staff_id, unit_id, "staff.view_unit"):
        return UnitDirectoryResult("denied")
    name = repository.active_unit_name(conn, unit_id)
    if name is None:
        return UnitDirectoryResult("unit_not_found")
    members = repository.active_members_of_unit(conn, unit_id)
    return UnitDirectoryResult("allowed", name, tuple(str(row[1]) for row in members))
