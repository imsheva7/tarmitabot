"""Financial and purchase request storage; callers own transactions."""


def active_staff(conn, actor_id):
    return conn.execute("SELECT staff_id,staff_name,role FROM staff_mapping WHERE telegram_user_id=? AND is_active=1",(actor_id,)).fetchone()


def advance_amounts(conn, actor_id, month):
    return conn.execute("""SELECT amount FROM requests WHERE telegram_user_id=? AND request_type='مساعده'
        AND month_tag=? AND status NOT LIKE '%رد شده%' AND status NOT LIKE '%لغو%'""",(actor_id,month)).fetchall()


def request(conn, request_id):
    return conn.execute("""SELECT telegram_user_id,user_name,request_type,req_code,col1,col2,col3,
        sensitive_data,status FROM requests WHERE id=?""",(request_id,)).fetchone()


def kind(conn, request_id):
    row=conn.execute('SELECT request_type FROM requests WHERE id=?',(request_id,)).fetchone()
    return row[0] if row else None


def replacement(conn, request_id):
    return conn.execute('SELECT response FROM request_replacements WHERE request_id=?',(request_id,)).fetchone()


def approve(conn, request_id):
    return conn.execute("UPDATE requests SET status='✅ تأیید شده قطعی' WHERE id=? AND status LIKE '%در انتظار%'",(request_id,)).rowcount


def complete(conn, request_id, status):
    return conn.execute("UPDATE requests SET status=? WHERE id=? AND status='✅ تأیید شده قطعی'",(status,request_id)).rowcount


def recipient(conn, role):
    row=conn.execute("""SELECT telegram_user_id FROM staff_mapping WHERE role=? AND is_active=1
        AND telegram_user_id>0 ORDER BY staff_id LIMIT 1""",(role,)).fetchone()
    return row[0] if row else None
