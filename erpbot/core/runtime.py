import os


import re


import io


import asyncio


import sqlite3


import logging


import pytz


import html


from contextlib import contextmanager


from datetime import datetime, timedelta


import jdatetime


import pandas as pd


from cryptography.fernet import Fernet


from aiogram import Bot, Dispatcher, F, BaseMiddleware


from aiogram.filters import Command, CommandObject


from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    FSInputFile, BufferedInputFile, ChatMemberUpdated
)


from aiogram.filters import ChatMemberUpdatedFilter, IS_MEMBER


from aiogram.fsm.context import FSMContext


from aiogram.fsm.state import State, StatesGroup

from .database import connect as _connect_database
from .encryption import encrypt_text as _encrypt_text, decrypt_text as _decrypt_text


_application = None
_settings = None
ENCRYPTION_KEY_PATH = None
FERNET_ENV_KEY = None
cipher_suite = None
TOKEN = None
GROUP_ID = None
DB_DIR = None
DB_PATH = None
bot = None
dp = None


def require_initialized():
    if _application is None:
        raise RuntimeError("Call erpbot.bootstrap.initialize_runtime() before using the legacy runtime")
    if _application._closed:
        raise RuntimeError("Application is closed; restart the process")
    return _application


def _bind_application(application):
    global _application, _settings, ENCRYPTION_KEY_PATH, FERNET_ENV_KEY
    global cipher_suite, TOKEN, GROUP_ID, DB_DIR, DB_PATH, bot, dp
    if _application is not None:
        raise RuntimeError("Runtime is already initialized")
    _application = application
    _settings = application.settings
    ENCRYPTION_KEY_PATH = _settings.encryption_key_path
    FERNET_ENV_KEY = _settings.fernet_key
    cipher_suite = application.cipher
    TOKEN = _settings.bot_token
    GROUP_ID = _settings.group_id
    DB_DIR = _settings.database_directory
    DB_PATH = _settings.database_path
    bot = application.bot
    dp = application.dispatcher


def encrypt_data(plain_text: str) -> str:
    return _encrypt_text(require_initialized().cipher, plain_text)


def decrypt_data(encrypted_text: str) -> str:
    return _decrypt_text(require_initialized().cipher, encrypted_text)


ARCHIVE_TOPIC_ID = 109  # تاپیک بایگانی یادآوری‌ها


TEHRAN_TZ = pytz.timezone('Asia/Tehran')


def get_current_tehran_time():
    from .dates import get_current_tehran_time as clock
    return clock()


TOPIC_LEAVE = 2     


TOPIC_ADVANCE = 3   


TOPIC_MISSION = 38  


TOPIC_PETTY = 57    


TOPIC_ASSETS = 59   


TOPIC_PURCHASE = 70 


TOPIC_INSURANCE = 73


MAX_BASE_ADVANCE = 100_000_000


INITIAL_STAFF_SEED = [
    ("امید یزدان پناه", "09393734293", "staff", "1404/01/01"),
    ("ایمان یزدان پناه", "09361562521", "main_admin", "1404/01/01"),
    ("امین ارکیان", "09135001135", "staff", "1404/01/01"),
    ("محمدصالح یزدان پناه", "09214552765", "staff", "1404/01/01"),
    ("پویا عابدی", "09378628800", "staff", "1404/01/01"),
    ("فاطمه ارکیان", "09140925381", "staff", "1404/01/01"),
    ("رضا مقصودی", "09367858095", "staff", "1404/01/01"),
    ("شهریار محمدی", "09302387127", "staff", "1404/01/01"),
    ("شهرزاد محمدی", "09057935492", "finance", "1404/01/01"),
    ("امیر حسین اسدی", "09393803016", "staff", "1404/01/01"),
    ("پوریا پیرای", "09140463353", "staff", "1404/01/01"),
    ("علیرضا بابایی", "09137607180", "staff", "1404/01/01"),
    ("حمیده زینلی", "09050957157", "staff", "1404/01/01"),
    ("ابراهیم معاذالهی", "09134781259", "staff", "1404/01/01"),
    ("داریوش دایی زاده", "09215210553", "staff", "1404/01/01"),
    ("ابوالفضل احمدنژاد", "09335015951", "staff", "1404/01/01"),
    ("مهدی نژاد شاهرخ آبادی", "09027215636", "staff", "1404/01/01"),
    ("آرمان خاندان", "09133539329", "staff", "1404/01/01"),
    ("علیرضا نگاری", "09380526509", "staff", "1404/01/01"),
    ("حلیمه امیری", "09010778008", "staff", "1404/01/01"),
    ("احمدرضا آموزنده", "09909070723", "staff", "1404/01/01")
]


