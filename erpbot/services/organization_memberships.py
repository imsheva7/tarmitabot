"""Multi-unit staff membership operations. Caller owns authorization and transaction.

No legacy staff_mapping.role changes and no permissions conferred by membership.
"""

from erpbot.repositories.staff_directory import (
    active_members_of_unit as _active_members_of_unit,
    active_units_for_staff as _active_units_for_staff,
)
from erpbot.repositories import organization_memberships as repository
from erpbot.repositories import organization_units as unit_repository
from erpbot.repositories import staff_directory
from erpbot.repositories.audit import record as _record_audit
from erpbot.services.organization_admin import require_admin

class MembershipError(ValueError):
    pass


def _positive_id(value):
    return type(value) is int and value > 0


def _audit(conn, actor_staff_id, action, staff_id, unit_id):
    _record_audit(conn, actor_staff_id, action, "staff_unit_membership",
                  f"{staff_id}:{unit_id}", f"staff_id={staff_id};unit_id={unit_id}")


def add_membership(conn, staff_id, unit_id, *, actor_staff_id):
    if not all(_positive_id(v) for v in (staff_id, unit_id, actor_staff_id)):
        raise MembershipError("شناسه نامعتبر است.")
    actor = repository.staff_role_status(conn, actor_staff_id)
    if actor is None or actor[0] != "main_admin" or actor[1] != 1:
        raise MembershipError("فقط مدیر اصلی فعال مجاز است.")
    if repository.staff_status(conn, staff_id) != 1:
        raise MembershipError("پرسنل فعال پیدا نشد.")
    if unit_repository.unit_status(conn, unit_id) != 1:
        raise MembershipError("واحد فعال پیدا نشد.")
    existing = repository.membership_status(conn, staff_id, unit_id)
    if existing == 1:
        raise MembershipError("پرسنل قبلاً عضو این واحد است.")
    if existing is not None:
        repository.restore_membership(conn, staff_id, unit_id)
    else:
        repository.insert_membership(conn, staff_id, unit_id)
    _audit(conn, actor_staff_id, "organization.membership.add", staff_id, unit_id)


def deactivate_membership(conn, staff_id, unit_id, *, actor_staff_id):
    if not all(_positive_id(v) for v in (staff_id, unit_id, actor_staff_id)):
        raise MembershipError("شناسه نامعتبر است.")
    actor = repository.staff_role_status(conn, actor_staff_id)
    if actor is None or actor[0] != "main_admin" or actor[1] != 1:
        raise MembershipError("فقط مدیر اصلی فعال مجاز است.")
    if repository.deactivate_membership(conn, staff_id, unit_id) != 1:
        raise MembershipError("عضویت فعال پیدا نشد.")
    # Important: removing membership also disables scoped roles; rejoining never restores them.
    repository.disable_unit_roles(conn, staff_id, unit_id)
    _audit(conn, actor_staff_id, "organization.membership.deactivate", staff_id, unit_id)


def active_memberships_for_staff(conn, staff_id):
    return _active_units_for_staff(conn, staff_id)


def active_members_of_unit(conn, unit_id):
    return _active_members_of_unit(conn, unit_id)


def staff_for_admin(conn, telegram_id):
    require_admin(conn, telegram_id)
    return repository.active_staff(conn)


def person_for_admin(conn, telegram_id, staff_id):
    require_admin(conn, telegram_id)
    return repository.staff_name(conn, staff_id)


def staff_exists_for_admin(conn, telegram_id, staff_id):
    require_admin(conn, telegram_id)
    return repository.staff_status(conn, staff_id) == 1


def units_for_admin(conn, telegram_id):
    require_admin(conn, telegram_id)
    return unit_repository.active_units(conn)


def removal_person_for_admin(conn, telegram_id, staff_id):
    require_admin(conn, telegram_id)
    return repository.staff_name(conn, staff_id, active_only=False)


def removal_unit_for_admin(conn, telegram_id, unit_id):
    require_admin(conn, telegram_id)
    return repository.unit_name(conn, unit_id)


def removal_membership_for_admin(conn, telegram_id, staff_id, unit_id):
    require_admin(conn, telegram_id)
    return repository.membership_status(conn, staff_id, unit_id) == 1


def active_unit_for_admin(conn, telegram_id, unit_id):
    require_admin(conn, telegram_id)
    name = unit_repository.active_unit_name(conn, unit_id)
    return (name,) if name is not None else None


def memberships_for_user(conn, telegram_id):
    staff_id = staff_directory.active_staff_id_for_telegram(conn, telegram_id)
    return active_memberships_for_staff(conn, staff_id) if staff_id is not None else None
