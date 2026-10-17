"""Scoped role and permission administration; legacy auth/approval paths are unchanged.

Caller owns transactions. This module checks main_admin again for EVERY mutation.
"""
import uuid
from erpbot.repositories import organization_roles as repository
from erpbot.repositories import organization_memberships as memberships
from erpbot.repositories import organization_units as units
from erpbot.repositories.audit import record as _record_audit
from erpbot.services.organization_admin import require_admin

class RoleError(ValueError):
    pass

def _id(v):
    return type(v) is int and v > 0

def _admin(conn, actor_staff_id):
    if not _id(actor_staff_id):
        raise RoleError("شناسه مدیر نامعتبر است.")
    row=memberships.staff_role_status(conn, actor_staff_id)
    if row is None or row[0] != 'main_admin' or row[1] != 1:
        raise RoleError("فقط مدیر اصلی فعال مجاز است.")

def _audit(conn, actor, action, entity, entity_id, details=''):
    _record_audit(conn, actor, action, entity, entity_id, details)

def list_roles(conn):
    return repository.list_roles(conn)

def list_permissions(conn):
    return repository.list_permissions(conn)

def create_role(conn,name,*,actor_staff_id):
    _admin(conn,actor_staff_id)
    if not isinstance(name,str) or not 2 <= len(name.strip()) <= 70:
        raise RoleError("نام نقش باید ۲ تا ۷۰ نویسه باشد.")
    name=' '.join(name.split())
    if any(ord(ch)<32 for ch in name):
        raise RoleError("نام نقش نامعتبر است.")
    if repository.name_exists(conn, name):
        raise RoleError("این نقش قبلاً ثبت شده است.")
    code='custom_'+uuid.uuid4().hex[:20]
    role_id = repository.insert_role(conn, code, name)
    _audit(conn,actor_staff_id,'organization.role.create','role',role_id,code)
    return role_id

def _custom_role(conn,role_id):
    if not _id(role_id): raise RoleError("شناسه نقش نامعتبر است.")
    row=repository.role_flags(conn, role_id)
    if row is None:raise RoleError("نقش پیدا نشد.")
    if row[0] or row[1]:raise RoleError("نقش‌های سیستمی قابل تغییر نیستند.")
    return row

def set_role_permission(conn,role_id,permission_id,enabled,*,actor_staff_id):
    _admin(conn,actor_staff_id)
    role=_custom_role(conn,role_id)
    if role[2]!=1:raise RoleError("نقش غیرفعال است.")
    if not _id(permission_id) or type(enabled) is not bool:
        raise RoleError("مجوز نامعتبر است.")
    exists=repository.permission_active(conn, permission_id)
    if not exists:raise RoleError("مجوز فعال پیدا نشد.")
    if enabled:
        repository.enable_permission(conn, role_id, permission_id)
    else:
        repository.disable_permission(conn, role_id, permission_id)
    _audit(conn,actor_staff_id,'organization.role.permission.set','role',role_id,f'permission={permission_id};enabled={int(enabled)}')

def set_role_active(conn,role_id,enabled,*,actor_staff_id):
    _admin(conn,actor_staff_id)
    _custom_role(conn,role_id)
    if type(enabled) is not bool:raise RoleError("وضعیت نامعتبر است.")
    repository.set_active(conn, role_id, enabled)
    if not enabled:
        repository.disable_assignments(conn, role_id)
    _audit(conn,actor_staff_id,'organization.role.active.set','role',role_id,f'enabled={int(enabled)}')

def assign_role(conn,staff_id,unit_id,role_id,*,actor_staff_id):
    _admin(conn,actor_staff_id)
    role=_custom_role(conn,role_id)
    if role[2]!=1:raise RoleError("نقش غیرفعال است.")
    if not _id(staff_id) or not _id(unit_id):raise RoleError("شناسه نامعتبر است.")
    if memberships.staff_status(conn, staff_id) != 1 or units.unit_status(conn, unit_id) != 1 or memberships.membership_status(conn, staff_id, unit_id) != 1:
        raise RoleError("عضویت فعال فرد در این واحد الزامی است.")
    current=repository.assignment(conn, staff_id, unit_id, role_id)
    if current and current[1]==1:raise RoleError("این نقش قبلاً اختصاص یافته است.")
    if current:
        repository.restore_assignment(conn, current[0], actor_staff_id)
    else:
        repository.insert_assignment(conn, staff_id, unit_id, role_id, actor_staff_id)
    _audit(conn,actor_staff_id,'organization.role.assign','staff',staff_id,f'unit={unit_id};role={role_id}')

def revoke_role(conn,staff_id,unit_id,role_id,*,actor_staff_id):
    _admin(conn,actor_staff_id)
    _custom_role(conn,role_id)
    if not _id(staff_id) or not _id(unit_id):raise RoleError("شناسه نامعتبر است.")
    if repository.revoke_assignment(conn, staff_id, unit_id, role_id)!=1:raise RoleError("نقش فعالی یافت نشد.")
    _audit(conn,actor_staff_id,'organization.role.revoke','staff',staff_id,f'unit={unit_id};role={role_id}')

def staff_unit_roles(conn,staff_id,unit_id):
    return repository.staff_unit_roles(conn, staff_id, unit_id)


def roles_for_admin(conn, telegram_id):
    require_admin(conn, telegram_id)
    return list_roles(conn)


def permissions_for_admin(conn, telegram_id):
    require_admin(conn, telegram_id)
    return list_permissions(conn)


def role_for_admin(conn, telegram_id, role_id):
    require_admin(conn, telegram_id)
    return repository.role_details(conn, role_id)


def descriptions_for_admin(conn, telegram_id, role_id):
    require_admin(conn, telegram_id)
    return repository.permission_descriptions(conn, role_id)


def flags_for_admin(conn, telegram_id, role_id):
    require_admin(conn, telegram_id)
    return repository.role_flags(conn, role_id)


def owned_for_admin(conn, telegram_id, role_id):
    require_admin(conn, telegram_id)
    return repository.owned_permissions(conn, role_id)


def membership_for_admin(conn, telegram_id, staff_id, unit_id):
    require_admin(conn, telegram_id)
    return memberships.active_membership(conn, staff_id, unit_id)


def assignable_for_admin(conn, telegram_id):
    require_admin(conn, telegram_id)
    return repository.assignable_roles(conn)
