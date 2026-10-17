"""Organization unit persistence. The caller owns authorization and transaction."""
from .audit import record


def main_admin_staff_id(conn, telegram_user_id):
    row = conn.execute(
        "SELECT staff_id FROM staff_mapping "
        "WHERE telegram_user_id=? AND is_active=1 AND role='main_admin'",
        (telegram_user_id,),
    ).fetchone()
    return row[0] if row is not None else None


def unit_status(conn, unit_id):
    row = conn.execute("SELECT is_active FROM org_units WHERE unit_id=?", (unit_id,)).fetchone()
    return row[0] if row is not None else None


def active_unit_name(conn, unit_id):
    row = conn.execute("SELECT unit_name FROM org_units WHERE unit_id=? AND is_active=1",
                       (unit_id,)).fetchone()
    return row[0] if row is not None else None


def sibling_exists(conn, name, parent_unit_id):
    return conn.execute(
        "SELECT 1 FROM org_units WHERE unit_name=? AND "
        "((parent_unit_id IS NULL AND ? IS NULL) OR parent_unit_id=?)",
        (name, parent_unit_id, parent_unit_id),
    ).fetchone() is not None


def insert_unit(conn, code, name, parent_unit_id):
    cursor = conn.execute("INSERT INTO org_units(unit_code,unit_name,parent_unit_id) VALUES(?,?,?)",
                          (code, name, parent_unit_id))
    return cursor.lastrowid


def record_creation(conn, actor_staff_id, unit_id, unit_code, parent_unit_id):
    record(conn, actor_staff_id, "organization.unit.create", "org_unit", unit_id,
           f"unit_code={unit_code};parent={parent_unit_id}")


def active_units(conn):
    return conn.execute("SELECT unit_id,unit_name,parent_unit_id FROM org_units "
                        "WHERE is_active=1 ORDER BY unit_name,unit_id").fetchall()
