"""Mission reads and guarded approval updates."""


def staff(conn, actor_id):
    return conn.execute('SELECT staff_id,staff_name,role FROM staff_mapping WHERE telegram_user_id=? AND is_active=1',(actor_id,)).fetchone()


def request_kind(conn, request_id):
    row=conn.execute('SELECT request_type FROM requests WHERE id=?',(request_id,)).fetchone()
    return row[0] if row else None


def request(conn, request_id):
    return conn.execute('SELECT telegram_user_id,req_code,request_type,status FROM requests WHERE id=?',(request_id,)).fetchone()


def replacement(conn, request_id):
    return conn.execute('SELECT response FROM request_replacements WHERE request_id=?',(request_id,)).fetchone()


def approve(conn, request_id):
    return conn.execute("UPDATE requests SET status='✅ تأیید شده قطعی' WHERE id=? AND status LIKE '%در انتظار%'",(request_id,)).rowcount
