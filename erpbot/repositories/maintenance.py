"""Bounded maintenance operations; never drop tables or reset sequences."""
from .finance import active_staff
from .personnel import record_change
from .audit import record

REQUEST_TABLES=('approval_actions','request_replacements','request_effects','requests')
ASSET_TABLES=('user_assets','vehicle_insurances')
SCOPES={'requests':REQUEST_TABLES,'assets':ASSET_TABLES,'leaves':('leave_ledger',),
        'all_except_staff':REQUEST_TABLES+ASSET_TABLES+('holidays','leave_ledger')}


def counts(conn, target):
    return {table:conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] for table in SCOPES[target]}


def clear(conn, target):
    for table in SCOPES[target]:
        conn.execute(f'DELETE FROM {table}')
    if target=='leaves':
        conn.execute('UPDATE staff_mapping SET leave_balance=0.0')


def balances(conn):
    return conn.execute('SELECT staff_id,staff_name,leave_balance FROM staff_mapping').fetchall()
