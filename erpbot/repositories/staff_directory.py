"""Read-only staff directory queries. The caller owns the connection.

These queries do not authorize the caller. Authorization belongs to the
application service; handlers must not use these queries to bypass it.
"""
from .organization_units import active_unit_name


def active_staff_id_for_telegram(conn, telegram_user_id):
    row = conn.execute(
        "SELECT staff_id FROM staff_mapping WHERE telegram_user_id=? AND is_active=1",
        (telegram_user_id,),
    ).fetchone()
    return row[0] if row is not None else None


def active_units_for_staff(conn, staff_id):
    return conn.execute(
        "SELECT u.unit_id,u.unit_name FROM org_units u "
        "JOIN staff_unit_memberships m ON m.unit_id=u.unit_id "
        "WHERE m.staff_id=? AND m.is_active=1 AND u.is_active=1 "
        "ORDER BY u.unit_name,u.unit_id",
        (staff_id,),
    ).fetchall()


def active_members_of_unit(conn, unit_id):
    return conn.execute(
        "SELECT s.staff_id,s.staff_name FROM staff_unit_memberships m "
        "JOIN staff_mapping s ON s.staff_id=m.staff_id "
        "WHERE m.unit_id=? AND m.is_active=1 AND s.is_active=1 "
        "ORDER BY s.staff_name,s.staff_id",
        (unit_id,),
    ).fetchall()
