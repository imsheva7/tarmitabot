"""Additive, idempotent organization/RBAC schema for ERP Bot V2.

This module defines storage only. It DOES NOT authorize requests, migrate
legacy permissions, or attach existing staff to units automatically.
"""

ROLE_SEEDS = (
    ('staff', 'پرسنل عادی', 1, 0),
    ('finance', 'امور مالی', 1, 0),
    ('purchase', 'امور خرید', 1, 0),
    ('main_admin', 'مدیر اصلی', 1, 1),
)

PERMISSION_SEEDS = (
    ('leave.view_unit', 'مشاهده مرخصی‌های واحد'),
    ('leave.approve_unit', 'تأیید مرحله واحد برای مرخصی'),
    ('warehouse.receipt.view', 'مشاهده رسیدهای انبار'),
    ('warehouse.receipt.approve', 'تأیید رسید ورودی انبار'),
    ('staff.view_unit', 'مشاهده پرسنل واحد'),
    ('organization.manage', 'مدیریت ساختار سازمانی'),
    ('roles.manage', 'مدیریت نقش و مجوز'),
    ('approval_policy.manage', 'مدیریت سیاست‌های تأیید'),
)

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS org_units (
        unit_id INTEGER PRIMARY KEY AUTOINCREMENT,
        unit_code TEXT NOT NULL UNIQUE,
        unit_name TEXT NOT NULL,
        parent_unit_id INTEGER REFERENCES org_units(unit_id) ON DELETE RESTRICT,
        is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CHECK(length(trim(unit_code)) > 0),
        CHECK(length(trim(unit_name)) > 0),
        CHECK(parent_unit_id IS NULL OR parent_unit_id <> unit_id)
    )""",
    """CREATE TABLE IF NOT EXISTS staff_unit_memberships (
        staff_id INTEGER NOT NULL REFERENCES staff_mapping(staff_id) ON DELETE RESTRICT,
        unit_id INTEGER NOT NULL REFERENCES org_units(unit_id) ON DELETE RESTRICT,
        is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)),
        joined_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        left_at TEXT,
        PRIMARY KEY(staff_id, unit_id)
    )""",
    """CREATE TABLE IF NOT EXISTS roles (
        role_id INTEGER PRIMARY KEY AUTOINCREMENT,
        role_code TEXT NOT NULL UNIQUE,
        role_name TEXT NOT NULL,
        is_system INTEGER NOT NULL DEFAULT 0 CHECK(is_system IN (0,1)),
        is_protected INTEGER NOT NULL DEFAULT 0 CHECK(is_protected IN (0,1)),
        is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)),
        CHECK(length(trim(role_code)) > 0),
        CHECK(length(trim(role_name)) > 0)
    )""",
    """CREATE TABLE IF NOT EXISTS permissions (
        permission_id INTEGER PRIMARY KEY AUTOINCREMENT,
        permission_code TEXT NOT NULL UNIQUE,
        description TEXT NOT NULL,
        is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1))
    )""",
    """CREATE TABLE IF NOT EXISTS role_permissions (
        role_id INTEGER NOT NULL REFERENCES roles(role_id) ON DELETE CASCADE,
        permission_id INTEGER NOT NULL REFERENCES permissions(permission_id) ON DELETE RESTRICT,
        PRIMARY KEY(role_id, permission_id)
    )""",
    """CREATE TABLE IF NOT EXISTS staff_role_assignments (
        assignment_id INTEGER PRIMARY KEY AUTOINCREMENT,
        staff_id INTEGER NOT NULL REFERENCES staff_mapping(staff_id) ON DELETE RESTRICT,
        role_id INTEGER NOT NULL REFERENCES roles(role_id) ON DELETE RESTRICT,
        unit_id INTEGER NOT NULL REFERENCES org_units(unit_id) ON DELETE RESTRICT,
        is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)),
        assigned_by_staff_id INTEGER REFERENCES staff_mapping(staff_id) ON DELETE SET NULL,
        assigned_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(staff_id, role_id, unit_id),
        FOREIGN KEY(staff_id, unit_id) REFERENCES staff_unit_memberships(staff_id, unit_id)
    )""",
    """CREATE TABLE IF NOT EXISTS approval_policies (
        policy_id INTEGER PRIMARY KEY AUTOINCREMENT,
        policy_code TEXT NOT NULL UNIQUE,
        request_kind TEXT NOT NULL,
        permission_id INTEGER NOT NULL REFERENCES permissions(permission_id) ON DELETE RESTRICT,
        unit_id INTEGER REFERENCES org_units(unit_id) ON DELETE RESTRICT,
        step_order INTEGER NOT NULL DEFAULT 1 CHECK(step_order > 0),
        requires_main_admin_override INTEGER NOT NULL DEFAULT 0 CHECK(requires_main_admin_override IN (0,1)),
        is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1))
    )""",
    """CREATE TABLE IF NOT EXISTS approval_actions (
        action_id INTEGER PRIMARY KEY AUTOINCREMENT,
        policy_id INTEGER NOT NULL REFERENCES approval_policies(policy_id) ON DELETE RESTRICT,
        request_id INTEGER NOT NULL REFERENCES requests(id) ON DELETE RESTRICT,
        actor_staff_id INTEGER NOT NULL REFERENCES staff_mapping(staff_id) ON DELETE RESTRICT,
        unit_id INTEGER NOT NULL REFERENCES org_units(unit_id) ON DELETE RESTRICT,
        decision TEXT NOT NULL CHECK(decision IN ('approved','rejected')),
        recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        note TEXT,
        UNIQUE(policy_id, request_id, actor_staff_id, decision)
    )""",
    """CREATE TABLE IF NOT EXISTS audit_logs (
        audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
        actor_staff_id INTEGER REFERENCES staff_mapping(staff_id) ON DELETE SET NULL,
        action_code TEXT NOT NULL,
        entity_type TEXT NOT NULL,
        entity_id TEXT,
        details TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""",
    "CREATE INDEX IF NOT EXISTS idx_staff_memberships_unit ON staff_unit_memberships(unit_id, is_active)",
    "CREATE INDEX IF NOT EXISTS idx_assignments_scope ON staff_role_assignments(unit_id, staff_id, is_active)",
    "CREATE INDEX IF NOT EXISTS idx_approval_actions_req ON approval_actions(request_id, policy_id)",
    "CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_logs(created_at)",
)


def migrate_organization_schema(conn):
    """Create the new schema using an existing transaction/connection.

    Call after the legacy staff_mapping and requests tables exist.
    Do not commit here: the caller owns the transaction.
    """
    enabled = conn.execute('PRAGMA foreign_keys').fetchone()[0]
    if enabled != 1:
        raise RuntimeError('SQLite foreign key enforcement must be enabled')
    for statement in SCHEMA:
        conn.execute(statement)
    for code, name, is_system, is_protected in ROLE_SEEDS:
        conn.execute(
            'INSERT OR IGNORE INTO roles (role_code, role_name, is_system, is_protected) VALUES (?, ?, ?, ?)',
            (code, name, is_system, is_protected),
        )
    for code, desc in PERMISSION_SEEDS:
        conn.execute(
            'INSERT OR IGNORE INTO permissions (permission_code, description) VALUES (?, ?)',
            (code, desc),
        )
