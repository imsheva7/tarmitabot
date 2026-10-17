"""Shared request storage used by the explicit delivery adapter."""


def insert_request(conn, values):
    return conn.execute("""INSERT INTO requests(telegram_user_id,user_name,telegram_info,request_type,col1,col2,col3,
        sensitive_data,amount,start_date,end_date,location,status,created_at,month_tag)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", values).lastrowid


def insert_replacement(conn, request_id, staff_id):
    conn.execute("INSERT OR REPLACE INTO request_replacements(request_id,staff_id,response) VALUES(?,?,NULL)", (request_id, staff_id))


def set_code(conn, request_id, code):
    conn.execute("UPDATE requests SET req_code=? WHERE id=?", (code, request_id))


def set_admin_message(conn, request_id, message_id, chat_id):
    conn.execute("UPDATE requests SET admin_msg_id=?,admin_chat_id=? WHERE id=?", (message_id, chat_id, request_id))


def replacement_recipient(conn, staff_id):
    return conn.execute("SELECT telegram_user_id,staff_name FROM staff_mapping WHERE staff_id=? AND is_active=1", (staff_id,)).fetchone()
