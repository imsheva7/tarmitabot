"""Regressions for legacy user_id databases; no production key or network."""
from test_explicit_bootstrap import run_isolated


SETUP=r'''
import asyncio
import sqlite3
from pathlib import Path
from cryptography.fernet import Fernet
from erpbot.bootstrap import initialize_runtime
from erpbot.core import runtime
from erpbot.core.settings import Settings
path=Path.cwd()/'enterprise_requests.db'
'''
BOOT=r'''
app=initialize_runtime(Settings.from_env({'BOT_TOKEN':'123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk',
    'FERNET_KEY':Fernet.generate_key().decode(),'ENABLE_INITIAL_STAFF_SEED':'0'},data_directory=Path.cwd()),configure_logging=False)
'''


def test_legacy_columns_migrate_before_startup_queries_and_preserve_data(tmp_path):
    run_isolated(tmp_path,SETUP+r'''
with sqlite3.connect(path) as conn:
    conn.executescript("""
        CREATE TABLE staff_mapping(user_id INTEGER PRIMARY KEY,staff_name TEXT UNIQUE,phone_number TEXT,
            is_active INTEGER,leave_balance REAL,role TEXT,employment_date TEXT,deactivation_date TEXT);
        INSERT INTO staff_mapping VALUES(202,'Genuine','09120000001',1,8,'main_admin','1400/01/01',NULL);
        INSERT INTO staff_mapping VALUES(1000,'Placeholder','09120000002',1,3,'staff','1400/01/02',NULL);
        CREATE TABLE requests(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,user_name TEXT,req_code TEXT UNIQUE,
            telegram_info TEXT,request_type TEXT,col1 TEXT,col2 TEXT,col3 TEXT,status TEXT,created_at TEXT);
        INSERT INTO requests(user_id,user_name,req_code,status) VALUES(202,'Genuine','REQ-1405-00001','در انتظار');
        CREATE TABLE reminders(id INTEGER PRIMARY KEY,user_id INTEGER,chat_id INTEGER,user_name TEXT,remind_time TEXT,text_content TEXT);
        INSERT INTO reminders VALUES(1,202,202,'Genuine','08:00','Preserve reminder');
        CREATE TABLE leave_ledger(id INTEGER PRIMARY KEY,staff_name TEXT,change_amount REAL,description TEXT,registered_by TEXT,created_at TEXT);
        INSERT INTO leave_ledger VALUES(1,'Genuine',8,'Existing','Test','1405/01/01');
        CREATE TABLE user_assets(id INTEGER PRIMARY KEY,staff_name TEXT,asset_type TEXT,details TEXT,is_active INTEGER);
        INSERT INTO user_assets VALUES(1,'Genuine','تجهیز','Preserve asset',1);
    """)
'''+BOOT+r'''
try:
    runtime.init_db()
    with runtime.get_connection() as conn:
        assert tuple(conn.execute('SELECT staff_id,telegram_user_id,leave_balance,role FROM staff_mapping WHERE staff_id=202').fetchone())==(202,202,8,'main_admin')
        assert tuple(conn.execute('SELECT staff_id,telegram_user_id,leave_balance FROM staff_mapping WHERE staff_id=1000').fetchone())==(1000,None,3)
        assert conn.execute('SELECT COUNT(*) FROM staff_mapping_legacy_backup').fetchone()[0]==2
        assert conn.execute('SELECT telegram_user_id FROM requests').fetchone()[0]==202
        assert conn.execute('SELECT telegram_user_id FROM reminders').fetchone()[0]==202
        assert conn.execute('SELECT staff_id FROM user_assets').fetchone()[0]==202
        assert conn.execute('SELECT staff_id FROM leave_ledger WHERE id=1').fetchone()[0]==202
        assert conn.execute('SELECT COUNT(*) FROM leave_ledger').fetchone()[0]==2
        assert conn.execute('PRAGMA foreign_key_check').fetchall()==[]
    runtime.init_db()
    with runtime.get_connection() as conn:
        assert conn.execute('SELECT COUNT(*) FROM staff_mapping').fetchone()[0]==2
        assert conn.execute('SELECT COUNT(*) FROM leave_ledger').fetchone()[0]==2
finally: asyncio.run(app.close())
''')


def test_unknown_legacy_schema_aborts_without_data_changes(tmp_path):
    run_isolated(tmp_path,SETUP+r'''
with sqlite3.connect(path) as conn:
    conn.execute('CREATE TABLE staff_mapping(unknown_id INTEGER,staff_name TEXT)')
    conn.execute("INSERT INTO staff_mapping VALUES(1,'Preserve')")
'''+BOOT+r'''
try:
    try: runtime.init_db()
    except RuntimeError as exc: assert 'Unknown staff_mapping' in str(exc)
    else: raise AssertionError('Unknown schema accepted')
    with sqlite3.connect(path) as conn:
        assert conn.execute('SELECT * FROM staff_mapping').fetchall()==[(1,'Preserve')]
        assert conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()==[('staff_mapping',)]
finally: asyncio.run(app.close())
''')


def test_failed_legacy_conversion_rolls_back_ddl_too(tmp_path):
    run_isolated(tmp_path,SETUP+r'''
with sqlite3.connect(path) as conn:
    conn.executescript("""
        CREATE TABLE staff_mapping(user_id INTEGER PRIMARY KEY,staff_name TEXT,phone_number TEXT,
            is_active INTEGER,leave_balance REAL,role TEXT,employment_date TEXT,deactivation_date TEXT);
        INSERT INTO staff_mapping VALUES(202,'Duplicate',NULL,1,5,'staff',NULL,NULL);
        INSERT INTO staff_mapping VALUES(303,'Duplicate',NULL,1,7,'staff',NULL,NULL);
    """)
'''+BOOT+r'''
try:
    for attempt in range(2):
        try: runtime.init_db()
        except sqlite3.IntegrityError: pass
        else: raise AssertionError('Duplicate legacy names silently changed')
        with sqlite3.connect(path) as conn:
            assert conn.execute('SELECT user_id,leave_balance FROM staff_mapping ORDER BY user_id').fetchall()==[(202,5),(303,7)]
            assert conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()==[('staff_mapping',)]
finally: asyncio.run(app.close())
''')
