"""Organization-unit rules and authorized use cases; caller owns transactions.

The *_for_admin use cases recheck the actor on every invocation. The original
domain helpers remain compatible for existing callers supplying authorization.
"""
import re
import uuid
from erpbot.repositories import organization_units as repository


class OrganizationUnitError(ValueError):
    pass


class OrganizationUnitPermissionError(OrganizationUnitError):
    pass


def can_manage_units(conn, telegram_user_id):
    return repository.main_admin_staff_id(conn, telegram_user_id) is not None


def _require_admin(conn, telegram_user_id):
    actor_staff_id = repository.main_admin_staff_id(conn, telegram_user_id)
    if actor_staff_id is None:
        raise OrganizationUnitPermissionError("دسترسی مدیر اصلی احراز نشد.")
    return actor_staff_id


def active_units_for_admin(conn, telegram_user_id):
    _require_admin(conn, telegram_user_id)
    return active_units(conn)


def chart_for_admin(conn, telegram_user_id):
    _require_admin(conn, telegram_user_id)
    return render_org_chart(conn)


def parent_name_for_admin(conn, telegram_user_id, unit_id):
    _require_admin(conn, telegram_user_id)
    return repository.active_unit_name(conn, unit_id)


def create_unit_for_admin(conn, telegram_user_id, name, parent_unit_id=None):
    actor_staff_id = _require_admin(conn, telegram_user_id)
    return create_unit(conn, name, parent_unit_id, actor_staff_id=actor_staff_id)


def create_unit(conn, name, parent_unit_id=None, *, unit_code=None, actor_staff_id=None):
    if not isinstance(name, str) or not (1 <= len(name.strip()) <= 80):
        raise OrganizationUnitError('نام واحد باید بین ۱ تا ۸۰ نویسه باشد.')
    name = ' '.join(name.split())
    if any(ord(c) < 32 for c in name):
        raise OrganizationUnitError('نام واحد حاوی نویسه غیرمجاز است.')
    if parent_unit_id is not None:
        if not isinstance(parent_unit_id, int) or isinstance(parent_unit_id, bool) or parent_unit_id < 1:
            raise OrganizationUnitError('شناسه واحد بالادستی نامعتبر است.')
        if repository.unit_status(conn, parent_unit_id) != 1:
            raise OrganizationUnitError('واحد بالادستی معتبر یا فعال نیست.')
    if repository.sibling_exists(conn, name, parent_unit_id):
        raise OrganizationUnitError('واحدی با همین نام در این سطح وجود دارد.')
    if unit_code is None:
        unit_code = 'unit_' + uuid.uuid4().hex[:16]
    if not isinstance(unit_code, str) or not re.fullmatch(r'[a-z][a-z0-9_]{1,39}', unit_code):
        raise OrganizationUnitError('کد واحد نامعتبر است.')
    unit_id = repository.insert_unit(conn, unit_code, name, parent_unit_id)
    repository.record_creation(conn, actor_staff_id, unit_id, unit_code, parent_unit_id)
    return unit_id


def active_units(conn):
    return repository.active_units(conn)


def render_org_chart(conn):
    rows = active_units(conn)
    if not rows:
        return 'هنوز هیچ واحد سازمانی تعریف نشده است.'
    children = {}
    ids = {r[0] for r in rows}
    for unit_id, name, parent_id in rows:
        effective_parent = parent_id if parent_id in ids else None
        children.setdefault(effective_parent, []).append((unit_id, name))
    lines = []
    visited = set()

    def walk(parent_id, depth):
        for unit_id, name in children.get(parent_id, []):
            if unit_id in visited:
                continue
            visited.add(unit_id)
            lines.append('　' * depth + ('↳ ' if depth else '• ') + name)
            walk(unit_id, depth + 1)

    walk(None, 0)
    # Defensive fallback for any corrupted graph; do not recurse infinitely.
    for unit_id, name, _ in rows:
        if unit_id not in visited:
            lines.append('• ' + name + ' (نیازمند بررسی ساختار)')
    return '\n'.join(lines)