def normalize_persian_numbers(text: str) -> str:
    from .dates import normalize_persian_numbers as normalize
    return normalize(text)


def normalize_jalali_date(date_text: str) -> str:
    from .dates import normalize_jalali_date as normalize
    return normalize(date_text)


def _table_columns(conn, table):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def migrate_legacy_database(conn):
    """Transactional, idempotent migration of the original user_id-based schema.

    Must run before CREATE TABLE and before the new schema's seed logic.
    A consistent external backup is REQUIRED before deployment.
    """
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "staff_mapping" not in tables or "staff_id" in _table_columns(conn, "staff_mapping"):
        return
    old_cols = _table_columns(conn, "staff_mapping")
    if "user_id" not in old_cols:
        raise RuntimeError("Unknown staff_mapping schema; migration aborted")
    # Preserve all existing staff IDs as new stable IDs and link genuine Telegram IDs only.
    # Old seed placeholders 1000..1020 must not be interpreted as Telegram accounts.
    conn.execute("""CREATE TABLE staff_mapping_v2 (
        staff_id INTEGER PRIMARY KEY AUTOINCREMENT, telegram_user_id INTEGER UNIQUE,
        staff_name TEXT UNIQUE, phone_number TEXT, is_active INTEGER DEFAULT 1,
        leave_balance REAL DEFAULT 0, role TEXT DEFAULT 'staff',
        employment_date TEXT, deactivation_date TEXT)""")
    conn.execute("""INSERT INTO staff_mapping_v2
        (staff_id, telegram_user_id, staff_name, phone_number, is_active, leave_balance, role, employment_date, deactivation_date)
        SELECT user_id, CASE WHEN user_id BETWEEN 1000 AND 1020 THEN NULL ELSE user_id END,
        staff_name, phone_number, is_active, leave_balance, role, employment_date, deactivation_date
        FROM staff_mapping""")
    conn.execute("ALTER TABLE staff_mapping RENAME TO staff_mapping_legacy_backup")
    conn.execute("ALTER TABLE staff_mapping_v2 RENAME TO staff_mapping")
    if "requests" in tables and "user_id" in _table_columns(conn, "requests"):
        conn.execute("ALTER TABLE requests ADD COLUMN telegram_user_id INTEGER")
        conn.execute("""UPDATE requests SET telegram_user_id = user_id
                     WHERE user_id NOT BETWEEN 1000 AND 1020""")
    if "reminders" in tables and "user_id" in _table_columns(conn, "reminders"):
        conn.execute("ALTER TABLE reminders ADD COLUMN telegram_user_id INTEGER")
        conn.execute("""UPDATE reminders SET telegram_user_id = user_id
                     WHERE user_id NOT BETWEEN 1000 AND 1020""")
    if "leave_ledger" in tables and "staff_id" not in _table_columns(conn, "leave_ledger"):
        conn.execute("ALTER TABLE leave_ledger ADD COLUMN staff_id INTEGER")
        conn.execute("""UPDATE leave_ledger SET staff_id =
            (SELECT staff_id FROM staff_mapping WHERE staff_mapping.staff_name = leave_ledger.staff_name)
            WHERE staff_id IS NULL""")
    if "user_assets" in tables and "staff_id" not in _table_columns(conn, "user_assets"):
        conn.execute("ALTER TABLE user_assets ADD COLUMN staff_id INTEGER")
        conn.execute("""UPDATE user_assets SET staff_id =
            (SELECT staff_id FROM staff_mapping WHERE staff_mapping.staff_name = user_assets.staff_name)
            WHERE staff_id IS NULL""")


def get_connection():
    # Keep the legacy entry point and resolve DB_PATH on each call. Tests and
    # isolated tools already override this path before opening connections.
    require_initialized()
    return _connect_database(DB_PATH)


