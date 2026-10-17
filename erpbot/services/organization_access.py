"""Phase 5A: read-only, fail-closed unit-scoped permission checks.

This module intentionally does not modify legacy approval handlers. A caller
must supply the target unit from trusted server-side request data, never from
an untrusted callback alone. No implicit main_admin bypass is applied.
"""


def _positive_int(value):
    return type(value) is int and value > 0


def has_unit_permission(conn, staff_id, unit_id, permission_code):
    """True only for active staff + unit + membership + role + permission.

    An active legacy main_admin is NOT automatically authorized here: legacy
    global privileges are managed separately until explicitly integrated.
    """
    if not (_positive_int(staff_id) and _positive_int(unit_id)):
        return False
    if not isinstance(permission_code, str) or not permission_code.strip():
        return False
    try:
        return conn.execute(
            """SELECT 1
               FROM staff_mapping AS s
               JOIN staff_unit_memberships AS m
                 ON m.staff_id=s.staff_id AND m.unit_id=? AND m.is_active=1
               JOIN org_units AS u ON u.unit_id=m.unit_id AND u.is_active=1
               JOIN staff_role_assignments AS a
                 ON a.staff_id=s.staff_id AND a.unit_id=m.unit_id AND a.is_active=1
               JOIN roles AS r ON r.role_id=a.role_id AND r.is_active=1
               JOIN role_permissions AS rp ON rp.role_id=r.role_id
               JOIN permissions AS p
                 ON p.permission_id=rp.permission_id AND p.is_active=1
               WHERE s.staff_id=? AND s.is_active=1 AND p.permission_code=?
               LIMIT 1""",
            (unit_id, staff_id, permission_code),
        ).fetchone() is not None
    except Exception as exc:
        # Missing schema and SQLite errors must never result in access granted.
        import sqlite3
        if isinstance(exc, sqlite3.Error):
            return False
        raise


def require_unit_permission(conn, staff_id, unit_id, permission_code):
    """Raise PermissionError unless has_unit_permission is True."""
    if not has_unit_permission(conn, staff_id, unit_id, permission_code):
        raise PermissionError('مجوز دسترسی به این واحد وجود ندارد.')
