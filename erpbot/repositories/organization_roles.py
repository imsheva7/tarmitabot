"""Scoped role persistence; the caller owns authorization and transactions."""


def list_roles(conn):
    return conn.execute("SELECT role_id,role_name,is_system,is_active FROM roles ORDER BY is_system DESC,role_name,role_id").fetchall()


def list_permissions(conn):
    return conn.execute("SELECT permission_id,permission_code,description FROM permissions WHERE is_active=1 ORDER BY permission_code").fetchall()


def name_exists(conn, name):
    return conn.execute("SELECT 1 FROM roles WHERE role_name=?", (name,)).fetchone() is not None


def insert_role(conn, code, name):
    return conn.execute("INSERT INTO roles(role_code,role_name) VALUES(?,?)", (code, name)).lastrowid


def role_flags(conn, role_id):
    return conn.execute("SELECT is_system,is_protected,is_active FROM roles WHERE role_id=?", (role_id,)).fetchone()


def role_details(conn, role_id):
    return conn.execute("SELECT role_name,is_system,is_protected,is_active FROM roles WHERE role_id=?", (role_id,)).fetchone()


def permission_descriptions(conn, role_id):
    return conn.execute("SELECT p.description FROM role_permissions rp JOIN permissions p ON p.permission_id=rp.permission_id WHERE rp.role_id=? ORDER BY p.permission_code", (role_id,)).fetchall()


def owned_permissions(conn, role_id):
    return {row[0] for row in conn.execute("SELECT permission_id FROM role_permissions WHERE role_id=?", (role_id,))}


def assignable_roles(conn):
    return conn.execute("SELECT role_id,role_name FROM roles WHERE is_system=0 AND is_protected=0 AND is_active=1 ORDER BY role_name").fetchall()


def permission_active(conn, permission_id):
    return conn.execute("SELECT 1 FROM permissions WHERE permission_id=? AND is_active=1", (permission_id,)).fetchone() is not None


def enable_permission(conn, role_id, permission_id):
    conn.execute("INSERT OR IGNORE INTO role_permissions(role_id,permission_id) VALUES(?,?)", (role_id, permission_id))


def disable_permission(conn, role_id, permission_id):
    conn.execute("DELETE FROM role_permissions WHERE role_id=? AND permission_id=?", (role_id, permission_id))


def set_active(conn, role_id, enabled):
    conn.execute("UPDATE roles SET is_active=? WHERE role_id=?", (int(enabled), role_id))


def disable_assignments(conn, role_id):
    conn.execute("UPDATE staff_role_assignments SET is_active=0 WHERE role_id=?", (role_id,))


def assignment(conn, staff_id, unit_id, role_id):
    return conn.execute("SELECT assignment_id,is_active FROM staff_role_assignments WHERE staff_id=? AND unit_id=? AND role_id=?", (staff_id, unit_id, role_id)).fetchone()


def restore_assignment(conn, assignment_id, actor):
    conn.execute("UPDATE staff_role_assignments SET is_active=1,assigned_by_staff_id=?,assigned_at=CURRENT_TIMESTAMP WHERE assignment_id=?", (actor, assignment_id))


def insert_assignment(conn, staff_id, unit_id, role_id, actor):
    conn.execute("INSERT INTO staff_role_assignments(staff_id,role_id,unit_id,assigned_by_staff_id) VALUES(?,?,?,?)", (staff_id, role_id, unit_id, actor))


def revoke_assignment(conn, staff_id, unit_id, role_id):
    return conn.execute("UPDATE staff_role_assignments SET is_active=0 WHERE staff_id=? AND unit_id=? AND role_id=? AND is_active=1", (staff_id, unit_id, role_id)).rowcount


def staff_unit_roles(conn, staff_id, unit_id):
    return conn.execute(
        "SELECT r.role_id,r.role_name FROM staff_role_assignments a JOIN roles r ON r.role_id=a.role_id "
        "JOIN staff_unit_memberships m ON m.staff_id=a.staff_id AND m.unit_id=a.unit_id "
        "JOIN staff_mapping s ON s.staff_id=a.staff_id JOIN org_units u ON u.unit_id=a.unit_id "
        "WHERE a.staff_id=? AND a.unit_id=? AND a.is_active=1 AND r.is_active=1 AND m.is_active=1 "
        "AND s.is_active=1 AND u.is_active=1 ORDER BY r.role_name", (staff_id, unit_id),
    ).fetchall()
