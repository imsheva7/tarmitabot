"""Insurance records, active cars and alert recipients."""


def actor_role(conn, actor_id):
    row=conn.execute('SELECT role FROM staff_mapping WHERE telegram_user_id=? AND is_active=1',(actor_id,)).fetchone()
    return row[0] if row else None


def cars(conn):
    return conn.execute("SELECT id,details FROM user_assets WHERE asset_type='خودروی سازمانی' AND is_active=1 ORDER BY id").fetchall()


def insert(conn, values):
    return conn.execute('INSERT INTO vehicle_insurances(car_code,car_name,plate_number,insurance_company,third_party_date,body_date) VALUES(?,?,?,?,?,?)',values).lastrowid


def all_records(conn):
    return conn.execute('SELECT car_code,car_name,plate_number,insurance_company,third_party_date,body_date FROM vehicle_insurances').fetchall()


def main_admins(conn):
    return [row[0] for row in conn.execute("SELECT telegram_user_id FROM staff_mapping WHERE role='main_admin' AND is_active=1 AND telegram_user_id>0")]
