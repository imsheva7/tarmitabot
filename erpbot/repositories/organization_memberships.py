"""Staff and membership queries; no authorization, commits, or connection creation."""


def staff_role_status(conn, staff_id):
    return conn.execute("SELECT role,is_active FROM staff_mapping WHERE staff_id=?", (staff_id,)).fetchone()


def staff_status(conn, staff_id):
    row = conn.execute("SELECT is_active FROM staff_mapping WHERE staff_id=?", (staff_id,)).fetchone()
    return row[0] if row is not None else None


def staff_name(conn, staff_id, *, active_only=True):
    if active_only:
        return conn.execute("SELECT staff_name FROM staff_mapping WHERE staff_id=? AND is_active=1", (staff_id,)).fetchone()
    return conn.execute("SELECT staff_name FROM staff_mapping WHERE staff_id=?", (staff_id,)).fetchone()


def active_staff(conn):
    return conn.execute("SELECT staff_id,staff_name FROM staff_mapping WHERE is_active=1 ORDER BY staff_name,staff_id").fetchall()


def membership_status(conn, staff_id, unit_id):
    row = conn.execute("SELECT is_active FROM staff_unit_memberships WHERE staff_id=? AND unit_id=?", (staff_id, unit_id)).fetchone()
    return row[0] if row is not None else None


def active_membership(conn, staff_id, unit_id):
    return conn.execute(
        "SELECT 1 FROM staff_unit_memberships m JOIN staff_mapping s ON s.staff_id=m.staff_id "
        "JOIN org_units u ON u.unit_id=m.unit_id WHERE m.staff_id=? AND m.unit_id=? "
        "AND m.is_active=1 AND s.is_active=1 AND u.is_active=1", (staff_id, unit_id),
    ).fetchone() is not None


def unit_name(conn, unit_id):
    return conn.execute("SELECT unit_name FROM org_units WHERE unit_id=?", (unit_id,)).fetchone()


def insert_membership(conn, staff_id, unit_id):
    conn.execute("INSERT INTO staff_unit_memberships(staff_id,unit_id) VALUES(?,?)", (staff_id, unit_id))


def restore_membership(conn, staff_id, unit_id):
    conn.execute("UPDATE staff_unit_memberships SET is_active=1,joined_at=CURRENT_TIMESTAMP,left_at=NULL WHERE staff_id=? AND unit_id=?", (staff_id, unit_id))


def deactivate_membership(conn, staff_id, unit_id):
    return conn.execute("UPDATE staff_unit_memberships SET is_active=0,left_at=CURRENT_TIMESTAMP WHERE staff_id=? AND unit_id=? AND is_active=1", (staff_id, unit_id)).rowcount


def disable_unit_roles(conn, staff_id, unit_id):
    conn.execute("UPDATE staff_role_assignments SET is_active=0 WHERE staff_id=? AND unit_id=? AND is_active=1", (staff_id, unit_id))
