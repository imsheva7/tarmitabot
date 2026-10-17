"""Leave persistence. Connections and transaction boundaries belong to callers."""
from .organization_units import main_admin_staff_id


def active_staff(conn, telegram_id):
    return conn.execute("SELECT staff_id,staff_name,leave_balance FROM staff_mapping WHERE telegram_user_id=? AND is_active=1", (telegram_id,)).fetchone()


def request_kind(conn, request_id):
    row = conn.execute("SELECT request_type FROM requests WHERE id=?", (request_id,)).fetchone()
    return row[0] if row else None


def request_kind_by_code(conn, code):
    row = conn.execute("SELECT request_type FROM requests WHERE req_code=?", (code,)).fetchone()
    return row[0] if row else None


def approval_request(conn, request_id):
    return conn.execute("SELECT telegram_user_id,req_code,request_type,col1,location FROM requests WHERE id=?", (request_id,)).fetchone()


def annual_request(conn, request_id):
    return conn.execute("""SELECT r.telegram_user_id,r.user_name,r.req_code,r.request_type,r.col1,r.location,r.status,
        s.staff_id,s.leave_balance FROM requests r LEFT JOIN staff_mapping s ON s.telegram_user_id=r.telegram_user_id
        WHERE r.id=?""", (request_id,)).fetchone()


def replacement_response(conn, request_id):
    return conn.execute("SELECT response FROM request_replacements WHERE request_id=?", (request_id,)).fetchone()


def mark_debit(conn, request_id):
    return conn.execute("INSERT OR IGNORE INTO request_effects(request_id,effect_type) VALUES(?,'leave_debit')", (request_id,)).rowcount


def record_debit(conn, staff_id, name, days, description, timestamp):
    conn.execute("INSERT INTO leave_ledger(staff_id,staff_name,change_amount,description,registered_by,created_at) VALUES(?,?,?,?,?,?)",
                 (staff_id, name, -days, description, "مدیر اصلی", timestamp))


def set_balance(conn, staff_id, balance):
    return conn.execute("UPDATE staff_mapping SET leave_balance=? WHERE staff_id=?", (balance, staff_id)).rowcount


def approve_pending(conn, request_id):
    return conn.execute("UPDATE requests SET status='✅ تأیید شده قطعی' WHERE id=? AND status LIKE '%در انتظار%'", (request_id,)).rowcount


def request_for_replacement(conn, request_id):
    return conn.execute("SELECT req_code,user_name,col1,col2,col3,admin_msg_id,admin_chat_id,status FROM requests WHERE id=?", (request_id,)).fetchone()


def replacement_assignment(conn, request_id):
    return conn.execute("SELECT staff_id,response FROM request_replacements WHERE request_id=?", (request_id,)).fetchone()


def set_replacement_response(conn, request_id, response):
    return conn.execute("UPDATE request_replacements SET response=? WHERE request_id=? AND response IS NULL", (response, request_id)).rowcount


def update_replacement_status(conn, request_id, details, approved):
    if approved:
        return conn.execute("UPDATE requests SET col3=? WHERE id=? AND status LIKE '%در انتظار%'", (details, request_id)).rowcount
    return conn.execute("UPDATE requests SET col3=?,status='❌ رد شده توسط جانشین' WHERE id=? AND status LIKE '%در انتظار%'", (details, request_id)).rowcount


def notification_request(conn, request_id):
    return conn.execute("SELECT telegram_user_id,req_code,admin_chat_id,admin_msg_id,status,request_type FROM requests WHERE id=?", (request_id,)).fetchone()


def reject_pending(conn, request_id, reason):
    return conn.execute("UPDATE requests SET status='❌ رد شده',rejection_reason=? WHERE id=? AND status LIKE '%در انتظار%'", (reason, request_id)).rowcount


def cancellation_request(conn, code):
    return conn.execute("SELECT id,telegram_user_id,status,admin_chat_id,admin_msg_id,request_type FROM requests WHERE req_code=?", (code,)).fetchone()


def cancel_pending(conn, request_id, telegram_id):
    return conn.execute("UPDATE requests SET status='❌ لغو شده توسط پرسنل' WHERE id=? AND telegram_user_id=? AND status LIKE '%در انتظار%'", (request_id, telegram_id)).rowcount


def holidays(conn):
    return [row[0] for row in conn.execute("SELECT h_date FROM holidays")]


def pending_days(conn, telegram_id):
    rows = conn.execute("SELECT location FROM requests WHERE telegram_user_id=? AND request_type='مرخصی' AND col1 LIKE '%استحقاقی%' AND status LIKE '%در انتظار%'", (telegram_id,)).fetchall()
    return sum(float(row[0]) for row in rows if row[0] and str(row[0]).replace('.', '', 1).isdigit())


def replacement_candidates(conn, telegram_id):
    return conn.execute("SELECT staff_id,staff_name FROM staff_mapping WHERE is_active=1 AND telegram_user_id!=?", (telegram_id,)).fetchall()


def replacement_staff(conn, staff_id):
    return conn.execute("SELECT staff_name,telegram_user_id FROM staff_mapping WHERE staff_id=? AND is_active=1", (staff_id,)).fetchone()
