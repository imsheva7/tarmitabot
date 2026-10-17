"""Asset storage. Authorization and transaction boundaries live in services."""


def staff(conn, telegram_id):
    return conn.execute("SELECT staff_id,staff_name,role FROM staff_mapping WHERE telegram_user_id=? AND is_active=1",(telegram_id,)).fetchone()


def recipient(conn, staff_id):
    return conn.execute("SELECT staff_name,telegram_user_id FROM staff_mapping WHERE staff_id=? AND is_active=1",(staff_id,)).fetchone()


def staff_list(conn):
    return conn.execute("SELECT staff_id,staff_name FROM staff_mapping WHERE is_active=1").fetchall()


def owned_list(conn, staff_id):
    return conn.execute("SELECT id,asset_type,details FROM user_assets WHERE staff_id=? AND is_active=1",(staff_id,)).fetchall()


def asset(conn, asset_id):
    return conn.execute("SELECT staff_id,asset_type,details,is_active,approval_status FROM user_assets WHERE id=?",(asset_id,)).fetchone()


def recent(conn):
    return conn.execute("SELECT id,staff_name,asset_type,details,is_active,approval_status,encrypted_password FROM user_assets ORDER BY id DESC LIMIT 20").fetchall()


def insert(conn, staff_id, name, kind, details, timestamp, encrypted_password=None, *, approved=False):
    status = 'تأیید قطعی توسط مدیر/سیستم ✅' if approved else 'در انتظار تأیید پرسنل ⏳'
    return conn.execute("""INSERT INTO user_assets(staff_id,staff_name,asset_type,details,is_active,
        approval_status,assigned_at,encrypted_password) VALUES(?,?,?,?,1,?,?,?)""",
        (staff_id,name,kind,details,status,timestamp,encrypted_password)).lastrowid


def confirm(conn, asset_id, staff_id, status):
    return conn.execute("UPDATE user_assets SET approval_status=? WHERE id=? AND staff_id=? AND is_active=1 AND COALESCE(approval_status,'') NOT LIKE '%تأیید قطعی%'",(status,asset_id,staff_id)).rowcount


def edit(conn, asset_id, details):
    return conn.execute("UPDATE user_assets SET details=? WHERE id=?",(details,asset_id)).rowcount


def return_asset(conn, asset_id, date, *, staff_id=None):
    if staff_id is not None:
        return conn.execute("UPDATE user_assets SET is_active=0,return_date=? WHERE id=? AND staff_id=? AND is_active=1",(date,asset_id,staff_id)).rowcount
    return conn.execute("UPDATE user_assets SET is_active=0,return_date=? WHERE id=? AND is_active=1",(date,asset_id)).rowcount


def request_kind(conn, request_id):
    row=conn.execute("SELECT request_type FROM requests WHERE id=?",(request_id,)).fetchone()
    return row[0] if row else None


def request(conn, request_id):
    return conn.execute("""SELECT telegram_user_id,user_name,request_type,req_code,col1,col2,col3,
        sensitive_data,location,status FROM requests WHERE id=?""",(request_id,)).fetchone()


def replacement_response(conn, request_id):
    return conn.execute("SELECT response FROM request_replacements WHERE request_id=?",(request_id,)).fetchone()


def approve_request(conn, request_id):
    return conn.execute("UPDATE requests SET status='✅ تأیید شده قطعی' WHERE id=? AND status LIKE '%در انتظار%'",(request_id,)).rowcount
