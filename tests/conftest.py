"""Isolated file-backed request schema for workflow and delivery tests."""
from types import SimpleNamespace
import pytest
from erpbot.core.database import connect
from erpbot.services.requests import create_request


@pytest.fixture
def leave_db(tmp_path):
    path = tmp_path / "test-only.db"
    def connection():
        return connect(path)

    with connection() as conn:
        conn.executescript("""
            CREATE TABLE staff_mapping(staff_id INTEGER PRIMARY KEY,telegram_user_id INTEGER UNIQUE,
                staff_name TEXT,is_active INTEGER DEFAULT 1,role TEXT DEFAULT 'staff',leave_balance REAL DEFAULT 5);
            CREATE TABLE requests(id INTEGER PRIMARY KEY,telegram_user_id INTEGER,user_name TEXT,telegram_info TEXT,
                req_code TEXT UNIQUE,request_type TEXT,col1 TEXT,col2 TEXT,col3 TEXT,sensitive_data TEXT,amount REAL,
                start_date TEXT,end_date TEXT,location TEXT,status TEXT,created_at TEXT,month_tag TEXT,
                admin_msg_id INTEGER,admin_chat_id INTEGER,rejection_reason TEXT);
            CREATE TABLE request_replacements(request_id INTEGER PRIMARY KEY REFERENCES requests(id),
                staff_id INTEGER REFERENCES staff_mapping(staff_id),response TEXT);
            CREATE TABLE request_effects(request_id INTEGER REFERENCES requests(id),effect_type TEXT,
                PRIMARY KEY(request_id,effect_type));
            CREATE TABLE leave_ledger(id INTEGER PRIMARY KEY,staff_id INTEGER,staff_name TEXT,change_amount REAL,
                description TEXT,registered_by TEXT,created_at TEXT);
            CREATE TABLE holidays(h_date TEXT);
            CREATE TABLE user_assets(id INTEGER PRIMARY KEY,staff_id INTEGER,asset_type TEXT,details TEXT,
                is_active INTEGER,approval_status TEXT);
            INSERT INTO user_assets VALUES(3,2,'تجهیز','شرح',1,'در انتظار');
        """)
        conn.executemany("INSERT INTO staff_mapping VALUES(?,?,?,?,?,?)", [
            (1,101,"مدیر",1,"main_admin",5), (2,202,"کارمند",1,"staff",5),
            (3,303,"جانشین <الف>",1,"staff",5), (4,404,"مالی",1,"finance",5),
            (5,505,"غیرفعال",0,"main_admin",5), (6,None,"بدون اتصال",1,"staff",5),
        ])

    def request(*, kind="مرخصی", col1="نوع: استحقاقی", days="3", replacement=None, owner=202):
        with connection() as conn:
            return create_request(conn,owner,"نام ارسالی","Telegram",kind,col1,"تاریخ","جزئیات",days,
                                  year=1405,created_at="1405/07/24 12:00",month_tag="1405/07",
                                  replacement_staff_id=replacement)

    def row(request_id):
        with connection() as conn:
            return conn.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()

    def effects():
        with connection() as conn:
            return (conn.execute("SELECT leave_balance FROM staff_mapping WHERE staff_id=2").fetchone()[0],
                    conn.execute("SELECT COUNT(*) FROM leave_ledger").fetchone()[0],
                    conn.execute("SELECT COUNT(*) FROM request_effects").fetchone()[0])

    return SimpleNamespace(path=path,connection=connection,request=request,row=row,effects=effects)


@pytest.fixture
def assets_db(tmp_path):
    path=tmp_path/'assets-only.db'
    def connection():
        return connect(path)
    with connection() as conn:
        conn.executescript("""
            CREATE TABLE staff_mapping(staff_id INTEGER PRIMARY KEY,telegram_user_id INTEGER UNIQUE,
                staff_name TEXT,is_active INTEGER,role TEXT);
            INSERT INTO staff_mapping VALUES(1,101,'Admin',1,'main_admin'),(2,202,'Owner',1,'staff'),
                (3,303,'Other',1,'staff'),(4,404,'Finance',1,'finance'),(5,505,'Purchase',1,'purchase'),
                (6,606,'Disabled',0,'main_admin'),(7,NULL,'Unlinked',1,'staff');
            CREATE TABLE user_assets(id INTEGER PRIMARY KEY,staff_id INTEGER,staff_name TEXT,asset_type TEXT,
                details TEXT,is_active INTEGER DEFAULT 1,approval_status TEXT,assigned_at TEXT,return_date TEXT,encrypted_password TEXT);
            CREATE TABLE requests(id INTEGER PRIMARY KEY,telegram_user_id INTEGER,user_name TEXT,telegram_info TEXT,
                req_code TEXT UNIQUE,request_type TEXT,col1 TEXT,col2 TEXT,col3 TEXT,sensitive_data TEXT,amount REAL,
                start_date TEXT,end_date TEXT,location TEXT,status TEXT,created_at TEXT,month_tag TEXT,
                admin_msg_id INTEGER,admin_chat_id INTEGER,rejection_reason TEXT);
            CREATE TABLE request_replacements(request_id INTEGER PRIMARY KEY,staff_id INTEGER,response TEXT);
            ALTER TABLE staff_mapping ADD COLUMN leave_balance REAL DEFAULT 5;
            ALTER TABLE staff_mapping ADD COLUMN phone_number TEXT;
            ALTER TABLE staff_mapping ADD COLUMN employment_date TEXT;
            ALTER TABLE staff_mapping ADD COLUMN deactivation_date TEXT;
            CREATE TABLE vehicle_insurances(id INTEGER PRIMARY KEY,car_code TEXT,car_name TEXT,plate_number TEXT,
                insurance_company TEXT,third_party_date TEXT,body_date TEXT);
        """)
    from erpbot.services import assets
    def assign(actor=101,owner=2,secret=None):
        with connection() as conn:
            return assets.assign(conn,actor,owner,'کارت سوخت','جزئیات','1405/07/24 12:00',secret)[0]
    def request(kind='تحویل اموال',location='کارت سوخت',owner=202,secret='encrypted-secret',amount=0):
        with connection() as conn:
            return create_request(conn,owner,'Owner','Telegram',kind,'ستون یک','ستون دو','ستون سه',location,
                year=1405,created_at='1405/07/24 12:00',month_tag='1405/07',sensitive_data=secret,amount=amount)[0]
    def status(request_id):
        with connection() as conn:
            return conn.execute('SELECT status FROM requests WHERE id=?',(request_id,)).fetchone()[0]
    def rows():
        with connection() as conn:
            return conn.execute('SELECT * FROM user_assets ORDER BY id').fetchall()
    return SimpleNamespace(connection=connection,path=path,assign=assign,request=request,status=status,rows=rows)
