"""Personnel and leave-ledger storage; callers own authorization and transactions."""
EDIT_FIELDS={'staff_name','phone_number','leave_balance','employment_date'}


def actor_role(conn, actor_id):
    row=conn.execute('SELECT role FROM staff_mapping WHERE telegram_user_id=? AND is_active=1',(actor_id,)).fetchone()
    return row[0] if row else None


def active_list(conn):
    return conn.execute('SELECT staff_id,staff_name FROM staff_mapping WHERE is_active=1').fetchall()


def target(conn, staff_id):
    return conn.execute('SELECT staff_name,leave_balance,is_active FROM staff_mapping WHERE staff_id=?',(staff_id,)).fetchone()


def phones(conn):
    return conn.execute('SELECT staff_id,phone_number FROM staff_mapping WHERE phone_number IS NOT NULL').fetchall()


def insert(conn, name, phone, role, balance, date):
    return conn.execute('INSERT INTO staff_mapping(staff_name,phone_number,role,leave_balance,employment_date,is_active) VALUES(?,?,?,?,?,1)',
                        (name,phone,role,balance,date)).lastrowid


def ledger_total(conn, staff_id):
    return conn.execute('SELECT COALESCE(SUM(change_amount),0) FROM leave_ledger WHERE staff_id=?',(staff_id,)).fetchone()[0]


def record_change(conn, staff_id, name, amount, description, timestamp):
    conn.execute('INSERT INTO leave_ledger(staff_id,staff_name,change_amount,description,registered_by,created_at) VALUES(?,?,?,?,?,?)',
                 (staff_id,name,amount,description,'مدیر اصلی',timestamp))


def edit(conn, staff_id, field, value):
    if field not in EDIT_FIELDS: raise ValueError('Unsupported staff field')
    return conn.execute(f'UPDATE staff_mapping SET {field}=? WHERE staff_id=? AND is_active=1',(value,staff_id)).rowcount


def deactivate(conn, staff_id, date):
    return conn.execute('UPDATE staff_mapping SET is_active=0,telegram_user_id=NULL,deactivation_date=? WHERE staff_id=? AND is_active=1',(date,staff_id)).rowcount


def deactivate_assets(conn, staff_id):
    conn.execute('UPDATE user_assets SET is_active=0 WHERE staff_id=?',(staff_id,))
