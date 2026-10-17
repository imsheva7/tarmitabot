"""Read-only report queries. Export columns are selected from a fixed catalogue."""
from ..reporting.catalogue import ADMIN_EXPORTS

PERSONAL_REQUEST_COLUMNS=('req_code','request_type','col1','col2','col3','status','created_at')
PERSONAL_ASSET_COLUMNS=('asset_type','details','is_active','approval_status','assigned_at')


def active_staff(conn, actor_id):
    return conn.execute('SELECT staff_id,staff_name,leave_balance,role FROM staff_mapping WHERE telegram_user_id=? AND is_active=1',(actor_id,)).fetchone()


def personal_requests(conn, actor_id, *, recent=False):
    sql='SELECT '+','.join(PERSONAL_REQUEST_COLUMNS)+' FROM requests WHERE telegram_user_id=?'
    if recent: sql+=' ORDER BY id DESC LIMIT 5'
    return conn.execute(sql,(actor_id,)).fetchall()


def personal_assets(conn, staff_id):
    return conn.execute('SELECT '+','.join(PERSONAL_ASSET_COLUMNS)+' FROM user_assets WHERE staff_id=?',(staff_id,)).fetchall()


def monthly_stats(conn, actor_id, month):
    leave=conn.execute("""SELECT location FROM requests WHERE telegram_user_id=? AND request_type='مرخصی'
        AND col1 LIKE '%استحقاقی%' AND month_tag=? AND status='✅ تأیید شده قطعی'""",(actor_id,month)).fetchall()
    advances=conn.execute("""SELECT amount FROM requests WHERE telegram_user_id=? AND request_type='مساعده'
        AND month_tag=? AND status IN ('💳 تسویه و پرداخت شده','✅ تأیید شده قطعی')""",(actor_id,month)).fetchall()
    missions=conn.execute("""SELECT COUNT(*) FROM requests WHERE telegram_user_id=? AND request_type='ماموریت'
        AND month_tag=? AND status='✅ تأیید شده قطعی'""",(actor_id,month)).fetchone()[0]
    return leave,advances,missions


def admin_export(conn, key):
    table,_,_,mapping=ADMIN_EXPORTS[key]
    return conn.execute('SELECT '+','.join(mapping)+' FROM '+table).fetchall()


def pending(conn):
    return conn.execute("SELECT id,req_code,user_name,request_type,col1,col2,created_at FROM requests WHERE status LIKE '%در انتظار%' ORDER BY id ASC LIMIT 10").fetchall()


def staff_list(conn):
    return conn.execute('SELECT staff_name,phone_number,is_active,leave_balance,role,employment_date,deactivation_date FROM staff_mapping').fetchall()


def absences(conn):
    return conn.execute("SELECT user_name,request_type,col1,col2,start_date,end_date FROM requests WHERE status LIKE '%تأیید شده%' AND request_type IN ('مرخصی','ماموریت')").fetchall()
