"""Shared request decisions; authorization and transaction ownership are external."""
from .finance import approve, replacement, active_staff

FIELDS='id,telegram_user_id,req_code,request_type,status,admin_chat_id,admin_msg_id'


def request(conn, request_id):
    return conn.execute(f'SELECT {FIELDS} FROM requests WHERE id=?',(request_id,)).fetchone()


def by_code(conn, code):
    return conn.execute(f'SELECT {FIELDS} FROM requests WHERE req_code=?',(code,)).fetchone()


def reject(conn, request_id, reason):
    return conn.execute("UPDATE requests SET status='❌ رد شده',rejection_reason=? WHERE id=? AND status LIKE '%در انتظار%'",
                        (reason,request_id)).rowcount


def cancel(conn, request_id, actor_id):
    return conn.execute("UPDATE requests SET status='❌ لغو شده توسط پرسنل' WHERE id=? AND telegram_user_id=? AND status LIKE '%در انتظار%'",
                        (request_id,actor_id)).rowcount
