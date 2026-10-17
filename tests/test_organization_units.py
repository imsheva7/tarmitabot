"""Isolated organization unit tests: no Telegram, token, or real company database."""
import ast
import importlib.util
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / 'erpbot' / 'services' / 'organization_units.py'
SCHEMA = ROOT / 'erpbot' / 'services' / 'organization_schema.py'
HANDLER = ROOT / 'erpbot' / 'handlers' / 'organization_units.py'


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


units = load(SERVICE, 'testable_organization_units')
schema = load(SCHEMA, 'testable_organization_schema')


@pytest.fixture
def conn():
    db = sqlite3.connect(':memory:')
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('CREATE TABLE staff_mapping(staff_id INTEGER PRIMARY KEY, staff_name TEXT, role TEXT)')
    db.execute('CREATE TABLE requests(id INTEGER PRIMARY KEY)')
    db.execute("INSERT INTO staff_mapping VALUES (1,'Admin','main_admin')")
    schema.migrate_organization_schema(db)
    db.commit()
    try:
        yield db
    finally:
        db.close()


def test_create_root_and_subunit(conn):
    root = units.create_unit(conn, 'پخش', actor_staff_id=1)
    child = units.create_unit(conn, 'پخش شهری', parent_unit_id=root, actor_staff_id=1)
    conn.commit()
    assert conn.execute('SELECT parent_unit_id FROM org_units WHERE unit_id=?', (child,)).fetchone()[0] == root
    assert 'پخش شهری' in units.render_org_chart(conn)
    assert conn.execute('SELECT COUNT(*) FROM audit_logs').fetchone()[0] == 2


def test_duplicate_sibling_rejected(conn):
    units.create_unit(conn, 'انبار')
    with pytest.raises(units.OrganizationUnitError):
        units.create_unit(conn, ' انبار ')
    assert conn.execute('SELECT COUNT(*) FROM org_units').fetchone()[0] == 1


def test_same_name_different_parent_allowed(conn):
    a = units.create_unit(conn, 'انبار')
    b = units.create_unit(conn, 'پخش')
    units.create_unit(conn, 'شیفت شب', a)
    units.create_unit(conn, 'شیفت شب', b)
    assert conn.execute("SELECT COUNT(*) FROM org_units WHERE unit_name='شیفت شب'").fetchone()[0] == 2


def test_inactive_parent_rejected(conn):
    parent = units.create_unit(conn, 'تأسیسات')
    conn.execute('UPDATE org_units SET is_active=0 WHERE unit_id=?', (parent,))
    with pytest.raises(units.OrganizationUnitError):
        units.create_unit(conn, 'خرید', parent)


@pytest.mark.parametrize('name', ['', ' ', 'X'*81, '\n'])
def test_invalid_names(conn, name):
    with pytest.raises(units.OrganizationUnitError):
        units.create_unit(conn, name)


def test_invalid_parent_rejected(conn):
    with pytest.raises(units.OrganizationUnitError):
        units.create_unit(conn, 'مالی', 999)


def test_invalid_manual_code_rejected(conn):
    with pytest.raises(units.OrganizationUnitError):
        units.create_unit(conn, 'مالی', unit_code='bad-code!')


def test_schema_foreign_keys_and_chart_with_orphan_parent(conn):
    root = units.create_unit(conn, 'پخش')
    child = units.create_unit(conn, 'پخش شهری', root)
    conn.commit()
    assert conn.execute('PRAGMA foreign_key_check').fetchall() == []
    conn.execute('UPDATE org_units SET is_active=0 WHERE unit_id=?', (root,))
    assert 'پخش شهری' in units.render_org_chart(conn)
    assert 'پخش\n' not in units.render_org_chart(conn)


def test_handlers_use_explicit_dependencies_without_sql_or_runtime_import():
    tree = ast.parse(HANDLER.read_text(encoding='utf-8'))
    names = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)}
    required = ('orgunits_menu', 'orgunits_chart', 'orgunits_choose_parent',
                'orgunits_pick_parent', 'orgunits_save_name')
    for name in required:
        assert name in names
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert 'runtime' not in (node.module or '').split('.')
            assert all(alias.name != '*' for alias in node.names)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in {'execute', 'executemany', 'executescript'}
    service_tree = ast.parse(SERVICE.read_text(encoding='utf-8'))
    for node in ast.walk(service_tree):
        if isinstance(node, ast.ImportFrom):
            assert not {'runtime', 'aiogram', 'handlers'} & set((node.module or '').split('.'))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in {'execute', 'executemany', 'executescript', 'commit', 'rollback'}
