"""Account lookup and guarded Telegram linking; callers own transactions."""
from .personnel import phones, actor_role

FIELDS='staff_id,staff_name,leave_balance,phone_number,is_active,role'


def by_telegram(conn, actor_id):
    return conn.execute(f'SELECT {FIELDS} FROM staff_mapping WHERE telegram_user_id=?',(actor_id,)).fetchone()


def by_id(conn, staff_id):
    return conn.execute(f'SELECT {FIELDS},telegram_user_id FROM staff_mapping WHERE staff_id=?',(staff_id,)).fetchone()


def link(conn, staff_id, actor_id):
    return conn.execute('UPDATE staff_mapping SET telegram_user_id=? WHERE staff_id=? AND is_active=1 AND (telegram_user_id IS NULL OR telegram_user_id=?)',
                        (actor_id,staff_id,actor_id)).rowcount