def init_db():
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        migrate_legacy_database(conn)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                req_code TEXT UNIQUE,
                telegram_user_id INTEGER,
                user_name TEXT,
                telegram_info TEXT,
                request_type TEXT,
                col1 TEXT,
                col2 TEXT,
                col3 TEXT,
                sensitive_data TEXT,
                amount INTEGER DEFAULT 0,
                start_date TEXT,
                end_date TEXT,
                location TEXT,
                status TEXT,
                created_at TEXT,
                month_tag TEXT,
                rejection_reason TEXT,
                admin_msg_id INTEGER,
                admin_chat_id INTEGER
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS staff_mapping (
                staff_id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_user_id INTEGER UNIQUE,
                staff_name TEXT UNIQUE,
                phone_number TEXT,
                is_active INTEGER DEFAULT 1,
                leave_balance REAL DEFAULT 0.0,
                role TEXT DEFAULT 'staff',
                employment_date TEXT,
                deactivation_date TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS leave_ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                staff_id INTEGER,
                staff_name TEXT,
                change_amount REAL,
                description TEXT,
                registered_by TEXT,
                created_at TEXT
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS holidays (
                h_date TEXT PRIMARY KEY,
                description TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS vehicle_insurances (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                car_code TEXT,
                car_name TEXT,
                plate_number TEXT,
                insurance_company TEXT,
                third_party_date TEXT,
                body_date TEXT
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                staff_id INTEGER,
                staff_name TEXT,
                asset_type TEXT,
                details TEXT,
                is_active INTEGER DEFAULT 1,
                approval_status TEXT DEFAULT 'در انتظار تأیید پرسنل ⏳',
                return_date TEXT,
                assigned_at TEXT,
                encrypted_password TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                message_thread_id INTEGER,
                telegram_user_id INTEGER,
                user_name TEXT,
                remind_type TEXT DEFAULT 'once', 
                day_of_week TEXT,                
                day_of_month INTEGER,            
                remind_time TEXT,                
                remind_at TEXT,                  
                text_content TEXT,
                is_sent INTEGER DEFAULT 0,
                last_fired TEXT
            )
        """)

        cursor.execute("""CREATE TABLE IF NOT EXISTS request_replacements (
            request_id INTEGER PRIMARY KEY, staff_id INTEGER NOT NULL,
            response TEXT CHECK(response IN ('approved','rejected') OR response IS NULL))""")
        cursor.execute("""CREATE TABLE IF NOT EXISTS request_effects (
            request_id INTEGER NOT NULL, effect_type TEXT NOT NULL,
            PRIMARY KEY(request_id, effect_type))""")

        # اسکریپت مهاجرت دیتابیس‌های قدیمی (ALTER TABLE)
        tables_columns = {
            "requests": [("telegram_user_id", "INTEGER"), ("sensitive_data", "TEXT"), ("amount", "INTEGER DEFAULT 0"), ("start_date", "TEXT"), ("end_date", "TEXT"), ("location", "TEXT"), ("month_tag", "TEXT"), ("rejection_reason", "TEXT"), ("admin_msg_id", "INTEGER"), ("admin_chat_id", "INTEGER")],
            "staff_mapping": [("leave_balance", "REAL DEFAULT 0.0"), ("role", "TEXT DEFAULT 'staff'"), ("employment_date", "TEXT"), ("deactivation_date", "TEXT")],
            "reminders": [("telegram_user_id", "INTEGER"), ("last_fired", "TEXT")],
            "user_assets": [("approval_status", "TEXT DEFAULT 'در انتظار تأیید پرسنل ⏳'"), ("return_date", "TEXT"), ("assigned_at", "TEXT"), ("encrypted_password", "TEXT")]
        }
        for table, cols in tables_columns.items():
            cursor.execute(f"PRAGMA table_info({table})")
            existing_cols = [col[1] for col in cursor.fetchall()]
            for col_name, col_type in cols:
                if col_name not in existing_cols:
                    try:
                        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}")
                    except Exception:
                        pass
        
        for sname, phone, role, emp_date in (INITIAL_STAFF_SEED if _settings.enable_initial_staff_seed else []):
            cursor.execute("""
                INSERT OR IGNORE INTO staff_mapping (staff_name, phone_number, is_active, leave_balance, role, employment_date) 
                VALUES (?, ?, 1, 0.0, ?, ?)
            """, (sname, phone, role, emp_date))
            cursor.execute("""
                UPDATE staff_mapping SET phone_number = ? WHERE staff_name = ? AND (phone_number IS NULL OR phone_number = '')
            """, (phone, sname))
                
        # Existing admin role assignments are retained. Bootstrap only with explicit configuration.
        bootstrap_admin = _settings.bootstrap_admin_telegram_id
        if bootstrap_admin is not None:
            cursor.execute("""UPDATE staff_mapping SET telegram_user_id = ?, role = 'main_admin'
                              WHERE role = 'main_admin' AND telegram_user_id IS NULL""", (int(bootstrap_admin),))
        
        cursor.execute("SELECT staff_id, staff_name, leave_balance FROM staff_mapping")
        for srow in cursor.fetchall():
            sid, sname, lbal = srow[0], srow[1], srow[2]
            cursor.execute("SELECT COUNT(*) FROM leave_ledger WHERE staff_id = ?", (sid,))
            if cursor.fetchone()[0] == 0 and lbal != 0.0:
                now_str = get_current_tehran_time().strftime("%Y/%m/%d %H:%M")
                cursor.execute("""
                    INSERT INTO leave_ledger (staff_id, staff_name, change_amount, description, registered_by, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (sid, sname, lbal, "مانده مرخصی اولیه سیستمی", "سیستم", now_str))
                
        # Phase 1: additive organization and scoped RBAC tables; legacy auth unchanged.
        from ..services.organization_schema import migrate_organization_schema
        migrate_organization_schema(conn)

        conn.commit()


# Database initialization is invoked explicitly from erpbot.main.main().


def generate_req_code(req_id: int) -> str:
    year_j = get_current_tehran_time().year
    return f"REQ-{year_j}-{req_id:05d}"


def get_staff_info_by_telegram_id(telegram_user_id: int):
    from ..repositories.navigation import by_telegram
    with get_connection() as conn:
        row = by_telegram(conn, telegram_user_id)
        return row if row else (None, None, 0.0, None, 0, 'staff')


def is_active_staff(telegram_user_id: int) -> bool:
    staff_id, _, _, _, is_active, _ = get_staff_info_by_telegram_id(telegram_user_id)
    return bool(staff_id) and is_active == 1


def check_user_role(telegram_user_id: int, required_role: str) -> bool:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT role FROM staff_mapping WHERE telegram_user_id = ? AND is_active = 1", (telegram_user_id,))
        row = cursor.fetchone()
        if not row:
            return False
        user_role = row[0]
        if user_role == "main_admin":
            return True
        return user_role == required_role


def is_any_admin(telegram_user_id: int) -> bool:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT role FROM staff_mapping WHERE telegram_user_id = ? AND is_active = 1", (telegram_user_id,))
        row = cursor.fetchone()
        if not row:
            return False
        return row[0] in ("main_admin", "finance", "purchase")


async def require_active_staff_callback(callback: CallbackQuery) -> bool:
    if not is_active_staff(callback.from_user.id):
        await callback.answer("برای استفاده از این بخش ابتدا حساب پرسنلی خود را از /start متصل کنید.", show_alert=True)
        return False
    return True


def get_holidays_list():
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT h_date FROM holidays")
        return [r[0] for r in cursor.fetchall()]


def validate_custom_date(date_text: str) -> bool:
    from .dates import validate_custom_date as validate
    return validate(date_text)


def validate_time_str(time_text: str) -> bool:
    clean_text = normalize_persian_numbers(time_text).strip()
    if not re.match(r'^\d{1,2}:\d{2}$', clean_text):
        return False
    h, m = map(int, clean_text.split(':'))
    if 0 <= h < 24 and 0 <= m < 60:
        return True
    return False


def validate_card_or_sheba(text: str) -> bool:
    clean_text = normalize_persian_numbers(text).strip().replace(" ", "").upper()
    if clean_text.isdigit() and len(clean_text) == 16:
        return True
    if clean_text.startswith("IR") and len(clean_text) == 26 and clean_text[2:].isdigit():
        return True
    if clean_text.isdigit() and len(clean_text) == 24:
        return True
    return False


class Form(StatesGroup):
    waiting_for_phone = State()
    waiting_for_leave_type = State()    
    waiting_for_leave_start_date = State()   
    waiting_for_leave_end_date = State()    
    waiting_for_hourly_date = State()
    waiting_for_hourly_times = State()
    waiting_for_replacement = State()
    waiting_for_leave_preview = State()
    
    waiting_for_advance_amount = State()
    waiting_for_advance_card = State()
    waiting_for_advance_reason = State()
    waiting_for_advance_preview = State()

    waiting_for_mission_city = State()  
    waiting_for_mission_start_date = State()
    waiting_for_mission_end_date = State()
    waiting_for_mission_preview = State()

    waiting_for_petty_photo = State()
    waiting_for_petty_amount = State()
    waiting_for_petty_desc = State()
    waiting_for_petty_preview = State()
    
    asset_car_code = State()
    asset_car_plate = State()
    asset_car_type = State()
    asset_car_km = State()
    asset_car_desc = State()
    asset_car_preview = State()
    
    asset_fuel_code = State()
    asset_fuel_pass = State()
    asset_fuel_l1500 = State()
    asset_fuel_l3000 = State()
    asset_fuel_l10000 = State()
    asset_fuel_preview = State()
    
    asset_pos_code = State()
    asset_pos_bank = State()
    asset_pos_charger = State()
    asset_pos_preview = State()
    
    asset_printer_code = State()
    asset_printer_charger = State()
    asset_printer_preview = State()

    return_asset_id = State()
    return_asset_desc = State()
    return_asset_preview = State()

    purch_item_name = State()
    purch_qty = State()
    purch_desc = State()
    purch_preview = State()

    interactive_reminder_type = State()
    interactive_reminder_date = State()
    interactive_reminder_time = State()
    interactive_reminder_text = State()


class AdminForm(StatesGroup):
    add_staff_name = State()
    add_staff_phone = State()
    add_staff_role = State()
    add_staff_balance = State()
    add_staff_date = State()
    
    edit_staff_select = State()
    edit_staff_field = State()
    edit_staff_value = State()

    edit_asset_details = State()

    admin_asset_type = State()
    admin_asgn_substep = State()
    admin_asgn_temp_code = State()
    admin_asgn_temp_plate = State()
    admin_asgn_temp_type = State()
    admin_asgn_temp_km = State()
    admin_asgn_temp_desc = State()
    
    admin_asgn_temp_fcode = State()
    admin_asgn_temp_fpass = State()
    admin_asgn_temp_l1500 = State()
    admin_asgn_temp_l3000 = State()
    admin_asgn_temp_l10000 = State()
    
    admin_asgn_temp_pcode = State()
    admin_asgn_temp_pbank = State()
    admin_asgn_temp_pcharger = State()
    
    admin_asgn_temp_prcode = State()
    admin_asgn_temp_prcharger = State()
    
    ins_car_code = State()
    ins_car_name = State()
    ins_plate = State()
    ins_company = State()
    ins_third = State()
    ins_body = State()
    
    holiday_date = State()
    holiday_desc = State()

    rejection_reason = State()
    confirm_reset = State()


def cancel_kb(back_callback="back_to_main"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ انصراف و لغو فرم", callback_data=back_callback)]
    ])


STRICT_PREFIXES = ("admin_add_staff", "admin_edit_staff_list", "admin_deactivate_staff_list", "admin_selective_reset_menu", "confreset_", "doreset_", "admin_get_backup")


ADMIN_PREFIXES = ("admin_", "adm_", "xcl_", "deact_", "edfield_", "edrole_", "editstaff_", "asgn", "add_holiday", "delhol_", "inselcar_", "confirmasset_", "retasset_", "role_")


class AdminGuard(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if isinstance(event, CallbackQuery):
            d = event.data or ""
            if not is_active_staff(event.from_user.id):
                await event.answer("حساب پرسنلی فعال و متصل لازم است.", show_alert=True)
                return
            user_id = event.from_user.id
            if any(d.startswith(p) for p in STRICT_PREFIXES):
                if not check_user_role(user_id, "main_admin"):
                    await event.answer("❌ دسترسی غیرمجاز! فقط مدیر اصلی مجاز به این عملیات است.", show_alert=True)
                    return
            elif any(d.startswith(p) for p in ADMIN_PREFIXES) and not d.startswith("confirmasset_") and not d.startswith("retasset_") and not d.startswith("inselcar_"):
                if not is_any_admin(user_id):
                    await event.answer("❌ دسترسی غیرمجاز!", show_alert=True)
                    return
        return await handler(event, data)


async def show_main_menu(message: Message, staff_name, balance, role):
    # Compatibility facade; current account data is read from the server.
    from ..services.navigation import active_account
    from ..handlers.navigation import show_main_menu as render_menu
    with get_connection() as conn:
        account = active_account(conn, message.from_user.id)
    await render_menu(message, account)


async def send_request_to_admin(message_obj, telegram_user_id, user_name, req_type, col1, col2, col3, location_val, amount=0, sensitive_data=None, start_date=None, end_date=None, photo_id=None, replacement_staff_id=None):
    from ..handlers.request_delivery import create_submitter
    submit = create_submitter(get_connection, bot, GROUP_ID, {
        "مرخصی": TOPIC_LEAVE, "مساعده": TOPIC_ADVANCE, "ماموریت": TOPIC_MISSION,
        "تنخواه": TOPIC_PETTY, "خرید ملزومات": TOPIC_PURCHASE,
        "تحویل اموال": TOPIC_ASSETS, "عودت اموال": TOPIC_ASSETS,
    }, get_current_tehran_time)
    return await submit(message_obj, telegram_user_id, user_name, req_type, col1, col2,
                        col3, location_val, amount, sensitive_data, start_date,
                        end_date, photo_id, replacement_staff_id)







__all__ = [k for k in globals() if not k.startswith("__")]
