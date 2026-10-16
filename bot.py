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

# ---------------------------------------------------------
# تنظیمات کلید رمزنگاری اطلاعات حساس (Fernet)
# ---------------------------------------------------------
ENCRYPTION_KEY_PATH = "/data/secret.key" if os.path.exists("/data") else "secret.key"
if not os.path.exists(ENCRYPTION_KEY_PATH):
    key = Fernet.generate_key()
    with open(ENCRYPTION_KEY_PATH, "wb") as key_file:
        key_file.write(key)

with open(ENCRYPTION_KEY_PATH, "rb") as key_file:
    _FERNET_KEY = key_file.read()
cipher_suite = Fernet(_FERNET_KEY)

def encrypt_data(plain_text: str) -> str:
    if not plain_text:
        return ""
    return cipher_suite.encrypt(plain_text.encode("utf-8")).decode("utf-8")

def decrypt_data(encrypted_text: str) -> str:
    if not encrypted_text:
        return ""
    try:
        return cipher_suite.decrypt(encrypted_text.encode("utf-8")).decode("utf-8")
    except Exception:
        return encrypted_text

# ---------------------------------------------------------
# تنظیمات لاگینگ و ثبت خطاهای سرور
# ---------------------------------------------------------
logging.basicConfig(
    filename='bot_errors.log',
    level=logging.ERROR,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("❌ خطای امنیتی بحرانی: متغیر محیطی BOT_TOKEN بر روی سرور تنظیم نشده است!")

GROUP_ID = int(os.getenv("GROUP_ID", "-1003619551361"))

DB_DIR = "/data" if os.path.exists("/data") else "."
DB_PATH = os.path.join(DB_DIR, "enterprise_requests.db")

TEHRAN_TZ = pytz.timezone('Asia/Tehran')

def get_current_tehran_time():
    now_utc = datetime.now(pytz.utc)
    now_tehran = now_utc.astimezone(TEHRAN_TZ)
    return jdatetime.datetime.fromgregorian(datetime=now_tehran)

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

bot = Bot(token=TOKEN)
dp = Dispatcher()

def normalize_persian_numbers(text: str) -> str:
    if not text:
        return ""
    trans = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
    return text.translate(trans)

def normalize_jalali_date(date_text: str) -> str:
    clean = normalize_persian_numbers(date_text).strip().replace("-", "/")
    parts = clean.split("/")
    if len(parts) == 3:
        try:
            y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
            return f"{y:04d}/{m:02d}/{d:02d}"
        except Exception:
            pass
    return clean

@contextmanager
def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        
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

        # اسکریپت مهاجرت دیتابیس‌های قدیمی (ALTER TABLE)
        tables_columns = {
            "requests": [("sensitive_data", "TEXT"), ("amount", "INTEGER DEFAULT 0"), ("start_date", "TEXT"), ("end_date", "TEXT"), ("location", "TEXT"), ("month_tag", "TEXT"), ("rejection_reason", "TEXT"), ("admin_msg_id", "INTEGER"), ("admin_chat_id", "INTEGER")],
            "staff_mapping": [("leave_balance", "REAL DEFAULT 0.0"), ("role", "TEXT DEFAULT 'staff'"), ("employment_date", "TEXT"), ("deactivation_date", "TEXT")],
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
        
        for sname, phone, role, emp_date in INITIAL_STAFF_SEED:
            cursor.execute("""
                INSERT OR IGNORE INTO staff_mapping (staff_name, phone_number, is_active, leave_balance, role, employment_date) 
                VALUES (?, ?, 1, 0.0, ?, ?)
            """, (sname, phone, role, emp_date))
            cursor.execute("""
                UPDATE staff_mapping SET phone_number = ? WHERE staff_name = ? AND (phone_number IS NULL OR phone_number = '')
            """, (phone, sname))
                
        cursor.execute("""
            UPDATE staff_mapping 
            SET telegram_user_id = 114906446, role = 'main_admin', is_active = 1 
            WHERE staff_name = 'ایمان یزدان پناه' AND (telegram_user_id IS NULL OR telegram_user_id = 114906446)
        """)
        
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
                
        conn.commit()

init_db()

def generate_req_code(req_id: int) -> str:
    year_j = get_current_tehran_time().year
    return f"REQ-{year_j}-{req_id:05d}"

def get_staff_info_by_telegram_id(telegram_user_id: int):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT staff_id, staff_name, leave_balance, phone_number, is_active, role FROM staff_mapping WHERE telegram_user_id = ?", (telegram_user_id,))
        row = cursor.fetchone()
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
    clean_text = normalize_jalali_date(date_text)
    pattern = r'^\d{4}/\d{2}/\d{2}$'
    if not re.match(pattern, clean_text):
        return False
    try:
        parts = [int(x) for x in clean_text.split('/')]
        jdatetime.date(parts[0], parts[1], parts[2])
        return True
    except Exception:
        return False

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

# ---------------------------------------------------------
# FSM States
# ---------------------------------------------------------
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

# ---------------------------------------------------------
# Admin Guard Middleware
# ---------------------------------------------------------
STRICT_PREFIXES = ("admin_add_staff", "admin_edit_staff_list", "admin_deactivate_staff_list", "admin_selective_reset_menu", "confreset_", "doreset_", "admin_get_backup")
ADMIN_PREFIXES = ("admin_", "adm_", "xcl_", "deact_", "edfield_", "edrole_", "editstaff_", "asgn", "add_holiday", "delhol_", "inselcar_", "confirmasset_", "retasset_", "role_")

class AdminGuard(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if isinstance(event, CallbackQuery):
            d = event.data or ""
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

dp.callback_query.middleware(AdminGuard())

@dp.my_chat_member(ChatMemberUpdatedFilter(member_status_changed=IS_MEMBER))
async def on_bot_added_to_chat(event: ChatMemberUpdated):
    chat_id = event.chat.id
    if chat_id != GROUP_ID:
        user = event.from_user
        if not check_user_role(user.id, "main_admin"):
            try:
                await bot.send_message(
                    chat_id=user.id,
                    text="❌ شما اجازه ندارید ربات را به گروه‌های متفرقه اضافه کنید. این ربات صرفاً توسط مدیر اصلی قابل مدیریت است."
                )
                await bot.leave_chat(chat_id=chat_id)
            except Exception as e:
                logging.error(f"Error leaving unauthorized group: {e}")

@dp.message(Command("start"))
async def cmd_start(message: Message, command: CommandObject, state: FSMContext):
    args = command.args
    if args and args.startswith("reminder_"):
        parts = args.split("_", 2)
        if len(parts) >= 3:
            target_chat = int(parts[1])
            target_thread = int(parts[2]) if parts[2] != "None" else None
            await state.update_data(remind_chat_id=target_chat, remind_thread_id=target_thread)
            
            user_id = message.from_user.id
            staff_id, staff_name, _, _, is_active, _ = get_staff_info_by_telegram_id(user_id)
            if not staff_name or is_active != 1:
                await message.answer("❌ ابتدا باید حساب پرسنلی خود را با دستور /start متصل کنید.")
                return

            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📌 یک‌بار مصرف (تاریخ مشخص)", callback_data="rem_type_once")],
                [InlineKeyboardButton(text="🔄 هفتگی (روز خاص هفته)", callback_data="rem_type_weekly")],
                [InlineKeyboardButton(text="🗓️ ماهانه (روز خاص ماه)", callback_data="rem_type_monthly")]
            ])
            await state.set_state(Form.interactive_reminder_type)
            await message.answer("⏰ <b>تنظیم هوشمند و تعاملی یادآوری در پی‌وی</b>\n\nنوع یادآوری مورد نظر خود را انتخاب کنید:", reply_markup=kb, parse_mode="HTML")
            return

    await state.clear()
    user_id = message.from_user.id
    staff_id, staff_name, balance, phone, is_active, role = get_staff_info_by_telegram_id(user_id)

    if not staff_name or is_active == 0:
        if is_active == 0 and staff_name:
            await message.answer("❌ دسترسی شما به سامانه مسدود است.")
            return

        kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="📱 تایید و اتصال خودکار حساب کاربری", request_contact=True)]],
            resize_keyboard=True,
            one_time_keyboard=True
        )
        await state.set_state(Form.waiting_for_phone)
        await message.answer("سلام! لطفاً برای اتصال امن حساب کاربری روی دکمه زیر کلیک کنید:", reply_markup=kb)
        return

    await show_main_menu(message, staff_name, balance, role)

@dp.message(Form.waiting_for_phone, F.contact)
async def process_phone_contact(message: Message, state: FSMContext):
    contact = message.contact
    user_id = message.from_user.id

    if not contact.user_id or contact.user_id != user_id:
        await message.answer("❌ خطای امنیتی: شماره تماسی که ارسال کردید متعلق به حساب تلگرام شما نیست!", reply_markup=ReplyKeyboardRemove())
        await state.clear()
        return

    phone = contact.phone_number
    clean_phone = phone.replace("+", "").strip()
    if clean_phone.startswith("98"):
        clean_phone = "0" + clean_phone[2:]

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT staff_id, staff_name, is_active FROM staff_mapping WHERE phone_number = ? OR phone_number = ? OR phone_number = ?", 
                       (phone, clean_phone, "+" + clean_phone))
        row = cursor.fetchone()

    if row:
        staff_id, staff_name, is_active = row[0], row[1], row[2]
        if is_active == 0:
            await message.answer("❌ حساب کاربری شما غیرفعال است.", reply_markup=ReplyKeyboardRemove())
            return

        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE staff_mapping SET telegram_user_id = ? WHERE staff_id = ?", (user_id, staff_id))
            conn.commit()
        
        await message.answer(f"✅ احراز هویت با موفقیت انجام شد. خوش آمدید، <b>{html.escape(staff_name)}</b>.", reply_markup=ReplyKeyboardRemove(), parse_mode="HTML")
        await state.clear()
        _, staff_name, balance, _, _, role = get_staff_info_by_telegram_id(user_id)
        await show_main_menu(message, staff_name, balance, role)
    else:
        await message.answer("⚠️ شماره شما در لیست پرسنل مجاز یافت نشد.", reply_markup=ReplyKeyboardRemove())

async def show_main_menu(message: Message, staff_name, balance, role):
    user_id = message.from_user.id
    keyboard_buttons = [
        [InlineKeyboardButton(text="📝 امور اداری و مالی (مرخصی، مساعده، ماموریت)", callback_data="menu_admin_finance")],
        [InlineKeyboardButton(text="🏢 حسابداری، اموال و خرید انبار", callback_data="menu_assets_purchase")],
        [InlineKeyboardButton(text="📊 کارنامه و پیگیری درخواست‌ها", callback_data="menu_reports_tracking")]
    ]
    if is_any_admin(user_id):
        keyboard_buttons.append([InlineKeyboardButton(text="⚙️ پنل مدیریت و گزارشات اکسل", callback_data="admin_panel")])
        keyboard_buttons.append([InlineKeyboardButton(text="📅 مرخصی‌های فعال امروز (/today)", callback_data="admin_today")])

    kb = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    status_text = f"👤 پرسنل: <b>{html.escape(staff_name)}</b> | 🌿 مانده مرخصی: <code>{balance} روز</code>"
    await message.answer(f"سامانه جامع مدیریت پرسنلی\n{status_text}\n\nبخش مورد نظر را انتخاب کنید:", reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data == "menu_admin_finance")
async def sub_menu_admin_finance(callback: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏳ درخواست مرخصی", callback_data="req_leave")],
        [InlineKeyboardButton(text="💵 درخواست مساعده", callback_data="req_advance")],
        [InlineKeyboardButton(text="📍 ثبت گزارش ماموریت", callback_data="req_mission")],
        [InlineKeyboardButton(text="🔙 بازگشت به منوی اصلی", callback_data="back_to_main")]
    ])
    await callback.message.edit_text("📝 <b>امور اداری و مالی</b>", reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "menu_assets_purchase")
async def sub_menu_assets_purchase(callback: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧾 ثبت فاکتور تنخواه", callback_data="req_petty")],
        [InlineKeyboardButton(text="🚗 تحویل اموال", callback_data="req_asset")],
        [InlineKeyboardButton(text="🔄 عودت اموال", callback_data="req_return_asset")],
        [InlineKeyboardButton(text="🛒 خرید ملزومات / انبار", callback_data="req_purchase")],
        [InlineKeyboardButton(text="🔙 بازگشت به منوی اصلی", callback_data="back_to_main")]
    ])
    await callback.message.edit_text("🏢 <b>حسابداری، اموال و خرید انبار</b>", reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "menu_reports_tracking")
async def sub_menu_reports_tracking(callback: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 وضعیت من (آمار ماه جاری)", callback_data="my_stats")],
        [InlineKeyboardButton(text="📥 دریافت گزارش اکسل عملکرد من", callback_data="my_excel_report")],
        [InlineKeyboardButton(text="📋 پیگیری و لغو درخواست‌ها", callback_data="my_requests")],
        [InlineKeyboardButton(text="🔙 بازگشت به منوی اصلی", callback_data="back_to_main")]
    ])
    await callback.message.edit_text("📊 <b>کارنامه و پیگیری درخواست‌ها</b>", reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "back_to_main")
async def back_to_main_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = callback.from_user.id
    _, staff_name, balance, _, _, role = get_staff_info_by_telegram_id(user_id)
    
    keyboard_buttons = [
        [InlineKeyboardButton(text="📝 امور اداری و مالی (مرخصی، مساعده، ماموریت)", callback_data="menu_admin_finance")],
        [InlineKeyboardButton(text="🏢 حسابداری، اموال و خرید انبار", callback_data="menu_assets_purchase")],
        [InlineKeyboardButton(text="📊 کارنامه و پیگیری درخواست‌ها", callback_data="menu_reports_tracking")]
    ]
    if is_any_admin(user_id):
        keyboard_buttons.append([InlineKeyboardButton(text="⚙️ پنل مدیریت و گزارشات اکسل", callback_data="admin_panel")])
        keyboard_buttons.append([InlineKeyboardButton(text="📅 مرخصی‌های فعال امروز (/today)", callback_data="admin_today")])

    kb = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    status_text = f"👤 پرسنل: <b>{html.escape(staff_name)}</b> | 🌿 مانده مرخصی: <code>{balance} روز</code>"
    
    try:
        await callback.message.edit_text(f"سامانه جامع مدیریت پرسنلی\n{status_text}\n\nبخش مورد نظر را انتخاب کنید:", reply_markup=kb, parse_mode="HTML")
    except Exception:
        await callback.message.answer(f"سامانه جامع مدیریت پرسنلی\n{status_text}\n\nبخش مورد نظر را انتخاب کنید:", reply_markup=kb, parse_mode="HTML")
    
    await callback.answer()

@dp.message(F.text.contains("#یادآوری"))
async def handle_group_reminder(message: Message, state: FSMContext):
    if message.chat.type not in ("group", "supergroup"):
        await message.answer("⚠️ دستور یادآوری باید در گروه‌های کاری استفاده شود.")
        return

    user_id = message.from_user.id
    _, staff_name, _, _, is_active, _ = get_staff_info_by_telegram_id(user_id)
    if not staff_name or is_active != 1:
        await message.reply("❌ شما هنوز در سامانه احراز هویت نکرده‌اید یا حساب شما فعال نیست.")
        return

    text = message.text.strip()
    chat_id = message.chat.id
    thread_id = message.message_thread_id if hasattr(message, "message_thread_id") else None

    if text == "#یادآوری":
        bot_info = await bot.get_me()
        payload = f"reminder_{chat_id}_{thread_id if thread_id else 'None'}"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🤖 تنظیم تعاملی یادآوری در پی‌وی", url=f"https://t.me/{bot_info.username}?start={payload}")]
        ])
        await message.reply("⏰ برای تنظیم تعاملی یادآوری در این تاپیک/گروه، روی دکمه زیر کلیک کنید:", reply_markup=kb)
        return

    now_j = get_current_tehran_time()

    weekly_match_fa = re.search(r"#یادآوری\s+هر\s+(شنبه|یکشنبه|دوشنبه|سه‌شنبه|چهارشنبه|پنج‌شنبه|جمعه)\s+(?:ساعت\s+)?(\d{1,2}:\d{2})\s+(.+)", text, re.DOTALL)
    if weekly_match_fa:
        persian_day, time_str, content = weekly_match_fa.groups()
        time_str = normalize_persian_numbers(time_str)
        if not validate_time_str(time_str):
            await message.reply("❌ ساعت وارد شده نامعتبر است.")
            return
        h, m = time_str.split(":")
        time_str = f"{int(h):02d}:{int(m):02d}"
        day_map = {
            "شنبه": "Saturday", "یکشنبه": "Sunday", "دوشنبه": "Monday",
            "سه‌شنبه": "Tuesday", "چهارشنبه": "Wednesday", "پنج‌شنبه": "Thursday", "جمعه": "Friday"
        }
        eng_day = day_map.get(persian_day)
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO reminders (chat_id, message_thread_id, telegram_user_id, user_name, remind_type, day_of_week, remind_time, text_content, is_sent)
                VALUES (?, ?, ?, ?, 'weekly', ?, ?, ?, 0)
            """, (chat_id, thread_id, user_id, staff_name, eng_day, time_str, content))
            conn.commit()
        await message.reply(f"✅ یادآوری هفتگی ثبت شد:\n📅 هر <b>{persian_day}</b> ساعت <b>{time_str}</b>", parse_mode="HTML")
        return

    monthly_match_fa = re.search(r"#یادآوری\s+روز\s+(اول|یک|\d{1,2})\s+هر\s+ماه\s+(?:ساعت\s+)?(\d{1,2}:\d{2})\s+(.+)", text, re.DOTALL)
    if monthly_match_fa:
        day_raw, time_str, content = monthly_match_fa.groups()
        time_str = normalize_persian_numbers(time_str)
        if not validate_time_str(time_str):
            await message.reply("❌ ساعت وارد شده نامعتبر است.")
            return
        h, m = time_str.split(":")
        time_str = f"{int(h):02d}:{int(m):02d}"
        day_num = 1 if day_raw in ("اول", "یک") else int(normalize_persian_numbers(day_raw))
        if not (1 <= day_num <= 31):
            await message.reply("❌ روز ماه نامعتبر است.")
            return
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO reminders (chat_id, message_thread_id, telegram_user_id, user_name, remind_type, day_of_month, remind_time, text_content, is_sent)
                VALUES (?, ?, ?, ?, 'monthly', ?, ?, ?, 0)
            """, (chat_id, thread_id, user_id, staff_name, day_num, time_str, content))
            conn.commit()
        await message.reply(f"✅ یادآوری ماهانه ثبت شد:\n📅 روز <b>{day_num}</b> هر ماه ساعت <b>{time_str}</b>", parse_mode="HTML")
        return

    nat_match = re.search(r"#یادآوری\s+(فردا|پس‌فردا|امروز)\s+(?:ساعت\s+)?(\d{1,2}:\d{2})\s+(.+)", text, re.DOTALL)
    if nat_match:
        day_keyword, time_str, content = nat_match.groups()
        time_str = normalize_persian_numbers(time_str)
        if not validate_time_str(time_str):
            await message.reply("❌ ساعت وارد شده نامعتبر است.")
            return
        h, m = time_str.split(":")
        time_str = f"{int(h):02d}:{int(m):02d}"
        target_date_j = now_j.date()
        if day_keyword == "فردا":
            target_date_j += jdatetime.timedelta(days=1)
        elif day_keyword == "پس‌فردا":
            target_date_j += jdatetime.timedelta(days=2)
        
        date_str = target_date_j.strftime("%Y/%m/%d")
        remind_datetime_str = f"{date_str} {time_str}"
        
        # بررسی زمان آینده
        if remind_datetime_str <= now_j.strftime("%Y/%m/%d %H:%M"):
            await message.reply("❌ زمان یادآوری نمی‌تواند در گذشته باشد.")
            return

        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO reminders (chat_id, message_thread_id, telegram_user_id, user_name, remind_type, remind_at, text_content, is_sent)
                VALUES (?, ?, ?, ?, 'once', ?, ?, 0)
            """, (chat_id, thread_id, user_id, staff_name, remind_datetime_str, content))
            conn.commit()
        await message.reply(f"✅ یادآوری برای <b>{day_keyword}</b> ({date_str}) ساعت <b>{time_str}</b> ثبت شد.", parse_mode="HTML")
        return

    once_pattern = r"#یادآوری\s+(\d{4}/\d{1,2}/\d{1,2})\s+(\d{1,2}:\d{2})\s+(.+)"
    once_match = re.match(once_pattern, text, re.DOTALL)
    if once_match:
        date_str, time_str, content = once_match.groups()
        date_str = normalize_jalali_date(date_str)
        time_str = normalize_persian_numbers(time_str)
        if not validate_custom_date(date_str) or not validate_time_str(time_str):
            await message.reply("❌ تاریخ یا ساعت وارد شده نامعتبر است.")
            return
        h, m = time_str.split(":")
        time_str = f"{int(h):02d}:{int(m):02d}"
        remind_datetime_str = f"{date_str} {time_str}"
        
        if remind_datetime_str <= now_j.strftime("%Y/%m/%d %H:%M"):
            await message.reply("❌ زمان یادآوری نمی‌تواند در گذشته باشد.")
            return

        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO reminders (chat_id, message_thread_id, telegram_user_id, user_name, remind_type, remind_at, text_content, is_sent)
                VALUES (?, ?, ?, ?, 'once', ?, ?, 0)
            """, (chat_id, thread_id, user_id, staff_name, remind_datetime_str, content))
            conn.commit()
        await message.reply(f"✅ یادآوری برای تاریخ <b>{date_str}</b> ساعت <b>{time_str}</b> ثبت شد.", parse_mode="HTML")
        return

    await message.reply("❌ فرمت یادآوری نامعتبر است. نمونه صحیح:\n<code>#یادآوری فردا ساعت ۱۰:۳۰ جلسه</code>", parse_mode="HTML")

@dp.callback_query(F.data.startswith("rem_type_"))
async def process_reminder_type_selected(callback: CallbackQuery, state: FSMContext):
    rtype = callback.data.split("rem_type_")[1]
    await state.update_data(rem_type=rtype)
    
    if rtype == "once":
        await state.set_state(Form.interactive_reminder_date)
        await callback.message.edit_text("📅 <b>مرحله ۱ از ۳:</b> تاریخ یادآوری را وارد کنید (<code>YYYY/MM/DD</code> یا مثلاً <code>فردا</code> / <code>پس‌فردا</code>):", parse_mode="HTML")
    elif rtype == "weekly":
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="شنبه", callback_data="remday_Saturday"), InlineKeyboardButton(text="یکشنبه", callback_data="remday_Sunday")],
            [InlineKeyboardButton(text="دوشنبه", callback_data="remday_Monday"), InlineKeyboardButton(text="سه‌شنبه", callback_data="remday_Tuesday")],
            [InlineKeyboardButton(text="چهارشنبه", callback_data="remday_Wednesday"), InlineKeyboardButton(text="پنج‌شنبه", callback_data="remday_Thursday")],
            [InlineKeyboardButton(text="جمعه", callback_data="remday_Friday")]
        ])
        await state.set_state(Form.interactive_reminder_date)
        await callback.message.edit_text("📅 <b>مرحله ۱ از ۳:</b> روز هفته را انتخاب کنید:", reply_markup=kb, parse_mode="HTML")
    elif rtype == "monthly":
        await state.set_state(Form.interactive_reminder_date)
        await callback.message.edit_text("📅 <b>مرحله ۱ از ۳:</b> شماره روز ماه را وارد کنید (مثلاً ۱ یا ۱۵):", parse_mode="HTML")
    await callback.answer()

@dp.message(Form.interactive_reminder_date)
async def process_reminder_date_text(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ لطفاً متن معتبر ارسال کنید.")
        return
    data = await state.get_data()
    rtype = data.get("rem_type")
    text = normalize_persian_numbers(message.text).strip()

    if rtype == "once":
        now_j = get_current_tehran_time()
        if text == "فردا":
            target_date = (now_j + jdatetime.timedelta(days=1)).strftime("%Y/%m/%d")
        elif text == "پس‌فردا":
            target_date = (now_j + jdatetime.timedelta(days=2)).strftime("%Y/%m/%d")
        elif validate_custom_date(text):
            target_date = normalize_jalali_date(text)
        else:
            await message.answer("❌ تاریخ نامعتبر است.")
            return
        await state.update_data(rem_date=target_date)
    elif rtype == "monthly":
        if not text.isdigit() or not (1 <= int(text) <= 31):
            await message.answer("❌ روز ماه باید عددی بین ۱ تا ۳۱ باشد.")
            return
        await state.update_data(rem_date=int(text))
    elif rtype == "weekly":
        valid_days = {"Saturday", "Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday"}
        if text not in valid_days:
            await message.answer("❌ روز هفته نامعتبر است.")
            return
        await state.update_data(rem_date=text)

    await state.set_state(Form.interactive_reminder_time)
    await message.answer("⏰ <b>مرحله ۲ از ۳:</b> ساعت یادآوری را وارد کنید (مثلاً 09:30):", parse_mode="HTML")

@dp.callback_query(Form.interactive_reminder_date, F.data.startswith("remday_"))
async def process_reminder_date_callback(callback: CallbackQuery, state: FSMContext):
    day_eng = callback.data.split("remday_")[1]
    await state.update_data(rem_date=day_eng)
    await state.set_state(Form.interactive_reminder_time)
    await callback.message.edit_text("⏰ <b>مرحله ۲ از ۳:</b> ساعت یادآوری را وارد کنید (مثلاً 09:30):", parse_mode="HTML")
    await callback.answer()

@dp.message(Form.interactive_reminder_time)
async def process_reminder_time_selected(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ لطفاً ساعت معتبر ارسال کنید.")
        return
    time_str = normalize_persian_numbers(message.text).strip()
    if not validate_time_str(time_str):
        await message.answer("❌ فرمت ساعت نامعتبر است (مثال: 08:30):")
        return
    h, m = time_str.split(":")
    formatted_time = f"{int(h):02d}:{int(m):02d}"
    await state.update_data(rem_time=formatted_time)
    await state.set_state(Form.interactive_reminder_text)
    await message.answer("📝 <b>مرحله ۳ از ۳:</b> متن یا عنوان یادآوری را بنویسید:", parse_mode="HTML")

@dp.message(Form.interactive_reminder_text)
async def process_reminder_text_final(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ لطفاً متن معتبر ارسال کنید.")
        return
    content = message.text.strip()
    data = await state.get_data()
    rtype = data.get("rem_type")
    rdate = data.get("rem_date")
    rtime = data.get("rem_time")
    
    user_id = message.from_user.id
    _, staff_name, _, _, _, _ = get_staff_info_by_telegram_id(user_id)
    chat_id = data.get("remind_chat_id", GROUP_ID)
    thread_id = data.get("remind_thread_id", None)

    with get_connection() as conn:
        cursor = conn.cursor()
        if rtype == "once":
            remind_datetime_str = f"{rdate} {rtime}"
            if remind_datetime_str <= get_current_tehran_time().strftime("%Y/%m/%d %H:%M"):
                await message.answer("❌ زمان یادآوری نمی‌تواند در گذشته باشد.")
                return
            cursor.execute("""
                INSERT INTO reminders (chat_id, message_thread_id, telegram_user_id, user_name, remind_type, remind_at, text_content, is_sent)
                VALUES (?, ?, ?, ?, 'once', ?, ?, 0)
            """, (chat_id, thread_id, user_id, staff_name, remind_datetime_str, content))
            await message.answer(f"✅ یادآوری برای تاریخ <b>{rdate}</b> ساعت <b>{rtime}</b> ثبت گردید.", parse_mode="HTML")
        elif rtype == "weekly":
            cursor.execute("""
                INSERT INTO reminders (chat_id, message_thread_id, telegram_user_id, user_name, remind_type, day_of_week, remind_time, text_content, is_sent)
                VALUES (?, ?, ?, ?, 'weekly', ?, ?, ?, 0)
            """, (chat_id, thread_id, user_id, staff_name, rdate, rtime, content))
            await message.answer(f"✅ یادآوری هفتگی برای ساعت <b>{rtime}</b> ثبت گردید.", parse_mode="HTML")
        elif rtype == "monthly":
            cursor.execute("""
                INSERT INTO reminders (chat_id, message_thread_id, telegram_user_id, user_name, remind_type, day_of_month, remind_time, text_content, is_sent)
                VALUES (?, ?, ?, ?, 'monthly', ?, ?, ?, 0)
            """, (chat_id, thread_id, user_id, staff_name, rdate, rtime, content))
            await message.answer(f"✅ یادآوری ماهانه برای روز <b>{rdate}</b> ساعت <b>{rtime}</b> ثبت گردید.", parse_mode="HTML")
        conn.commit()

    await state.clear()

async def reminder_scheduler():
    last_checked_minute = ""
    while True:
        try:
            await asyncio.sleep(15)
            now_tehran = get_current_tehran_time()
            current_date_str = now_tehran.strftime("%Y/%m/%d")
            current_time_str = now_tehran.strftime("%H:%M")
            current_full_str = f"{current_date_str} {current_time_str}"
            current_eng_day = now_tehran.togregorian().strftime("%A")
            current_day_of_month = now_tehran.day

            if current_full_str == last_checked_minute:
                continue

            with get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute("SELECT id, chat_id, message_thread_id, user_name, text_content FROM reminders WHERE remind_type = 'once' AND is_sent = 0 AND remind_at <= ?", (current_full_str,))
                for rem in cursor.fetchall():
                    rem_id, chat_id, thread_id, user_name, content = rem
                    msg = f"🔔 <b>یادآوری ثبت‌شده</b>\n\n👤 ثبت‌کننده: <b>{html.escape(user_name)}</b>\n📝 {html.escape(content)}"
                    try:
                        if thread_id and thread_id != "None":
                            await bot.send_message(chat_id=chat_id, message_thread_id=int(thread_id), text=msg, parse_mode="HTML")
                        else:
                            await bot.send_message(chat_id=chat_id, text=msg, parse_mode="HTML")
                    except Exception as e:
                        logging.error(f"Reminder error {rem_id}: {e}")
                    cursor.execute("UPDATE reminders SET is_sent = 1 WHERE id = ?", (rem_id,))
                    conn.commit()

                cursor.execute("SELECT id, chat_id, message_thread_id, user_name, text_content, last_fired FROM reminders WHERE remind_type = 'weekly' AND day_of_week = ? AND remind_time = ?", (current_eng_day, current_time_str))
                for rem in cursor.fetchall():
                    rem_id, chat_id, thread_id, user_name, content, last_fired = rem
                    if last_fired == current_date_str:
                        continue
                    msg = f"🔄 <b>یادآوری هفتگی</b>\n\n👤 ثبت‌کننده: <b>{html.escape(user_name)}</b>\n📝 {html.escape(content)}"
                    try:
                        if thread_id and thread_id != "None":
                            await bot.send_message(chat_id=chat_id, message_thread_id=int(thread_id), text=msg, parse_mode="HTML")
                        else:
                            await bot.send_message(chat_id=chat_id, text=msg, parse_mode="HTML")
                        cursor.execute("UPDATE reminders SET last_fired = ? WHERE id = ?", (current_date_str, rem_id))
                        conn.commit()
                    except Exception as e:
                        logging.error(f"Weekly reminder error {rem_id}: {e}")

                # محاسبه صحیح طول ماه در تقویم جلالی برای یادآورهای ماهانه
                j_year, j_month = now_tehran.year, now_tehran.month
                if j_month <= 6:
                    max_days = 31
                elif j_month <= 11:
                    max_days = 30
                else:
                    max_days = 30 if jdatetime.date.isleap(j_year) else 29

                target_days = [current_day_of_month]
                if current_day_of_month >= max_days:
                    target_days = list(range(current_day_of_month, 32))

                placeholders = ','.join(['?'] * len(target_days))
                query = f"SELECT id, chat_id, message_thread_id, user_name, text_content, last_fired FROM reminders WHERE remind_type = 'monthly' AND day_of_month IN ({placeholders}) AND remind_time = ?"
                cursor.execute(query, target_days + [current_time_str])
                
                for rem in cursor.fetchall():
                    rem_id, chat_id, thread_id, user_name, content, last_fired = rem
                    if last_fired == current_date_str:
                        continue
                    msg = f"🔄 <b>یادآوری ماهانه</b>\n\n👤 ثبت‌کننده: <b>{html.escape(user_name)}</b>\n📝 {html.escape(content)}"
                    try:
                        if thread_id and thread_id != "None":
                            await bot.send_message(chat_id=chat_id, message_thread_id=int(thread_id), text=msg, parse_mode="HTML")
                        else:
                            await bot.send_message(chat_id=chat_id, text=msg, parse_mode="HTML")
                        cursor.execute("UPDATE reminders SET last_fired = ? WHERE id = ?", (current_date_str, rem_id))
                        conn.commit()
                    except Exception as e:
                        logging.error(f"Monthly reminder error {rem_id}: {e}")

            last_checked_minute = current_full_str
        except Exception as e:
            logging.error(f"Reminder Scheduler Error: {e}")

async def send_request_to_admin(message_obj, telegram_user_id, user_name, req_type, col1, col2, col3, location_val, amount=0, sensitive_data=None, start_date=None, end_date=None, photo_id=None, replacement_staff_id=None):
    now_j = get_current_tehran_time()
    created_at = now_j.strftime("%Y/%m/%d %H:%M")
    month_tag = now_j.strftime("%Y/%m")
    
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO requests (telegram_user_id, user_name, telegram_info, request_type, col1, col2, col3, sensitive_data, amount, start_date, end_date, location, status, created_at, month_tag) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (telegram_user_id, user_name, message_obj.from_user.full_name, req_type, col1, col2, col3, sensitive_data, amount, start_date, end_date, location_val, "⏳ در انتظار تأیید نهایی مدیریت", created_at, month_tag))
        req_id = cursor.lastrowid
        req_code = generate_req_code(req_id)
        cursor.execute("UPDATE requests SET req_code = ? WHERE id = ?", (req_code, req_id))
        conn.commit()

    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ تأیید نهایی", callback_data=f"approve_{req_id}"),
         InlineKeyboardButton(text="❌ رد (با دلیل)", callback_data=f"reject_{req_id}")]
    ])

    text = f"📩 <b>درخواست {html.escape(req_type)} ({req_code})</b>\n\n👤 پرسنل: {html.escape(user_name)}\n📌 {html.escape(col1)}\n📌 {html.escape(col2)}\n📌 {html.escape(col3)}\n📅 ثبت: {created_at}\nوضعیت: ⏳ در انتظار تأیید نهایی مدیریت"
    
    try:
        if photo_id:
            sent_msg = await bot.send_photo(chat_id=GROUP_ID, message_thread_id=TOPIC_PETTY, photo=photo_id, caption=text, reply_markup=admin_kb, parse_mode="HTML")
        else:
            thread_map = {
                "مرخصی": TOPIC_LEAVE,
                "مساعده": TOPIC_ADVANCE,
                "ماموریت": TOPIC_MISSION,
                "تنخواه": TOPIC_PETTY,
                "خرید ملزومات": TOPIC_PURCHASE,
                "تحویل اموال": TOPIC_ASSETS,
                "عودت اموال": TOPIC_ASSETS
            }
            t_id = thread_map.get(req_type, GROUP_ID)
            sent_msg = await bot.send_message(chat_id=GROUP_ID, message_thread_id=t_id, text=text, reply_markup=admin_kb, parse_mode="HTML")
        
        if sent_msg:
            with get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("UPDATE requests SET admin_msg_id = ?, admin_chat_id = ? WHERE id = ?", (sent_msg.message_id, sent_msg.chat.id, req_id))
                conn.commit()

        target_msg = message_obj if isinstance(message_obj, Message) else message_obj.message
        await target_msg.answer(f"✅ درخواست {req_type} شما ({req_code}) ثبت و برای تأیید مدیریت ارسال شد.")
    except Exception as e:
        logging.error(f"Send to admin error: {e}")
        target_msg = message_obj if isinstance(message_obj, Message) else message_obj.message
        await target_msg.answer(f"✅ درخواست شما ثبت شد اما در ارسال به کانال گروه خطایی رخ داد.")

    if replacement_staff_id:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT telegram_user_id, staff_name FROM staff_mapping WHERE staff_id = ? AND is_active = 1", (replacement_staff_id,))
            repl_row = cursor.fetchone()
        if repl_row and repl_row[0]:
            repl_uid, repl_name = repl_row[0], repl_row[1]
            repl_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ تأیید جانشینی", callback_data=f"replapp_{req_id}"),
                 InlineKeyboardButton(text="❌ عدم تأیید جانشینی", callback_data=f"replrej_{req_id}")]
            ])
            repl_text = f"🔄 <b>درخواست جانشینی در مرخصی</b>\n\nهمکار گرامی <b>{html.escape(repl_name)}</b>،\nهمکار شما <b>{html.escape(user_name)}</b> در درخواست مرخصی خود ({req_code}) شما را به عنوان <b>فرد جایگزین</b> معرفی نموده است.\n\n📌 <b>مشخصات مرخصی:</b>\n{html.escape(col1)}\n{html.escape(col2)}\n\nآیا جانشینی ایشان را تأیید می‌کنید؟"
            try:
                await bot.send_message(chat_id=repl_uid, text=repl_text, reply_markup=repl_kb, parse_mode="HTML")
            except Exception as e:
                logging.error(f"Replacement msg error: {e}")

@dp.callback_query(F.data.startswith("replapp_") | F.data.startswith("replrej_"))
async def process_replacement_response(callback: CallbackQuery):
    action, _, raw_req_id = callback.data.partition("_")
    req_id = int(raw_req_id)
    is_approved = (action == "replapp")

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT req_code, user_name, col1, col2, col3, admin_msg_id, admin_chat_id, status FROM requests WHERE id = ?", (req_id,))
        row = cursor.fetchone()

    if not row:
        await callback.answer("درخواست یافت نشد.", show_alert=True)
        return

    req_code, user_name, col1, col2, col3, admin_msg_id, admin_chat_id, status = row
    if "تأیید شده" in status or "رد شده" in status:
        await callback.answer("این درخواست قبلاً تعیین تکلیف شده است.", show_alert=True)
        return

    # بررسی سخت‌گیرانه مالکیت جانشین
    user_id = callback.from_user.id
    staff_id, repl_user_name, _, _, _, _ = get_staff_info_by_telegram_id(user_id)
    
    status_tag = f"تأیید شده توسط جانشین ({repl_user_name}) ✅" if is_approved else f"رد شده توسط جانشین ({repl_user_name}) ❌"
    
    if "وضعیت جانشین:" in col3:
        base_col3 = col3.split("| وضعیت جانشین:")[0]
        new_col3 = f"{base_col3} | وضعیت جانشین: {status_tag}"
    else:
        new_col3 = f"{col3} | وضعیت جانشین: {status_tag}"

    with get_connection() as conn:
        cursor = conn.cursor()
        if not is_approved:
            cursor.execute("UPDATE requests SET col3 = ?, status = '❌ رد شده توسط جانشین' WHERE id = ?", (new_col3, req_id))
        else:
            cursor.execute("UPDATE requests SET col3 = ? WHERE id = ?", (new_col3, req_id))
        conn.commit()

    try:
        await callback.message.edit_text(callback.message.text + f"\n\n<b>پاسخ شما ثبت شد:</b> {status_tag}", reply_markup=None, parse_mode="HTML")
    except Exception:
        pass
    await callback.answer("پاسخ شما با موفقیت ثبت شد.")

    if admin_msg_id and admin_chat_id:
        try:
            admin_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ تأیید نهایی", callback_data=f"approve_{req_id}"),
                 InlineKeyboardButton(text="❌ رد (با دلیل)", callback_data=f"reject_{req_id}")]
            ])
            updated_status_str = "❌ رد شده به دلیل عدم تایید جانشین" if not is_approved else "⏳ در انتظار تأیید نهایی مدیریت"
            updated_admin_text = f"📩 <b>درخواست مرخصی ({req_code})</b>\n\n👤 پرسنل: {html.escape(user_name)}\n📌 {html.escape(col1)}\n📌 {html.escape(col2)}\n📌 {html.escape(new_col3)}\nوضعیت: {updated_status_str}"
            await bot.edit_message_text(chat_id=admin_chat_id, message_id=admin_msg_id, text=updated_admin_text, reply_markup=admin_kb if is_approved else None, parse_mode="HTML")
        except Exception:
            pass

# ---------------------------------------------------------
# جریان درخواست مرخصی
# ---------------------------------------------------------
@dp.callback_query(F.data == "req_leave")
async def process_leave_start(callback: CallbackQuery, state: FSMContext):
    if not await require_active_staff_callback(callback):
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="استحقاقی", callback_data="ltype_estheghaghi")],
        [InlineKeyboardButton(text="استعلاجی", callback_data="ltype_estelaji")],
        [InlineKeyboardButton(text="ساعتی", callback_data="ltype_saati")],
        [InlineKeyboardButton(text="بدون حقوق", callback_data="ltype_without_pay")],
        [InlineKeyboardButton(text="❌ انصراف", callback_data="menu_admin_finance")]
    ])
    await callback.message.edit_text("🟩⬜⬜⬜ <b>مرحله ۱ از ۴:</b> نوع مرخصی را انتخاب کنید:", reply_markup=kb, parse_mode="HTML")
    await state.set_state(Form.waiting_for_leave_type)
    await callback.answer()

@dp.callback_query(Form.waiting_for_leave_type, F.data.startswith("ltype_"))
async def process_leave_type_selected(callback: CallbackQuery, state: FSMContext):
    ltype_key = callback.data.split("_", 1)[1]
    mapping = {
        "estheghaghi": "استحقاقی",
        "estelaji": "استعلاجی",
        "saati": "ساعتی",
        "without_pay": "بدون حقوق"
    }
    ltype = mapping.get(ltype_key, "استحقاقی")
    await state.update_data(leave_type=ltype)
    if ltype == "ساعتی":
        await state.set_state(Form.waiting_for_hourly_date)
        kb = cancel_kb("menu_admin_finance")
        await callback.message.edit_text("🟩🟩⬜⬜ <b>مرحله ۲ از ۴:</b> تاریخ روز مرخصی را با فرمت <code>سال/ماه/روز</code> وارد کنید:", reply_markup=kb, parse_mode="HTML")
    else:
        await state.set_state(Form.waiting_for_leave_start_date)
        kb = cancel_kb("menu_admin_finance")
        await callback.message.edit_text("🟩🟩⬜⬜ <b>مرحله ۲ از ۴:</b> تاریخ شروع مرخصی را با فرمت <code>سال/ماه/روز</code> وارد کنید:", reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.message(Form.waiting_for_hourly_date)
async def receive_hourly_date(message: Message, state: FSMContext):
    text_date = normalize_jalali_date(message.text) if message.text else ""
    if not validate_custom_date(text_date):
        await message.answer("❌ فرمت تاریخ نامعتبر است (<code>YYYY/MM/DD</code>):", parse_mode="HTML")
        return
    await state.update_data(hourly_date=text_date)
    await state.set_state(Form.waiting_for_hourly_times)
    await message.answer("🟩🟩🟩⬜ <b>مرحله ۳ از ۴:</b> ساعت خروج و ورود را وارد کنید (مثلاً 09:00 تا 13:00):", parse_mode="HTML")

@dp.message(Form.waiting_for_hourly_times)
async def receive_hourly_times(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ لطفاً ساعت معتبر وارد کنید.")
        return
    await state.update_data(hourly_times=normalize_persian_numbers(message.text).strip())
    await ask_for_leave_replacement(message, state)

@dp.message(Form.waiting_for_leave_start_date)
async def receive_leave_start(message: Message, state: FSMContext):
    text_date = normalize_jalali_date(message.text) if message.text else ""
    if not validate_custom_date(text_date):
        await message.answer("❌ فرمت تاریخ نامعتبر است (<code>YYYY/MM/DD</code>):", parse_mode="HTML")
        return
    await state.update_data(leave_start=text_date)
    await state.set_state(Form.waiting_for_leave_end_date)
    await message.answer("🟩🟩🟩⬜ <b>مرحله ۳ از ۴:</b> تاریخ پایان مرخصی را با فرمت <code>سال/ماه/روز</code> وارد کنید:", parse_mode="HTML")

@dp.message(Form.waiting_for_leave_end_date)
async def receive_leave_end(message: Message, state: FSMContext):
    text_date = normalize_jalali_date(message.text) if message.text else ""
    if not validate_custom_date(text_date):
        await message.answer("❌ فرمت تاریخ نامعتبر است (<code>YYYY/MM/DD</code>):", parse_mode="HTML")
        return
    data = await state.get_data()
    start_date = data.get("leave_start")
    
    try:
        s_p = [int(x) for x in start_date.split('/')]
        e_p = [int(x) for x in text_date.split('/')]
        d1 = jdatetime.date(s_p[0], s_p[1], s_p[2])
        d2 = jdatetime.date(e_p[0], e_p[1], e_p[2])
        if d2 < d1:
            await message.answer("❌ تاریخ پایان نمی‌تواند قبل از تاریخ شروع باشد. لطفاً تاریخ پایان را مجدداً وارد کنید:")
            return
    except Exception:
        await message.answer("❌ تاریخ نامعتبر است. مجدداً وارد کنید:")
        return

    await state.update_data(leave_end=text_date)
    
    if data.get("leave_type") == "استحقاقی":
        holidays = get_holidays_list()
        try:
            current_d = d1
            working_days = 0
            while current_d <= d2:
                d_str = current_d.strftime("%Y/%m/%d")
                if current_d.weekday() != 6 and d_str not in holidays:
                    working_days += 1
                current_d += jdatetime.timedelta(days=1)
            calculated_days = float(working_days) if working_days > 0 else 1.0
        except Exception:
            calculated_days = 1.0

        user_id = message.from_user.id
        _, _, balance, _, _, _ = get_staff_info_by_telegram_id(user_id)
        
        # محاسبه دربرگیرنده درخواست‌های در انتظار جهت جلوگیری از مانده منفی تجمعی
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT location FROM requests WHERE telegram_user_id = ? AND request_type = 'مرخصی' AND col1 LIKE '%استحقاقی%' AND status LIKE '%در انتظار%'", (user_id,))
            pending_leaves = sum([float(r[0]) for r in cursor.fetchall() if r[0] and str(r[0]).replace('.', '', 1).isdigit()])

        if (calculated_days + pending_leaves) > balance:
            await message.answer(f"❌ مانده مرخصی شما ({balance} روز) و درخواست‌های در انتظار ({pending_leaves} روز) برای این درخواست کافی نیست. لطفاً تاریخ‌های کوتاه‌تری انتخاب کنید:")
            return

    await ask_for_leave_replacement(message, state)

async def ask_for_leave_replacement(message: Message, state: FSMContext):
    current_user_id = message.from_user.id
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT staff_id, staff_name FROM staff_mapping WHERE is_active = 1 AND telegram_user_id != ?", (current_user_id,))
        rows = cursor.fetchall()

    buttons = []
    for r in rows:
        sid, sname = r[0], r[1]
        buttons.append([InlineKeyboardButton(text=f"👤 {sname}", callback_data=f"repl_{sid}")])
    buttons.append([InlineKeyboardButton(text="❌ بدون جایگزین / هیچکدام", callback_data="repl_None")])
    buttons.append([InlineKeyboardButton(text="❌ انصراف", callback_data="back_to_main")])
    
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await state.set_state(Form.waiting_for_replacement)
    await message.answer("🟩🟩🟩🟩 <b>مرحله ۴ از ۴:</b> همکار جایگزین خود را در زمان مرخصی انتخاب کنید:", reply_markup=kb, parse_mode="HTML")

@dp.callback_query(Form.waiting_for_replacement, F.data.startswith("repl_"))
async def process_leave_replacement_selected(callback: CallbackQuery, state: FSMContext):
    repl_raw = callback.data.split("repl_")[1]
    if repl_raw == "None":
        replacement_text = "بدون جایگزین"
        replacement_staff_id = None
    else:
        repl_sid = int(repl_raw)
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT staff_name FROM staff_mapping WHERE staff_id = ?", (repl_sid,))
            r = cursor.fetchone()
        replacement_text = r[0] if r else "بدون جایگزین"
        replacement_staff_id = repl_sid

    await state.update_data(replacement_name=replacement_text, replacement_staff_id=replacement_staff_id)

    user_data = await state.get_data()
    ltype = user_data.get("leave_type")
    
    preview_text = f"📋 <b>پیش‌نمایش درخواست مرخصی</b>\n\n🔹 نوع مرخصی: {html.escape(ltype)}\n"
    if ltype == "ساعتی":
        preview_text += f"📅 تاریخ: {html.escape(user_data.get('hourly_date'))}\n⏰ ساعت: {html.escape(user_data.get('hourly_times'))}\n"
    else:
        preview_text += f"📅 از تاریخ: {html.escape(user_data.get('leave_start'))} تا {html.escape(user_data.get('leave_end'))}\n"
    preview_text += f"🔄 فرد جایگزین: {html.escape(replacement_text)}\n\nآیا اطلاعات فوق تایید می‌شود و برای مدیر ارسال گردد؟"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 تأیید و ارسال نهایی", callback_data="leave_submit_final"),
         InlineKeyboardButton(text="❌ لغو و انصراف", callback_data="back_to_main")]
    ])
    await state.set_state(Form.waiting_for_leave_preview)
    await callback.message.edit_text(preview_text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(Form.waiting_for_leave_preview, F.data == "leave_submit_final")
async def submit_leave_final(callback: CallbackQuery, state: FSMContext):
    user_data = await state.get_data()
    user_id = callback.from_user.id
    _, staff_name, _, _, _, _ = get_staff_info_by_telegram_id(user_id)
    ltype = user_data.get("leave_type")
    replacement_text = user_data.get("replacement_name")
    replacement_staff_id = user_data.get("replacement_staff_id")
    status_repl = "تعیین تکلیف نشده ⏳" if replacement_staff_id else "بدون نیاز به جانشین"

    if ltype == "ساعتی":
        leave_date = user_data.get("hourly_date")
        times = user_data.get("hourly_times")
        col1 = f"نوع: {ltype}"
        col2 = f"تاریخ: {leave_date} | ساعت: {times}"
        col3 = f"مدت: ساعتی | جایگزین: {replacement_text} | وضعیت جانشین: {status_repl}"
        await send_request_to_admin(callback, user_id, staff_name, "مرخصی", col1, col2, col3, "0.0", amount=0, start_date=leave_date, end_date=leave_date, replacement_staff_id=replacement_staff_id)
    else:
        start_str = user_data.get("leave_start")
        end_str = user_data.get("leave_end")
        holidays = get_holidays_list()

        calculated_days = 1.0
        try:
            s_p = [int(x) for x in start_str.split('/')]
            e_p = [int(x) for x in end_str.split('/')]
            d1 = jdatetime.date(s_p[0], s_p[1], s_p[2])
            d2 = jdatetime.date(e_p[0], e_p[1], e_p[2])
            
            if d2 >= d1:
                current_d = d1
                working_days = 0
                while current_d <= d2:
                    d_str = current_d.strftime("%Y/%m/%d")
                    if current_d.weekday() != 6 and d_str not in holidays:
                        working_days += 1
                    current_d += jdatetime.timedelta(days=1)
                calculated_days = float(working_days) if working_days > 0 else 1.0
        except Exception:
            calculated_days = 1.0

        col1 = f"نوع: {ltype}"
        col2 = f"از: {start_str} ➔ تا: {end_str}"
        col3 = f"روز کسر: {calculated_days} | جایگزین: {replacement_text} | وضعیت جانشین: {status_repl}"
        await send_request_to_admin(callback, user_id, staff_name, "مرخصی", col1, col2, col3, str(calculated_days), amount=0, start_date=start_str, end_date=end_str, replacement_staff_id=replacement_staff_id)

    await state.clear()
    await callback.answer()

# ---------------------------------------------------------
# جریان درخواست مساعده
# ---------------------------------------------------------
@dp.callback_query(F.data == "req_advance")
async def process_advance_start(callback: CallbackQuery, state: FSMContext):
    if not await require_active_staff_callback(callback):
        return
    await state.set_state(Form.waiting_for_advance_amount)
    kb = cancel_kb("menu_admin_finance")
    await callback.message.edit_text("🟩⬜⬜ <b>مرحله ۱ از ۳:</b> مبلغ درخواستی مساعده (به ریال) را به عدد وارد کنید:", reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.message(Form.waiting_for_advance_amount)
async def receive_advance_amount(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ لطفاً مبلغ معتبر وارد کنید.")
        return
    raw_text = normalize_persian_numbers(message.text).replace(",", "").replace("ریال", "").strip()
    if not raw_text.isdigit():
        await message.answer("❌ مبلغ فقط باید عدد باشد:")
        return
    amount = int(raw_text)

    user_id = message.from_user.id
    current_month = get_current_tehran_time().strftime("%Y/%m")

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT amount FROM requests WHERE telegram_user_id = ? AND request_type = 'مساعده' AND month_tag = ? AND status NOT LIKE '%رد شده%' AND status NOT LIKE '%لغو%'", (user_id, current_month))
        existing_advs = cursor.fetchall()

    total_taken = sum([int(r[0]) for r in existing_advs if r[0]])

    today_day = get_current_tehran_time().day
    daily_rate = MAX_BASE_ADVANCE / 30.0
    allowed_limit = int(today_day * daily_rate)
    remaining_allowed = allowed_limit - total_taken

    if amount > remaining_allowed:
        await message.answer(f"⚠️ سقف باقیمانده مساعده شما تا امروز: {remaining_allowed:,} ریال است (کل دریافتی این ماه: {total_taken:,} از سقف {allowed_limit:,}):")
        return

    await state.update_data(advance_amount_int=amount, advance_amount=f"{amount:,}")
    await state.set_state(Form.waiting_for_advance_card)
    await message.answer("🟩🟩⬜ <b>مرحله ۲ از ۳:</b> شماره کارت (۱۶ رقم) یا شبا جهت واریز را وارد کنید:", parse_mode="HTML")

@dp.message(Form.waiting_for_advance_card)
async def receive_advance_card(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ لطفاً شماره کارت یا شبا معتبر وارد کنید.")
        return
    card = normalize_persian_numbers(message.text).strip()
    if not validate_card_or_sheba(card):
        await message.answer("❌ شماره کارت یا شبا نامعتبر است:")
        return
    await state.update_data(advance_card=card)
    await state.set_state(Form.waiting_for_advance_reason)
    await message.answer("🟩🟩🟩 <b>مرحله ۳ از ۳:</b> دلیل درخواست مساعده را بنویسید:", parse_mode="HTML")

@dp.message(Form.waiting_for_advance_reason)
async def receive_advance_reason(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ لطفاً دلیل معتبر وارد کنید.")
        return
    reason = message.text.strip()
    await state.update_data(advance_reason=reason)
    data = await state.get_data()

    preview_text = (
        f"📋 <b>پیش‌نمایش درخواست مساعده</b>\n\n"
        f"💵 مبلغ: {html.escape(data.get('advance_amount'))} ریال\n"
        f"💳 شماره کارت/شبا: <code>محفوظ (ارسال امن به مالی)</code>\n"
        f"📝 دلیل: {html.escape(reason)}\n\n"
        f"آیا اطلاعات تایید می‌شود؟"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 تأیید و ارسال نهایی", callback_data="adv_submit_final"),
         InlineKeyboardButton(text="❌ لغو و انصراف", callback_data="back_to_main")]
    ])
    await state.set_state(Form.waiting_for_advance_preview)
    await message.answer(preview_text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(Form.waiting_for_advance_preview, F.data == "adv_submit_final")
async def submit_advance_final(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user_id = callback.from_user.id
    _, staff_name, _, _, _, _ = get_staff_info_by_telegram_id(user_id)
    
    col1 = f"مبلغ: {data.get('advance_amount')} ریال"
    col2 = f"دلیل: {data.get('advance_reason')}"
    col3 = "کارت/شبا: [محفوظ و مختص واحد مالی]"
    sensitive_data = encrypt_data(f"کارت/شبا: {data.get('advance_card')}")
    amount = data.get('advance_amount_int', 0)
    
    await send_request_to_admin(callback, user_id, staff_name, "مساعده", col1, col2, col3, "-", amount=amount, sensitive_data=sensitive_data)
    await state.clear()
    await callback.answer()

# ---------------------------------------------------------
# گزارش ماموریت
# ---------------------------------------------------------
@dp.callback_query(F.data == "req_mission")
async def process_mission_start(callback: CallbackQuery, state: FSMContext):
    if not await require_active_staff_callback(callback):
        return
    await state.set_state(Form.waiting_for_mission_city)
    kb = cancel_kb("menu_admin_finance")
    await callback.message.edit_text("🟩⬜⬜ <b>مرحله ۱ از ۳:</b> شهر مقصد ماموریت را وارد کنید:", reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.message(Form.waiting_for_mission_city)
async def receive_mission_city(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ نام شهر معتبر وارد کنید.")
        return
    await state.update_data(mission_city=message.text.strip())
    await state.set_state(Form.waiting_for_mission_start_date)
    await message.answer("🟩🟩⬜ <b>مرحله ۲ از ۳:</b> تاریخ شروع ماموریت را با فرمت <code>سال/ماه/روز</code> وارد کنید:", parse_mode="HTML")

@dp.message(Form.waiting_for_mission_start_date)
async def receive_mission_start(message: Message, state: FSMContext):
    text_date = normalize_jalali_date(message.text) if message.text else ""
    if not validate_custom_date(text_date):
        await message.answer("❌ فرمت تاریخ نامعتبر است (<code>YYYY/MM/DD</code>):", parse_mode="HTML")
        return
    await state.update_data(mission_start=text_date)
    await state.set_state(Form.waiting_for_mission_end_date)
    await message.answer("🟩🟩🟩 <b>مرحله ۳ از ۳:</b> تاریخ پایان ماموریت را با فرمت <code>سال/ماه/روز</code> وارد کنید:", parse_mode="HTML")

@dp.message(Form.waiting_for_mission_end_date)
async def receive_mission_end(message: Message, state: FSMContext):
    text_date = normalize_jalali_date(message.text) if message.text else ""
    if not validate_custom_date(text_date):
        await message.answer("❌ فرمت تاریخ نامعتبر است (<code>YYYY/MM/DD</code>):", parse_mode="HTML")
        return
    data = await state.get_data()
    start_date = data.get("mission_start")

    try:
        s_p = [int(x) for x in start_date.split('/')]
        e_p = [int(x) for x in text_date.split('/')]
        d1 = jdatetime.date(s_p[0], s_p[1], s_p[2])
        d2 = jdatetime.date(e_p[0], e_p[1], e_p[2])
        if d2 < d1:
            await message.answer("❌ تاریخ پایان نمی‌تواند قبل از شروع باشد:")
            return
        mission_days = (d2 - d1).days + 1
    except Exception:
        await message.answer("❌ تاریخ نامعتبر است:")
        return

    await state.update_data(mission_end=text_date, mission_days=str(mission_days))
    
    preview_text = f"📋 <b>پیش‌نمایش گزارش ماموریت</b>\n\n📍 شهر مقصد: {html.escape(data.get('mission_city'))}\n📅 از: {html.escape(start_date)} تا {html.escape(text_date)} ({mission_days} روز)\n\nتایید نهایی می‌شود?"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 تأیید و ارسال نهایی", callback_data="mission_submit_final"),
         InlineKeyboardButton(text="❌ لغو و انصراف", callback_data="back_to_main")]
    ])
    await state.set_state(Form.waiting_for_mission_preview)
    await message.answer(preview_text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(Form.waiting_for_mission_preview, F.data == "mission_submit_final")
async def submit_mission_final(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user_id = callback.from_user.id
    _, staff_name, _, _, _, _ = get_staff_info_by_telegram_id(user_id)
    
    col1 = f"شهر: {data.get('mission_city')}"
    col2 = f"مدت: {data.get('mission_days')} روز (از {data.get('mission_start')} تا {data.get('mission_end')})"
    col3 = "-"
    await send_request_to_admin(callback, user_id, staff_name, "ماموریت", col1, col2, col3, "-", start_date=data.get('mission_start'), end_date=data.get('mission_end'))
    await state.clear()
    await callback.answer()

# ---------------------------------------------------------
# تنخواه
# ---------------------------------------------------------
@dp.callback_query(F.data == "req_petty")
async def process_petty_start(callback: CallbackQuery, state: FSMContext):
    if not await require_active_staff_callback(callback):
        return
    await state.set_state(Form.waiting_for_petty_photo)
    kb = cancel_kb("menu_assets_purchase")
    await callback.message.edit_text("🟩⬜⬜ <b>مرحله ۱ از ۳:</b> عکس واضح فاکتور خرید را ارسال نمایید:", reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.message(Form.waiting_for_petty_photo, F.photo)
async def receive_petty_photo(message: Message, state: FSMContext):
    photo_id = message.photo[-1].file_id
    await state.update_data(petty_photo=photo_id)
    await state.set_state(Form.waiting_for_petty_amount)
    await message.answer("🟩🟩⬜ <b>مرحله ۲ از ۳:</b> مبلغ فاکتور (به ریال) را به عدد وارد کنید:", parse_mode="HTML")

@dp.message(Form.waiting_for_petty_amount)
async def receive_petty_amount(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ مبلغ معتبر وارد کنید.")
        return
    raw_val = normalize_persian_numbers(message.text).replace(",", "").strip()
    if not raw_val.isdigit():
        await message.answer("❌ مبلغ فقط باید عدد باشد:")
        return
    amount_int = int(raw_val)
    await state.update_data(petty_amount_int=amount_int, petty_amount=f"{amount_int:,} ریال")
    await state.set_state(Form.waiting_for_petty_desc)
    await message.answer("🟩🟩🟩 <b>مرحله ۳ از ۳:</b> شرح هزینه را بنویسید:", parse_mode="HTML")

@dp.message(Form.waiting_for_petty_desc)
async def receive_petty_desc(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ شرح هزینه معتبر وارد کنید.")
        return
    desc = message.text.strip()
    await state.update_data(petty_desc=desc)
    data = await state.get_data()

    preview_text = f"📋 <b>پیش‌نمایش کامل فاکتور تنخواه</b>\n\n💵 مبلغ: {html.escape(data.get('petty_amount'))}\n📝 شرح هزینه: {html.escape(desc)}\n🖼 تصویر فاکتور ضمیمه شده است.\n\nتأیید و ارسال نهایی می‌شود?"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 تأیید و ارسال نهایی", callback_data="petty_submit_final"),
         InlineKeyboardButton(text="❌ لغو و انصراف", callback_data="back_to_main")]
    ])
    await state.set_state(Form.waiting_for_petty_preview)
    await message.answer_photo(photo=data.get('petty_photo'), caption=preview_text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(Form.waiting_for_petty_preview, F.data == "petty_submit_final")
async def submit_petty_final(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user_id = callback.from_user.id
    _, staff_name, _, _, _, _ = get_staff_info_by_telegram_id(user_id)
    
    col1 = f"مبلغ: {data.get('petty_amount')}"
    col2 = f"بابت: {data.get('petty_desc')}"
    col3 = "-"
    amount = data.get('petty_amount_int', 0)
    await send_request_to_admin(callback, user_id, staff_name, "تنخواه", col1, col2, col3, "-", amount=amount, photo_id=data.get("petty_photo"))
    await state.clear()
    await callback.answer()

# ---------------------------------------------------------
# عودت اموال
# ---------------------------------------------------------
@dp.callback_query(F.data == "req_return_asset")
async def process_return_asset_start(callback: CallbackQuery, state: FSMContext):
    if not await require_active_staff_callback(callback):
        return
    user_id = callback.from_user.id
    staff_id, _, _, _, _, _ = get_staff_info_by_telegram_id(user_id)

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, asset_type, details FROM user_assets WHERE staff_id = ? AND is_active = 1", (staff_id,))
        assets = cursor.fetchall()

    if not assets:
        await callback.answer("شما هیچ تجهیز فعالی برای عودت ندارید.", show_alert=True)
        return

    buttons = [[InlineKeyboardButton(text=f"📦 {a[1]} ({html.escape(a[2][:30])})", callback_data=f"retasset_{a[0]}")] for a in assets]
    buttons.append([InlineKeyboardButton(text="❌ انصراف", callback_data="back_to_main")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.edit_text("🔄 <b>درخواست عودت اموال و تجهیزات</b>\n\nکدام تجهیز را می‌خواهید عودت دهید؟", reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data.startswith("retasset_"))
async def process_return_asset_selected(callback: CallbackQuery, state: FSMContext):
    asset_id = int(callback.data.split("retasset_")[1])
    user_id = callback.from_user.id
    staff_id, _, _, _, _, _ = get_staff_info_by_telegram_id(user_id)

    # بررسی سخت‌گیرانه مالکیت مال قبل از عودت
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT staff_id FROM user_assets WHERE id = ?", (asset_id,))
        arow = cursor.fetchone()
        if not arow or arow[0] != staff_id:
            await callback.answer("❌ این تجهیز متعلق به شما نیست.", show_alert=True)
            return

    await state.update_data(return_asset_id=asset_id)
    await state.set_state(Form.return_asset_desc)
    kb = cancel_kb("menu_assets_purchase")
    await callback.message.edit_text("📝 لطفاً دلیل یا توضیحات عودت این تجهیز را بنویسید:", reply_markup=kb)
    await callback.answer()

@dp.message(Form.return_asset_desc)
async def receive_return_asset_desc(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ توضیحات معتبر وارد کنید.")
        return
    desc = message.text.strip()
    await state.update_data(return_desc=desc)

    preview_text = f"📋 <b>پیش‌نمایش درخواست عودت اموال</b>\n\n📝 توضیحات: {html.escape(desc)}\n\nثبت نهایی شود؟"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 تأیید و ارسال نهایی", callback_data="return_submit_final"),
         InlineKeyboardButton(text="❌ لغو و انصراف", callback_data="back_to_main")]
    ])
    await state.set_state(Form.return_asset_preview)
    await message.answer(preview_text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(Form.return_asset_preview, F.data == "return_submit_final")
async def submit_return_final(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user_id = callback.from_user.id
    _, staff_name, _, _, _, _ = get_staff_info_by_telegram_id(user_id)
    date_now = get_current_tehran_time().strftime("%Y/%m/%d %H:%M")

    asset_id = data.get("return_asset_id")
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT asset_type, details FROM user_assets WHERE id = ?", (asset_id,))
        arow = cursor.fetchone()

    asset_info = f"{arow[0]} - {arow[1]}" if arow else "تجهیز نامشخص"

    col1 = f"تاریخ عودت: {date_now} | تجهیز: {asset_info}"
    col2 = f"توضیحات: {data.get('return_desc')}"
    col3 = f"شناسه مال: {asset_id} | وضعیت: در انتظار تحویل فیزیکی و تأیید"
    await send_request_to_admin(callback, user_id, staff_name, "عودت اموال", col1, col2, col3, str(asset_id))
    await state.clear()
    await callback.answer()

# ---------------------------------------------------------
# خرید ملزومات
# ---------------------------------------------------------
@dp.callback_query(F.data == "req_purchase")
async def process_purchase_start(callback: CallbackQuery, state: FSMContext):
    if not await require_active_staff_callback(callback):
        return
    await state.set_state(Form.purch_item_name)
    kb = cancel_kb("menu_assets_purchase")
    await callback.message.edit_text("🟩⬜⬜ <b>مرحله ۱ از ۳:</b> نام کالا یا ملزومات مورد نیاز را بنویسید:", reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.message(Form.purch_item_name)
async def receive_purch_item(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ نام کالا معتبر وارد کنید.")
        return
    await state.update_data(purch_item=message.text.strip())
    await state.set_state(Form.purch_qty)
    await message.answer("🟩🟩⬜ <b>مرحله ۲ از ۳:</b> تعداد یا مقدار مورد نیاز را وارد کنید:", parse_mode="HTML")

@dp.message(Form.purch_qty)
async def receive_purch_qty(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ تعداد معتبر وارد کنید.")
        return
    await state.update_data(purch_qty=message.text.strip())
    await state.set_state(Form.purch_desc)
    await message.answer("🟩🟩🟩 <b>مرحله ۳ از ۳:</b> توضیحات یا دلیل نیاز به خرید را بنویسید:", parse_mode="HTML")

@dp.message(Form.purch_desc)
async def receive_purch_desc(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ توضیحات معتبر وارد کنید.")
        return
    desc = message.text.strip()
    await state.update_data(purch_desc=desc)
    data = await state.get_data()

    preview_text = f"📋 <b>پیش‌نمایش کامل درخواست خرید انبار</b>\n\n🛒 کالا: {html.escape(data.get('purch_item'))}\n🔢 تعداد: {html.escape(data.get('purch_qty'))}\n📝 توضیحات: {html.escape(desc)}\n\nتأیید و ارسال نهایی می‌شود?"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 تأیید و ارسال نهایی", callback_data="purch_submit_final"),
         InlineKeyboardButton(text="❌ لغو و انصراف", callback_data="back_to_main")]
    ])
    await state.set_state(Form.purch_preview)
    await message.answer(preview_text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(Form.purch_preview, F.data == "purch_submit_final")
async def submit_purch_final(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user_id = callback.from_user.id
    _, staff_name, _, _, _, _ = get_staff_info_by_telegram_id(user_id)
    
    col1 = f"کالا: {data.get('purch_item')}"
    col2 = f"تعداد: {data.get('purch_qty')}"
    col3 = f"توضیحات: {data.get('purch_desc')}"
    await send_request_to_admin(callback, user_id, staff_name, "خرید ملزومات", col1, col2, col3, "-")
    await state.clear()
    await callback.answer()

# ---------------------------------------------------------
# تحویل اموال
# ---------------------------------------------------------
@dp.callback_query(F.data == "req_asset")
async def process_asset_start(callback: CallbackQuery, state: FSMContext):
    if not await require_active_staff_callback(callback):
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚗 خودروی سازمانی", callback_data="asset_sel_car")],
        [InlineKeyboardButton(text="⛽ کارت سوخت", callback_data="asset_sel_fuel")],
        [InlineKeyboardButton(text="💳 کارت‌خوان (POS)", callback_data="asset_sel_pos")],
        [InlineKeyboardButton(text="🖨️ پرینتر جیبی", callback_data="asset_sel_printer")],
        [InlineKeyboardButton(text="❌ انصراف", callback_data="menu_assets_purchase")]
    ])
    date_now = get_current_tehran_time().strftime("%Y/%m/%d")
    await callback.message.edit_text(f"🚗 <b>ثبت تحویل اقلام امانی و تجهیزات</b>\n📅 تاریخ امروز: <code>{date_now}</code>\n\nقلم مورد نظر را انتخاب کنید:", reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "asset_sel_car")
async def asset_car_step1(callback: CallbackQuery, state: FSMContext):
    await state.set_state(Form.asset_car_code)
    kb = cancel_kb("menu_assets_purchase")
    await callback.message.edit_text("🚗 <b>مرحله ۱ از ۵:</b> کد خودرو را وارد کنید:", reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.message(Form.asset_car_code)
async def asset_car_step2(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ کد معتبر وارد کنید.")
        return
    await state.update_data(car_code=message.text.strip())
    await state.set_state(Form.asset_car_plate)
    await message.answer("🚗 <b>مرحله ۲ از ۵:</b> پلاک خودرو را وارد کنید:", parse_mode="HTML")

@dp.message(Form.asset_car_plate)
async def asset_car_step3(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ پلاک معتبر وارد کنید.")
        return
    await state.update_data(car_plate=message.text.strip())
    await state.set_state(Form.asset_car_type)
    await message.answer("🚗 <b>مرحله ۳ از ۵:</b> نوع خودرو را وارد کنید:", parse_mode="HTML")

@dp.message(Form.asset_car_type)
async def asset_car_step4(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ نوع خودرو معتبر وارد کنید.")
        return
    await state.update_data(car_type=message.text.strip())
    await state.set_state(Form.asset_car_km)
    await message.answer("🚗 <b>مرحله ۴ از ۵:</b> کیلومتر تحویلی را وارد کنید:", parse_mode="HTML")

@dp.message(Form.asset_car_km)
async def asset_car_step5(message: Message, state: FSMContext):
    clean_km = normalize_persian_numbers(message.text).strip() if message.text else ""
    if not clean_km.isdigit():
        await message.answer("❌ کیلومتر باید عدد باشد:")
        return
    await state.update_data(car_km=clean_km)
    await state.set_state(Form.asset_car_desc)
    await message.answer("🚗 <b>مرحله ۵ از ۵:</b> توضیحات تکمیلی (اگر ندارد <code>-</code> بگذارید):", parse_mode="HTML")

@dp.message(Form.asset_car_desc)
async def asset_car_preview(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ توضیحات معتبر وارد کنید.")
        return
    desc = message.text.strip()
    await state.update_data(car_desc=desc)
    data = await state.get_data()

    preview_text = (
        f"📋 <b>پیش‌نمایش کامل تحویل خودروی سازمانی</b>\n\n"
        f"🔹 کد: {html.escape(data.get('car_code'))} | پلاک: {html.escape(data.get('car_plate'))}\n"
        f"🔹 نوع خودرو: {html.escape(data.get('car_type'))} | کیلومتر: {html.escape(data.get('car_km'))}\n"
        f"📝 توضیحات: {html.escape(desc)}\n\nتایید نهایی می‌شود?"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 تأیید و ارسال نهایی", callback_data="asset_car_submit_final"),
         InlineKeyboardButton(text="❌ لغو و انصراف", callback_data="back_to_main")]
    ])
    await state.set_state(Form.asset_car_preview)
    await message.answer(preview_text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(Form.asset_car_preview, F.data == "asset_car_submit_final")
async def submit_asset_car_final(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    date_now = get_current_tehran_time().strftime("%Y/%m/%d")
    col1 = f"تاریخ تحویل: {date_now} | کد: {data.get('car_code')} | پلاک: {data.get('car_plate')}"
    col2 = f"نوع: {data.get('car_type')} | کیلومتر: {data.get('car_km')}"
    col3 = f"توضیحات: {data.get('car_desc')}"
    user_id = callback.from_user.id
    _, staff_name, _, _, _, _ = get_staff_info_by_telegram_id(user_id)
    await send_request_to_admin(callback, user_id, staff_name, "تحویل اموال", col1, col2, col3, "خودروی سازمانی")
    await state.clear()
    await callback.answer()

@dp.callback_query(F.data == "asset_sel_fuel")
async def asset_fuel_step1(callback: CallbackQuery, state: FSMContext):
    await state.set_state(Form.asset_fuel_code)
    kb = cancel_kb("menu_assets_purchase")
    await callback.message.edit_text("⛽ <b>مرحله ۱ از ۵:</b> کد کارت سوخت را وارد کنید:", reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.message(Form.asset_fuel_code)
async def asset_fuel_step2(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ کد معتبر وارد کنید.")
        return
    await state.update_data(fuel_code=message.text.strip())
    await state.set_state(Form.asset_fuel_pass)
    await message.answer("⛽ <b>مرحله ۲ از ۵:</b> رمز کارت سوخت را وارد کنید:", parse_mode="HTML")

@dp.message(Form.asset_fuel_pass)
async def asset_fuel_step3(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ رمز معتبر وارد کنید.")
        return
    await state.update_data(fuel_pass=message.text.strip())
    await state.set_state(Form.asset_fuel_l1500)
    await message.answer("⛽ <b>مرحله ۳ از ۵:</b> میزان لیتر سهمیه <b>۱۵۰۰ تومانی</b> ماهیانه:", parse_mode="HTML")

@dp.message(Form.asset_fuel_l1500)
async def asset_fuel_step4(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ مقدار معتبر وارد کنید.")
        return
    await state.update_data(fuel_l1500=message.text.strip())
    await state.set_state(Form.asset_fuel_l3000)
    await message.answer("⛽ <b>مرحله ۴ از ۵:</b> میزان لیتر سهمیه <b>۳۰۰۰ تومانی</b> ماهیانه:", parse_mode="HTML")

@dp.message(Form.asset_fuel_l3000)
async def asset_fuel_step5(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ مقدار معتبر وارد کنید.")
        return
    await state.update_data(fuel_l3000=message.text.strip())
    await state.set_state(Form.asset_fuel_l10000)
    await message.answer("⛽ <b>مرحله ۵ از ۵:</b> میزان لیتر سهمیه <b>۱۰,۰۰۰ تومانی</b> ماهیانه:", parse_mode="HTML")

@dp.message(Form.asset_fuel_l10000)
async def asset_fuel_preview(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ مقدار معتبر وارد کنید.")
        return
    l10000 = message.text.strip()
    await state.update_data(fuel_l10000=l10000)
    data = await state.get_data()

    preview_text = (
        f"📋 <b>پیش‌نمایش کامل تحویل کارت سوخت</b>\n\n"
        f"⛽ کد کارت: {html.escape(data.get('fuel_code'))} | رمز: <code>محفوظ (ارسال امن به مالی)</code>\n"
        f"🔹 سهمیه ۱۵۰۰: {html.escape(data.get('fuel_l1500'))} | ۳۰۰۰: {html.escape(data.get('fuel_l3000'))}\n"
        f"🔹 سهمیه ۱۰,۰۰۰: {html.escape(l10000)} لیتر\n\nتایید نهایی می‌شود?"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 تأیید و ارسال نهایی", callback_data="asset_fuel_submit_final"),
         InlineKeyboardButton(text="❌ لغو و انصراف", callback_data="back_to_main")]
    ])
    await state.set_state(Form.asset_fuel_preview)
    await message.answer(preview_text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(Form.asset_fuel_preview, F.data == "asset_fuel_submit_final")
async def submit_asset_fuel_final(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    date_now = get_current_tehran_time().strftime("%Y/%m/%d")
    col1 = f"تاریخ تحویل: {date_now} | کد کارت سوخت: {data.get('fuel_code')} | رمز: [محفوظ و مختص واحد مالی]"
    col2 = f"سهمیه ۱۵۰۰ تومانی: {data.get('fuel_l1500')} | ۳۰۰۰ تومانی: {data.get('fuel_l3000')}"
    col3 = f"سهمیه ۱۰,۰۰۰ تومانی: {data.get('fuel_l10000')} لیتر"
    sensitive_data = encrypt_data(f"رمز کارت سوخت: {data.get('fuel_pass')}")
    user_id = callback.from_user.id
    _, staff_name, _, _, _, _ = get_staff_info_by_telegram_id(user_id)
    await send_request_to_admin(callback, user_id, staff_name, "تحویل اموال", col1, col2, col3, "کارت سوخت", sensitive_data=sensitive_data)
    await state.clear()
    await callback.answer()

@dp.callback_query(F.data == "asset_sel_pos")
async def asset_pos_step1(callback: CallbackQuery, state: FSMContext):
    await state.set_state(Form.asset_pos_code)
    kb = cancel_kb("menu_assets_purchase")
    await callback.message.edit_text("💳 <b>مرحله ۱ از ۳:</b> کد دستگاه پوز را وارد کنید:", reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.message(Form.asset_pos_code)
async def asset_pos_step2(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ کد معتبر وارد کنید.")
        return
    await state.update_data(pos_code=message.text.strip())
    await state.set_state(Form.asset_pos_bank)
    await message.answer("💳 <b>مرحله ۲ از ۳:</b> نام بانک را وارد کنید:", parse_mode="HTML")

@dp.message(Form.asset_pos_bank)
async def asset_pos_step3(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ نام بانک معتبر وارد کنید.")
        return
    await state.update_data(pos_bank=message.text.strip())
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ دارد", callback_data="poschg_yes"),
         InlineKeyboardButton(text="❌ ندارد", callback_data="poschg_no")]
    ])
    await state.set_state(Form.asset_pos_charger)
    await message.answer("💳 <b>مرحله ۳ از ۳:</b> آیا دستگاه پوز <b>شارژر</b> دارد؟", reply_markup=kb, parse_mode="HTML")

@dp.callback_query(Form.asset_pos_charger, F.data.startswith("poschg_"))
async def asset_pos_preview(callback: CallbackQuery, state: FSMContext):
    charger = "دارد" if callback.data.split("_")[1] == "yes" else "ندارد"
    await state.update_data(pos_charger=charger)
    data = await state.get_data()

    preview_text = (
        f"📋 <b>پیش‌نمایش کامل تحویل کارت‌خوان (POS)</b>\n\n"
        f"💳 کد پوز: {html.escape(data.get('pos_code'))} | بانک: {html.escape(data.get('pos_bank'))}\n"
        f"🔌 شارژر: {charger}\n\nتایید نهایی می‌شود?"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 تأیید و ارسال نهایی", callback_data="asset_pos_submit_final"),
         InlineKeyboardButton(text="❌ لغو و انصراف", callback_data="back_to_main")]
    ])
    await state.set_state(Form.asset_pos_preview)
    try:
        await callback.message.edit_text(preview_text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await callback.message.answer(preview_text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(Form.asset_pos_preview, F.data == "asset_pos_submit_final")
async def submit_asset_pos_final(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    date_now = get_current_tehran_time().strftime("%Y/%m/%d")
    col1 = f"تاریخ تحویل: {date_now} | کد پوز: {data.get('pos_code')}"
    col2 = f"بانک: {data.get('pos_bank')}"
    col3 = f"شارژر: {data.get('pos_charger')}"
    user_id = callback.from_user.id
    _, staff_name, _, _, _, _ = get_staff_info_by_telegram_id(user_id)
    await send_request_to_admin(callback, user_id, staff_name, "تحویل اموال", col1, col2, col3, "کارت‌خوان")
    await state.clear()
    await callback.answer()

@dp.callback_query(F.data == "asset_sel_printer")
async def asset_printer_step1(callback: CallbackQuery, state: FSMContext):
    await state.set_state(Form.asset_printer_code)
    kb = cancel_kb("menu_assets_purchase")
    await callback.message.edit_text("🖨️ <b>مرحله ۱ از ۲:</b> کد پرینتر جیبی را وارد کنید:", reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.message(Form.asset_printer_code)
async def asset_printer_step2(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ کد معتبر وارد کنید.")
        return
    await state.update_data(printer_code=message.text.strip())
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ دارد", callback_data="prchg_yes"),
         InlineKeyboardButton(text="❌ ندارد", callback_data="prchg_no")]
    ])
    await state.set_state(Form.asset_printer_charger)
    await message.answer("🖨️ <b>مرحله ۲ از ۲:</b> آیا پرینتر <b>شارژر</b> دارد؟", reply_markup=kb, parse_mode="HTML")

@dp.callback_query(Form.asset_printer_charger, F.data.startswith("prchg_"))
async def asset_printer_preview(callback: CallbackQuery, state: FSMContext):
    charger = "دارد" if callback.data.split("_")[1] == "yes" else "ندارد"
    await state.update_data(printer_charger=charger)
    data = await state.get_data()

    preview_text = (
        f"📋 <b>پیش‌نمایش کامل تحویل پرینتر جیبی</b>\n\n"
        f"🖨️ کد پرینتر: {html.escape(data.get('printer_code'))}\n"
        f"🔌 شارژر: {charger}\n\nتایید نهایی می‌شود?"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 تأیید و ارسال نهایی", callback_data="asset_printer_submit_final"),
         InlineKeyboardButton(text="❌ لغو و انصراف", callback_data="back_to_main")]
    ])
    await state.set_state(Form.asset_printer_preview)
    try:
        await callback.message.edit_text(preview_text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await callback.message.answer(preview_text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(Form.asset_printer_preview, F.data == "asset_printer_submit_final")
async def submit_asset_printer_final(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    date_now = get_current_tehran_time().strftime("%Y/%m/%d")
    col1 = f"تاریخ تحویل: {date_now} | کد پرینتر: {data.get('printer_code')}"
    col2 = f"شارژر: {data.get('printer_charger')}"
    col3 = "-"
    user_id = callback.from_user.id
    _, staff_name, _, _, _, _ = get_staff_info_by_telegram_id(user_id)
    await send_request_to_admin(callback, user_id, staff_name, "تحویل اموال", col1, col2, col3, "پرینتر جیبی")
    await state.clear()
    await callback.answer()

# ---------------------------------------------------------
# گزارشات کاربر و پیگیری
# ---------------------------------------------------------
@dp.callback_query(F.data == "my_stats")
async def show_user_stats(callback: CallbackQuery):
    user_id = callback.from_user.id
    staff_id, staff_name, balance, _, _, _ = get_staff_info_by_telegram_id(user_id)
    current_month = get_current_tehran_time().strftime("%Y/%m")

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT location FROM requests WHERE telegram_user_id = ? AND request_type = 'مرخصی' AND col1 LIKE '%استحقاقی%' AND month_tag = ? AND status = '✅ تأیید شده قطعی'", (user_id, current_month))
        leave_rows = cursor.fetchall()
        used_leave = sum([float(r[0]) for r in leave_rows if r[0] and str(r[0]).replace('.', '', 1).isdigit()])

        cursor.execute("SELECT amount FROM requests WHERE telegram_user_id = ? AND request_type = 'مساعده' AND month_tag = ? AND status IN ('💳 تسویه و پرداخت شده', '✅ تأیید شده قطعی')", (user_id, current_month))
        adv_rows = cursor.fetchall()
        total_adv = sum([int(r[0]) for r in adv_rows if r[0]])

        cursor.execute("SELECT location FROM requests WHERE telegram_user_id = ? AND request_type = 'ماموریت' AND month_tag = ? AND status = '✅ تأیید شده قطعی'", (user_id, current_month))
        mission_count = len(cursor.fetchall())

    stats_msg = (
        f"📊 <b>کارنامه و وضعیت ماه جاری ({current_month})</b>\n\n"
        f"👤 <b>نام پرسنل:</b> {html.escape(staff_name)}\n"
        f"🌿 <b>مرخصی استحقاقی استفاده‌شده ماه:</b> {used_leave} روز\n"
        f"🍃 <b>مانده مرخصی کل (دفتر کل):</b> {balance} روز\n"
        f"💵 <b>مجموع مساعده پرداختی/تاییدشده:</b> {total_adv:,} ریال\n"
        f"📍 <b>تعداد مأموریت‌ها:</b> {mission_count} مورد\n"
    )
    await callback.message.answer(stats_msg, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "my_excel_report")
async def send_my_excel_report(callback: CallbackQuery):
    user_id = callback.from_user.id
    staff_id, staff_name, _, _, _, _ = get_staff_info_by_telegram_id(user_id)
    if not staff_name:
        await callback.answer("حساب پرسنلی یافت نشد.", show_alert=True)
        return

    with get_connection() as conn:
        df_req = pd.read_sql_query("SELECT req_code, request_type, col1, col2, col3, status, created_at FROM requests WHERE telegram_user_id = ?", conn, params=(user_id,))
        df_assets = pd.read_sql_query("SELECT asset_type, details, is_active, approval_status, assigned_at FROM user_assets WHERE staff_id = ?", conn, params=(staff_id,))

    df_req = df_req.rename(columns={
        "req_code": "کد درخواست",
        "request_type": "نوع درخواست",
        "col1": "اطلاعات اصلی",
        "col2": "جزئیات اول",
        "col3": "جزئیات دوم",
        "status": "وضعیت درخواست",
        "created_at": "تاریخ ثبت"
    })

    df_assets = df_assets.rename(columns={
        "asset_type": "نوع تجهیز",
        "details": "مشخصات و جزئیات مال",
        "is_active": "وضعیت فعال بودن",
        "approval_status": "وضعیت تایید پرسنل",
        "assigned_at": "تاریخ واگذاری"
    })

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df_req.to_excel(writer, sheet_name="درخواست‌های من", index=False)
        df_assets.to_excel(writer, sheet_name="اموال من", index=False)
    output.seek(0)

    filename = f"Report_{staff_name.replace(' ', '_')}.xlsx"
    file_bytes = BufferedInputFile(output.getvalue(), filename=filename)
    await callback.message.answer_document(file_bytes, caption=f"📊 گزارش عملکرد و اموال تحویلی شما ({staff_name})")
    await callback.answer()

@dp.callback_query(F.data == "my_requests")
async def show_user_requests(callback: CallbackQuery):
    user_id = callback.from_user.id
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT req_code, request_type, col1, col2, col3, status, created_at FROM requests WHERE telegram_user_id = ? ORDER BY id DESC LIMIT 5", (user_id,))
        rows = cursor.fetchall()

    if not rows:
        await callback.answer("شما تاکنون درخواستی ثبت نکرده‌اید.", show_alert=True)
        return

    for r in rows:
        r_code, r_type, c1, c2, c3, status, created_at = r
        text = f"🔹 <b>کد: {r_code}</b> | نوع: {r_type}\n📌 اطلاعات: {html.escape(c1)} | {html.escape(c2)}\n📌 جزئیات: {html.escape(c3)}\n📌 وضعیت: <b>{html.escape(status)}</b>\n📅 تاریخ: {created_at}"
        keyboard = None
        if "در انتظار" in status:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ لغو این درخواست", callback_data=f"cancel_{r_code}")]])
        await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data.startswith("cancel_"))
async def cancel_request_cb(callback: CallbackQuery):
    r_code = callback.data.split("_")[1]
    user_id = callback.from_user.id
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT telegram_user_id, status, admin_chat_id, admin_msg_id FROM requests WHERE req_code = ?", (r_code,))
        row = cursor.fetchone()
        if row and row[0] == user_id and "در انتظار" in row[1]:
            cursor.execute("UPDATE requests SET status = '❌ لغو شده توسط پرسنل' WHERE req_code = ?", (r_code,))
            conn.commit()
            
            a_chat, a_msg = row[2], row[3]
            if a_chat and a_msg:
                try:
                    await bot.edit_message_text(chat_id=a_chat, message_id=a_msg, text=f"📩 <b>درخواست ({r_code})</b>\n\n❌ <b>وضعیت: لغو شده توسط پرسنل</b>", reply_markup=None, parse_mode="HTML")
                except Exception:
                    pass

            await callback.message.edit_text(callback.message.text + "\n\n<b>[این درخواست توسط شما لغو شد]</b>", reply_markup=None, parse_mode="HTML")
            await callback.answer("درخواست لغو شد.")
        else:
            await callback.answer("امکان لغو این درخواست وجود ندارد.", show_alert=True)

# ---------------------------------------------------------
# پنل مدیریت پیشرفته
# ---------------------------------------------------------
@dp.callback_query(F.data == "admin_panel")
@dp.message(Command("admin"), F.chat.type == "private")
async def show_admin_panel(event: CallbackQuery | Message, state: FSMContext):
    user_id = event.from_user.id
    if not is_any_admin(user_id):
        if isinstance(event, CallbackQuery):
            await event.answer("❌ دسترسی غیرمجاز!", show_alert=True)
        return

    await state.clear()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏳ درخواست‌های در انتظار (بررسی یکجا)", callback_data="admin_pending_reqs")],
        [InlineKeyboardButton(text="👥 مدیریت پرسنل، ویرایش و تاریخ‌ها", callback_data="adm_cat_staff")],
        [InlineKeyboardButton(text="🚗 واگذاری و ویرایش اموال پرسنل", callback_data="admin_assign_asset")],
        [InlineKeyboardButton(text="🛡️ ثبت بیمه شخص ثالث و بدنه", callback_data="admin_add_insurance")],
        [InlineKeyboardButton(text="📅 مدیریت روزهای تعطیل شرکت", callback_data="admin_holidays_menu")],
        [InlineKeyboardButton(text="📊 گزارشات اکسل تخصصی", callback_data="adm_cat_excel")],
        [InlineKeyboardButton(text="🗑️ ریست انتخابی دیتابیس", callback_data="admin_selective_reset_menu")],
        [InlineKeyboardButton(text="📦 دانلود بکاپ دیتابیس", callback_data="admin_get_backup")],
        [InlineKeyboardButton(text="🔙 بازگشت به منوی اصلی", callback_data="back_to_main")]
    ])
    
    text = "⚙️ <b>پنل مدیریت پیشرفته ERP</b>\n\nبخش مورد نظر را انتخاب کنید:"
    if isinstance(event, CallbackQuery):
        await event.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        await event.answer()
    else:
        await event.answer(text, reply_markup=keyboard, parse_mode="HTML")

@dp.callback_query(F.data == "admin_pending_reqs")
async def admin_show_pending_requests(callback: CallbackQuery):
    if not is_any_admin(callback.from_user.id):
        await callback.answer("❌ دسترسی غیرمجاز!", show_alert=True)
        return

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, req_code, user_name, request_type, col1, col2, created_at FROM requests WHERE status LIKE '%در انتظار%' ORDER BY id ASC LIMIT 10")
        rows = cursor.fetchall()

    if not rows:
        await callback.answer("هیچ درخواست بلاتکلیف و در انتظاری وجود ندارد.", show_alert=True)
        return

    await callback.message.answer("⏳ <b>لیست درخواست‌های در انتظار تأیید مدیریت:</b>", parse_mode="HTML")
    for r in rows:
        req_id, req_code, uname, rtype, c1, c2, created_at = r
        text = f"📩 <b>کد: {req_code}</b> | نوع: {rtype}\n👤 پرسنل: {html.escape(uname)}\n📌 {html.escape(c1)}\n📌 {html.escape(c2)}\n📅 ثبت: {created_at}"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ تأیید نهایی", callback_data=f"approve_{req_id}"),
             InlineKeyboardButton(text="❌ رد درخواست", callback_data=f"reject_{req_id}")]
        ])
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "admin_holidays_menu")
async def admin_holidays_menu(callback: CallbackQuery):
    if not check_user_role(callback.from_user.id, "main_admin"):
        await callback.answer("❌ دسترسی غیرمجاز!", show_alert=True)
        return
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT h_date, description FROM holidays ORDER BY h_date DESC LIMIT 10")
        rows = cursor.fetchall()

    text = "📅 <b>مدیریت روزهای تعطیل شرکت</b>\n(در محاسبات مرخصی کسر نمی‌شوند)\n\n"
    buttons = [[InlineKeyboardButton(text="➕ افزودن روز تعطیل جدید", callback_data="add_holiday_start")]]
    for r in rows:
        h_date, desc = r
        buttons.append([InlineKeyboardButton(text=f"❌ حذف تعطیلی {h_date} ({desc})", callback_data=f"delhol_{h_date}")])
    buttons.append([InlineKeyboardButton(text="🔙 بازگشت به پنل", callback_data="admin_panel")])
    
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "add_holiday_start")
async def add_holiday_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminForm.holiday_date)
    kb = cancel_kb("admin_holidays_menu")
    await callback.message.edit_text("📅 تاریخ روز تعطیل را با فرمت <code>YYYY/MM/DD</code> وارد کنید:", reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.message(AdminForm.holiday_date)
async def receive_holiday_date(message: Message, state: FSMContext):
    text_date = normalize_jalali_date(message.text) if message.text else ""
    if not validate_custom_date(text_date):
        await message.answer("❌ فرمت تاریخ نامعتبر است (<code>YYYY/MM/DD</code>):", parse_mode="HTML")
        return
    await state.update_data(h_date=text_date)
    await state.set_state(AdminForm.holiday_desc)
    await message.answer("📝 شرح یا دلیل تعطیلی را بنویسید:")

@dp.message(AdminForm.holiday_desc)
async def receive_holiday_desc(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ شرح معتبر وارد کنید.")
        return
    desc = message.text.strip()
    data = await state.get_data()
    h_date = data.get("h_date")

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO holidays (h_date, description) VALUES (?, ?)", (h_date, desc))
        conn.commit()

    await message.answer(f"✅ روز تعطیل <code>{h_date}</code> ({html.escape(desc)}) با موفقیت ثبت شد.", parse_mode="HTML")
    await state.clear()

@dp.callback_query(F.data.startswith("delhol_"))
async def delete_holiday(callback: CallbackQuery):
    h_date = callback.data.split("delhol_")[1]
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM holidays WHERE h_date = ?", (h_date,))
        conn.commit()
    await callback.answer(f"تعطیلی {h_date} حذف شد.")
    await admin_holidays_menu(callback)

@dp.callback_query(F.data == "adm_cat_staff")
async def admin_category_staff(callback: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ افزودن پرسنل جدید", callback_data="admin_add_staff")],
        [InlineKeyboardButton(text="✏️ ویرایش مشخصات پرسنل", callback_data="admin_edit_staff_list")],
        [InlineKeyboardButton(text="🚫 غیرفعال کردن پرسنل (ثبت تسویه)", callback_data="admin_deactivate_staff_list")],
        [InlineKeyboardButton(text="📋 لیست کامل پرسنل و جزئیات", callback_data="admin_list_staff")],
        [InlineKeyboardButton(text="🔙 بازگشت به پنل", callback_data="admin_panel")]
    ])
    await callback.message.edit_text("👥 <b>مدیریت پرسنل و ویرایش:</b>", reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "admin_add_staff")
async def adm_add_staff_start(callback: CallbackQuery, state: FSMContext):
    if not check_user_role(callback.from_user.id, "main_admin"):
        await callback.answer("❌ فقط مدیر اصلی مجاز به افزودن پرسنل است!", show_alert=True)
        return
    await state.set_state(AdminForm.add_staff_name)
    kb = cancel_kb("adm_cat_staff")
    await callback.message.edit_text("➕ نام پرسنل جدید را وارد کنید:", reply_markup=kb)
    await callback.answer()

@dp.message(AdminForm.add_staff_name)
async def adm_add_staff_name(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ نام معتبر وارد کنید.")
        return
    await state.update_data(new_sname=message.text.strip())
    await state.set_state(AdminForm.add_staff_phone)
    await message.answer("شماره تماس پرسنل را وارد کنید:")

@dp.message(AdminForm.add_staff_phone)
async def adm_add_staff_phone(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ شماره معتبر وارد کنید.")
        return
    await state.update_data(new_sphone=normalize_persian_numbers(message.text).strip())
    await state.set_state(AdminForm.add_staff_role)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👑 مدیر اصلی (main_admin)", callback_data="role_main_admin")],
        [InlineKeyboardButton(text="💳 واحد مالی (finance)", callback_data="role_finance")],
        [InlineKeyboardButton(text="🛒 مسئول خرید (purchase)", callback_data="role_purchase")],
        [InlineKeyboardButton(text="👤 پرسنل عادی (staff)", callback_data="role_staff")]
    ])
    await message.answer("نقش سازمانی پرسنل را انتخاب کنید:", reply_markup=kb)

@dp.callback_query(AdminForm.add_staff_role, F.data.startswith("role_"))
async def adm_add_staff_role_selected(callback: CallbackQuery, state: FSMContext):
    role = callback.data.split("_", 1)[1]
    await state.update_data(new_srole=role)
    await state.set_state(AdminForm.add_staff_balance)
    await callback.message.edit_text("مانده مرخصی اولیه (روز):")
    await callback.answer()

@dp.message(AdminForm.add_staff_balance)
async def adm_add_staff_balance(message: Message, state: FSMContext):
    try:
        bal = float(normalize_persian_numbers(message.text)) if message.text else 0.0
    except Exception:
        bal = 0.0
    await state.update_data(new_sbal=bal)
    await state.set_state(AdminForm.add_staff_date)
    await message.answer("📅 تاریخ استخدام را با فرمت <code>YYYY/MM/DD</code> وارد کنید (یا <code>-</code> برای تاریخ امروز):", parse_mode="HTML")

@dp.message(AdminForm.add_staff_date)
async def adm_add_staff_save(message: Message, state: FSMContext):
    text_date = message.text.strip() if message.text else "-"
    if text_date in ("امروز", "-"):
        emp_date = get_current_tehran_time().strftime("%Y/%m/%d")
    elif validate_custom_date(text_date):
        emp_date = normalize_jalali_date(text_date)
    else:
        emp_date = get_current_tehran_time().strftime("%Y/%m/%d")

    data = await state.get_data()
    name, phone, role, bal = data.get("new_sname"), data.get("new_sphone"), data.get("new_srole"), data.get("new_sbal")
    
    with get_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO staff_mapping (staff_name, phone_number, is_active, leave_balance, role, employment_date) 
                VALUES (?, ?, 1, ?, ?, ?)
            """, (name, phone, bal, role, emp_date))
            staff_id = cursor.lastrowid
            if bal != 0.0:
                now_str = get_current_tehran_time().strftime("%Y/%m/%d %H:%M")
                cursor.execute("""
                    INSERT INTO leave_ledger (staff_id, staff_name, change_amount, description, registered_by, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (staff_id, name, bal, "مانده مرخصی اولیه", "مدیر اصلی", now_str))
            conn.commit()
            await message.answer(f"✅ پرسنل <b>{html.escape(name)}</b> با موفقیت اضافه شد.", parse_mode="HTML")
        except sqlite3.IntegrityError:
            await message.answer("❌ این نام یا شماره تماس قبلاً در سیستم ثبت شده است.")
    await state.clear()

@dp.callback_query(F.data == "admin_edit_staff_list")
async def admin_edit_staff_list(callback: CallbackQuery):
    if not check_user_role(callback.from_user.id, "main_admin"):
        await callback.answer("❌ فقط مدیر اصلی مجاز به ویرایش پرسنل است!", show_alert=True)
        return
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT staff_id, staff_name FROM staff_mapping WHERE is_active = 1")
        rows = cursor.fetchall()

    if not rows:
        await callback.answer("پرسنل فعالی یافت نشد.", show_alert=True)
        return

    buttons = [[InlineKeyboardButton(text=f"✏️ ویرایش {r[1]}", callback_data=f"editstaff_{r[0]}")] for r in rows]
    buttons.append([InlineKeyboardButton(text="🔙 بازگشت", callback_data="adm_cat_staff")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.edit_text("👤 پرسنل مورد نظر جهت ویرایش را انتخاب کنید:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("editstaff_"))
async def admin_edit_staff_options(callback: CallbackQuery, state: FSMContext):
    staff_id = int(callback.data.split("_")[1])
    await state.update_data(edit_staff_id=staff_id)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ ویرایش نام", callback_data="edfield_staff_name")],
        [InlineKeyboardButton(text="📱 ویرایش شماره تماس", callback_data="edfield_phone_number")],
        [InlineKeyboardButton(text="🛡️ ویرایش نقش", callback_data="edfield_role")],
        [InlineKeyboardButton(text="🌿 ویرایش مانده مرخصی", callback_data="edfield_leave_balance")],
        [InlineKeyboardButton(text="📅 ویرایش تاریخ استخدام", callback_data="edfield_employment_date")],
        [InlineKeyboardButton(text="🔙 بازگشت", callback_data="admin_edit_staff_list")]
    ])
    await callback.message.edit_text("⚙️ کدام بخش از اطلاعات این پرسنل را می‌خواهید ویرایش کنید؟", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("edfield_"))
async def admin_edit_staff_field_chosen(callback: CallbackQuery, state: FSMContext):
    field = callback.data.split("edfield_")[1]
    
    ALLOWED_FIELDS = {"staff_name", "phone_number", "leave_balance", "employment_date"}
    if field not in ALLOWED_FIELDS:
        await callback.answer("فیلد غیرمجاز است.", show_alert=True)
        return

    await state.update_data(edit_field=field)
    await state.set_state(AdminForm.edit_staff_value)
    await callback.message.edit_text(f"✍️ مقدار جدید برای فیلد <code>{field}</code> را ارسال کنید:", parse_mode="HTML")
    await callback.answer()

@dp.message(AdminForm.edit_staff_value)
async def admin_edit_staff_save_value(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ مقدار معتبر وارد کنید.")
        return
    new_val = message.text.strip()
    data = await state.get_data()
    staff_id = data.get("edit_staff_id")
    field = data.get("edit_field")

    ALLOWED_FIELDS = {"staff_name", "phone_number", "leave_balance", "employment_date"}
    if field not in ALLOWED_FIELDS:
        await message.answer("❌ فیلد غیرمجاز است.")
        await state.clear()
        return

    with get_connection() as conn:
        cursor = conn.cursor()
        try:
            if field == "leave_balance":
                new_target_balance = float(normalize_persian_numbers(new_val))
                cursor.execute("SELECT staff_name, leave_balance FROM staff_mapping WHERE staff_id = ?", (staff_id,))
                srow = cursor.fetchone()
                sname, current_balance = srow[0], float(srow[1])
                delta = new_target_balance - current_balance
                
                if delta != 0.0:
                    now_str = get_current_tehran_time().strftime("%Y/%m/%d %H:%M")
                    cursor.execute("""
                        INSERT INTO leave_ledger (staff_id, staff_name, change_amount, description, registered_by, created_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (staff_id, sname, delta, "ویرایش دستی مانده", "مدیر اصلی", now_str))
                    cursor.execute("SELECT COALESCE(SUM(change_amount), 0) FROM leave_ledger WHERE staff_id = ?", (staff_id,))
                    new_balance = float(cursor.fetchone()[0])
                    cursor.execute("UPDATE staff_mapping SET leave_balance = ? WHERE staff_id = ?", (new_balance, staff_id))
            else:
                query = f"UPDATE staff_mapping SET {field} = ? WHERE staff_id = ?"
                cursor.execute(query, (new_val, staff_id))
            conn.commit()
            await message.answer("✅ اطلاعات پرسنل با موفقیت ویرایش شد.")
        except Exception:
            conn.rollback()
            await message.answer("❌ خطا در ویرایش اطلاعات.")
    await state.clear()

@dp.callback_query(F.data == "admin_deactivate_staff_list")
async def admin_deactivate_list(callback: CallbackQuery):
    if not check_user_role(callback.from_user.id, "main_admin"):
        await callback.answer("❌ فقط مدیر اصلی مجاز به غیرفعال‌سازی پرسنل است!", show_alert=True)
        return
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT staff_id, staff_name FROM staff_mapping WHERE is_active = 1")
        rows = cursor.fetchall()

    if not rows:
        await callback.answer("پرسنل فعالی یافت نشد.", show_alert=True)
        return

    buttons = [[InlineKeyboardButton(text=f"🚫 غیرفعال کردن {r[1]}", callback_data=f"deact_{r[0]}")] for r in rows]
    buttons.append([InlineKeyboardButton(text="🔙 بازگشت", callback_data="adm_cat_staff")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.edit_text("انتخاب پرسنل جهت غیرفعال‌سازی:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("deact_"))
async def admin_deactivate_execute(callback: CallbackQuery):
    if not check_user_role(callback.from_user.id, "main_admin"):
        await callback.answer("❌ دسترسی غیرمجاز!", show_alert=True)
        return
    staff_id = int(callback.data.split("_")[1])
    now_str = get_current_tehran_time().strftime("%Y/%m/%d")
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE staff_mapping SET is_active = 0, telegram_user_id = NULL, deactivation_date = ? WHERE staff_id = ?", (now_str, staff_id))
        cursor.execute("UPDATE user_assets SET is_active = 0 WHERE staff_id = ?", (staff_id,))
        conn.commit()
    await callback.message.edit_text(f"✅ پرسنل غیرفعال شد. تاریخ تسویه ثبت گردید: <code>{now_str}</code>", reply_markup=None, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "admin_list_staff")
async def admin_list_staff(callback: CallbackQuery):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT staff_name, phone_number, is_active, leave_balance, role, employment_date, deactivation_date FROM staff_mapping")
        rows = cursor.fetchall()

    text = "📋 <b>لیست پرسنل سامانه:</b>\n\n"
    for r in rows:
        status = "🟢 فعال" if r[2] == 1 else "🔴 غیرفعال"
        emp = r[5] if r[5] else "نامشخص"
        deact = f" | خروج: {r[6]}" if r[6] else ""
        chunk = f"{status} <b>{html.escape(r[0])}</b> | <code>{r[4]}</code>\n📱 پ: <code>{r[1]}</code> | استخدام: {emp}{deact} | مانده: {r[3]} روز\n\n"
        if len(text) + len(chunk) > 4000:
            await callback.message.answer(text, parse_mode="HTML")
            text = ""
        text += chunk
    if text:
        await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "admin_assign_asset")
async def admin_assign_asset_menu(callback: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ واگذاری تجهیز جدید به پرسنل", callback_data="asgn_new_step1")],
        [InlineKeyboardButton(text="✏️ ویرایش یا مشاهده اموال تحویلی", callback_data="asgn_list_active")],
        [InlineKeyboardButton(text="🔙 بازگشت به پنل", callback_data="admin_panel")]
    ])
    await callback.message.edit_text("🚗 <b>مدیریت اموال و تجهیزات پرسنل</b>", reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "asgn_new_step1")
async def admin_assign_asset_start(callback: CallbackQuery):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT staff_id, staff_name FROM staff_mapping WHERE is_active = 1")
        rows = cursor.fetchall()
    if not rows:
        await callback.answer("پرسنل فعالی یافت نشد.", show_alert=True)
        return
    buttons = [[InlineKeyboardButton(text=r[1], callback_data=f"asgnuser_{r[0]}")] for r in rows]
    buttons.append([InlineKeyboardButton(text="🔙 بازگشت", callback_data="admin_assign_asset")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    date_now = get_current_tehran_time().strftime("%Y/%m/%d")
    await callback.message.edit_text(f"👤 پرسنل مورد نظر جهت واگذاری اموال را انتخاب کنید:\n📅 تاریخ واگذاری: <code>{date_now}</code>", reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data.startswith("asgnuser_"))
async def admin_asgn_user(callback: CallbackQuery, state: FSMContext):
    staff_id = int(callback.data.split("_")[1])
    await state.update_data(target_staff_id=staff_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚗 خودروی سازمانی", callback_data="asgntype_car")],
        [InlineKeyboardButton(text="⛽ کارت سوخت", callback_data="asgntype_fuel")],
        [InlineKeyboardButton(text="💳 کارت‌خوان (POS)", callback_data="asgntype_pos")],
        [InlineKeyboardButton(text="🖨️ پرینتر جیبی", callback_data="asgntype_printer")],
        [InlineKeyboardButton(text="🔙 بازگشت", callback_data="admin_assign_asset")]
    ])
    await callback.message.edit_text("نوع تجهیز را انتخاب کنید:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("asgntype_"))
async def admin_asgn_type(callback: CallbackQuery, state: FSMContext):
    atype_key = callback.data.split("_", 1)[1]
    mapping = {
        "car": "خودروی سازمانی",
        "fuel": "کارت سوخت",
        "pos": "کارت‌خوان",
        "printer": "پرینتر جیبی"
    }
    atype = mapping.get(atype_key, "سایر")
    await state.update_data(asset_type=atype)
    
    if atype_key == "car":
        await state.set_state(AdminForm.admin_asgn_temp_code)
        await callback.message.edit_text("🚗 1️⃣ کد خودرو را وارد کنید:")
    elif atype_key == "fuel":
        await state.set_state(AdminForm.admin_asgn_temp_fcode)
        await callback.message.edit_text("⛽ 1️⃣ کد کارت سوخت را وارد کنید:")
    elif atype_key == "pos":
        await state.set_state(AdminForm.admin_asgn_temp_pcode)
        await callback.message.edit_text("💳 1️⃣ کد دستگاه پوز را وارد کنید:")
    elif atype_key == "printer":
        await state.set_state(AdminForm.admin_asgn_temp_prcode)
        await callback.message.edit_text("🖨️ 1️⃣ کد پرینتر جیبی را وارد کنید:")
    await callback.answer()

@dp.message(AdminForm.admin_asgn_temp_code)
async def adm_car_s2(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ کد معتبر وارد کنید.")
        return
    await state.update_data(asgn_car_code=message.text.strip())
    await state.set_state(AdminForm.admin_asgn_temp_plate)
    await message.answer("🚗 2️⃣ پلاک خودرو را وارد کنید:")

@dp.message(AdminForm.admin_asgn_temp_plate)
async def adm_car_s3(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ پلاک معتبر وارد کنید.")
        return
    await state.update_data(asgn_car_plate=message.text.strip())
    await state.set_state(AdminForm.admin_asgn_temp_type)
    await message.answer("🚗 3️⃣ نوع خودرو را وارد کنید:")

@dp.message(AdminForm.admin_asgn_temp_type)
async def adm_car_s4(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ نوع خودرو معتبر وارد کنید.")
        return
    await state.update_data(asgn_car_type=message.text.strip())
    await state.set_state(AdminForm.admin_asgn_temp_km)
    await message.answer("🚗 4️⃣ کیلومتر تحویلی را وارد کنید:")

@dp.message(AdminForm.admin_asgn_temp_km)
async def adm_car_s5(message: Message, state: FSMContext):
    clean_km = normalize_persian_numbers(message.text).strip() if message.text else ""
    if not clean_km.isdigit():
        await message.answer("❌ کیلومتر باید عدد باشد:")
        return
    await state.update_data(asgn_car_km=clean_km)
    await state.set_state(AdminForm.admin_asgn_temp_desc)
    await message.answer("🚗 5️⃣ توضیحات تکمیلی (اگر ندارد <code>-</code>):", parse_mode="HTML")

@dp.message(AdminForm.admin_asgn_temp_desc)
async def adm_car_save_final(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ توضیحات معتبر وارد کنید.")
        return
    desc = message.text.strip()
    data = await state.get_data()
    staff_id = data.get("target_staff_id")
    date_now = get_current_tehran_time().strftime("%Y/%m/%d")
    details = f"تاریخ واگذاری: {date_now} | کد: {data.get('asgn_car_code')} | پلاک: {data.get('asgn_car_plate')} | نوع: {data.get('asgn_car_type')} | کیلومتر: {data.get('asgn_car_km')} | توضیحات: {desc}"
    await save_admin_asset(message, state, staff_id, "خودروی سازمانی", details)

@dp.message(AdminForm.admin_asgn_temp_fcode)
async def adm_fuel_s2(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ کد معتبر وارد کنید.")
        return
    await state.update_data(asgn_fcode=message.text.strip())
    await state.set_state(AdminForm.admin_asgn_temp_fpass)
    await message.answer("⛽ 2️⃣ رمز کارت سوخت را وارد کنید:")

@dp.message(AdminForm.admin_asgn_temp_fpass)
async def adm_fuel_s3(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ رمز معتبر وارد کنید.")
        return
    await state.update_data(asgn_fpass=message.text.strip())
    await state.set_state(AdminForm.admin_asgn_temp_l1500)
    await message.answer("⛽ 3️⃣ میزان لیتر سهمیه <b>۱۵۰۰ تومانی</b> ماهیانه را وارد کنید:", parse_mode="HTML")

@dp.message(AdminForm.admin_asgn_temp_l1500)
async def adm_fuel_s4(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ مقدار معتبر وارد کنید.")
        return
    await state.update_data(asgn_l1500=message.text.strip())
    await state.set_state(AdminForm.admin_asgn_temp_l3000)
    await message.answer("⛽ 4️⃣ میزان لیتر سهمیه <b>۳۰۰۰ تومانی</b> ماهیانه را وارد کنید:", parse_mode="HTML")

@dp.message(AdminForm.admin_asgn_temp_l3000)
async def adm_fuel_s5(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ مقدار معتبر وارد کنید.")
        return
    await state.update_data(asgn_l3000=message.text.strip())
    await state.set_state(AdminForm.admin_asgn_temp_l10000)
    await message.answer("⛽ 5️⃣ میزان لیتر سهمیه <b>۱۰,۰۰۰ تومانی</b> ماهیانه را وارد کنید:", parse_mode="HTML")

@dp.message(AdminForm.admin_asgn_temp_l10000)
async def adm_fuel_save_final(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ مقدار معتبر وارد کنید.")
        return
    l10000 = message.text.strip()
    data = await state.get_data()
    staff_id = data.get("target_staff_id")
    date_now = get_current_tehran_time().strftime("%Y/%m/%d")
    details = f"تاریخ واگذاری: {date_now} | کد کارت سوخت: {data.get('asgn_fcode')} | رمز: [محفوظ و مختص پرسنل] | ۱۵۰۰ تومانی: {data.get('asgn_l1500')} | ۳۰۰۰ تومانی: {data.get('asgn_l3000')} | ۱۰,۰۰۰ تومانی: {l10000}"
    encrypted_pass = encrypt_data(data.get('asgn_fpass'))
    await save_admin_asset(message, state, staff_id, "کارت سوخت", details, encrypted_password=encrypted_pass)

@dp.message(AdminForm.admin_asgn_temp_pcode)
async def adm_pos_s2(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ کد معتبر وارد کنید.")
        return
    await state.update_data(asgn_pcode=message.text.strip())
    await state.set_state(AdminForm.admin_asgn_temp_pbank)
    await message.answer("💳 2️⃣ نام بانک را وارد کنید:")

@dp.message(AdminForm.admin_asgn_temp_pbank)
async def adm_pos_s3(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ نام بانک معتبر وارد کنید.")
        return
    await state.update_data(asgn_pbank=message.text.strip())
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ دارد", callback_data="admposchg_yes"),
         InlineKeyboardButton(text="❌ ندارد", callback_data="admposchg_no")]
    ])
    await state.set_state(AdminForm.admin_asgn_temp_pcharger)
    await message.answer("💳 3️⃣ آیا دستگاه پوز <b>شارژر</b> دارد؟", reply_markup=kb, parse_mode="HTML")

@dp.callback_query(AdminForm.admin_asgn_temp_pcharger, F.data.startswith("admposchg_"))
async def adm_pos_save_final(callback: CallbackQuery, state: FSMContext):
    charger = "دارد" if callback.data.split("_")[1] == "yes" else "ندارد"
    data = await state.get_data()
    staff_id = data.get("target_staff_id")
    date_now = get_current_tehran_time().strftime("%Y/%m/%d")
    details = f"تاریخ واگذاری: {date_now} | کد پوز: {data.get('asgn_pcode')} | بانک: {data.get('asgn_pbank')} | شارژر: {charger}"
    try:
        await callback.message.edit_text(callback.message.text + f"\n\nشارژر: {charger}")
    except Exception:
        pass
    await save_admin_asset(callback.message, state, staff_id, "کارت‌خوان", details)
    await callback.answer()

@dp.message(AdminForm.admin_asgn_temp_prcode)
async def adm_pr_s2(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ کد معتبر وارد کنید.")
        return
    await state.update_data(asgn_prcode=message.text.strip())
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ دارد", callback_data="admprchg_yes"),
         InlineKeyboardButton(text="❌ ندارد", callback_data="admprchg_no")]
    ])
    await state.set_state(AdminForm.admin_asgn_temp_prcharger)
    await message.answer("🖨️ 2️⃣ آیا پرینتر <b>شارژر</b> دارد؟", reply_markup=kb, parse_mode="HTML")

@dp.callback_query(AdminForm.admin_asgn_temp_prcharger, F.data.startswith("admprchg_"))
async def adm_pr_save_final(callback: CallbackQuery, state: FSMContext):
    charger = "دارد" if callback.data.split("_")[1] == "yes" else "ندارد"
    data = await state.get_data()
    staff_id = data.get("target_staff_id")
    date_now = get_current_tehran_time().strftime("%Y/%m/%d")
    details = f"تاریخ واگذاری: {date_now} | کد پرینتر: {data.get('asgn_prcode')} | شارژر: {charger}"
    try:
        await callback.message.edit_text(callback.message.text + f"\n\nشارژر: {charger}")
    except Exception:
        pass
    await save_admin_asset(callback.message, state, staff_id, "پرینتر جیبی", details)
    await callback.answer()

async def save_admin_asset(message_obj, state: FSMContext, staff_id: int, atype: str, details: str, encrypted_password=None):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT staff_name, telegram_user_id FROM staff_mapping WHERE staff_id = ?", (staff_id,))
        row = cursor.fetchone()
        staff_name = row[0] if row else "نامشخص"
        telegram_user_id = row[1] if row else None
        now_str = get_current_tehran_time().strftime("%Y/%m/%d %H:%M")

        cursor.execute("""
            INSERT INTO user_assets (staff_id, staff_name, asset_type, details, is_active, approval_status, assigned_at, encrypted_password)
            VALUES (?, ?, ?, ?, 1, 'در انتظار تأیید پرسنل ⏳', ?, ?)
        """, (staff_id, staff_name, atype, details, now_str, encrypted_password))
        asset_id = cursor.lastrowid
        conn.commit()

    target_msg = message_obj if isinstance(message_obj, Message) else message_obj.message
    await target_msg.answer(f"✅ مال ({atype}) به نام <b>{html.escape(staff_name)}</b> ثبت شد و پیام تایید برای او ارسال گردید.", parse_mode="HTML")
    
    if telegram_user_id:
        try:
            user_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ تحویل گرفتم و تأیید می‌کنم", callback_data=f"confirmasset_{asset_id}")]
            ])
            await bot.send_message(
                chat_id=telegram_user_id, 
                text=f"📦 <b>تجهیز جدید به نام شما ثبت شد:</b>\n\nنوع: {html.escape(atype)}\nمشخصات: {html.escape(details)}\n\nلطفاً پس از دریافت فیزیکی، روی دکمه زیر کلیک کنید:", 
                reply_markup=user_kb,
                parse_mode="HTML"
            )
        except Exception:
            pass
    await state.clear()

@dp.callback_query(F.data.startswith("confirmasset_"))
async def user_confirm_asset_receipt(callback: CallbackQuery):
    aid = int(callback.data.split("confirmasset_")[1])
    user_id = callback.from_user.id
    staff_id, _, _, _, _, _ = get_staff_info_by_telegram_id(user_id)

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT staff_id, approval_status FROM user_assets WHERE id = ?", (aid,))
        row = cursor.fetchone()
        if not row or row[0] != staff_id:
            await callback.answer("رکورد مال معتبر نیست یا متعلق به شما نیست.", show_alert=True)
            return

        if "تأیید قطعی" in row[1]:
            await callback.answer("این تجهیز قبلاً توسط شما تأیید شده است.", show_alert=True)
            return

        confirm_date = get_current_tehran_time().strftime("%Y/%m/%d %H:%M")
        cursor.execute("UPDATE user_assets SET approval_status = ? WHERE id = ?", (f"تأیید قطعی توسط پرسنل ✅ ({confirm_date})", aid))
        conn.commit()

    await callback.message.edit_text(callback.message.text + f"\n\n<b>✅ تحویل این تجهیز توسط شما در تاریخ {confirm_date} تأیید شد.</b>", reply_markup=None, parse_mode="HTML")
    await callback.answer("تأیید دریافت با موفقیت ثبت شد.")

@dp.callback_query(F.data == "asgn_list_active")
async def admin_list_active_assets(callback: CallbackQuery):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, staff_name, asset_type, details, is_active, approval_status, encrypted_password FROM user_assets ORDER BY id DESC LIMIT 20")
        rows = cursor.fetchall()

    if not rows:
        await callback.answer("هیچ اموالی ثبت نشده است.", show_alert=True)
        return

    for r in rows:
        aid, sname, atype, details, active, approval_status, enc_pass = r
        status = "🟢 فعال" if active == 1 else "🔴 عودت داده شده"
        pass_info = f"\n🔑 رمز عبور/کارت: <code>{decrypt_data(enc_pass)}</code>" if enc_pass else ""
        text = f"🆔 شناسه مال: {aid}\n👤 پرسنل: {html.escape(sname)}\n📦 نوع: {html.escape(atype)}\n📝 جزئیات: {html.escape(details)}{pass_info}\n📌 وضعیت: {status} | تایید: {approval_status}"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ ویرایش جزئیات", callback_data=f"asgnedit_{aid}"),
             InlineKeyboardButton(text="🗑️ حذف/غیرفعال (عودت)", callback_data=f"asgndel_{aid}")]
        ])
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data.startswith("asgnedit_"))
async def admin_edit_asset_start(callback: CallbackQuery, state: FSMContext):
    aid = int(callback.data.split("asgnedit_")[1])
    await state.update_data(editing_asset_id=aid)
    await state.set_state(AdminForm.edit_asset_details)
    await callback.message.edit_text("✍️ جزئیات جدید را وارد کنید:")
    await callback.answer()

@dp.message(AdminForm.edit_asset_details)
async def admin_edit_asset_save(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ جزئیات معتبر وارد کنید.")
        return
    new_details = message.text.strip()
    data = await state.get_data()
    aid = data.get("editing_asset_id")

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE user_assets SET details = ? WHERE id = ?", (new_details, aid))
        conn.commit()

    await message.answer("✅ مشخصات مال با موفقیت ویرایش شد.")
    await state.clear()

@dp.callback_query(F.data.startswith("asgndel_"))
async def admin_delete_asset(callback: CallbackQuery):
    aid = int(callback.data.split("asgndel_")[1])
    date_now = get_current_tehran_time().strftime("%Y/%m/%d")
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE user_assets SET is_active = 0, return_date = ? WHERE id = ?", (date_now, aid))
        conn.commit()
    try:
        await callback.message.edit_text(callback.message.text + f"\n\n<b>[غیرفعال و عودت داده شد - تاریخ: {date_now}]</b>", reply_markup=None, parse_mode="HTML")
    except Exception:
        pass
    await callback.answer("مال عودت و غیرفعال شد.")

@dp.callback_query(F.data == "adm_cat_excel")
async def admin_category_excel(callback: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 اکسل درخواست‌ها (Requests)", callback_data="xcl_req")],
        [InlineKeyboardButton(text="👥 اکسل پرسنل و تاریخ‌ها (Staff)", callback_data="xcl_staff")],
        [InlineKeyboardButton(text="🚗 اکسل اموال و تجهیزات (Assets)", callback_data="xcl_assets")],
        [InlineKeyboardButton(text="🛡️ اکسل بیمه ناوگان (Insurances)", callback_data="xcl_ins")],
        [InlineKeyboardButton(text="🔙 بازگشت به پنل", callback_data="admin_panel")]
    ])
    await callback.message.edit_text("📊 <b>انتخاب گزارش اکسل تخصصی:</b>", reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data.startswith("xcl_"))
async def send_specific_excel(callback: CallbackQuery):
    target = callback.data.split("xcl_")[1]
    with get_connection() as conn:
        sheet_configs = {
            "req": ("requests", "Requests_Report.xlsx", "گزارش درخواست‌ها", {
                "id": "شناسه سیستمی",
                "req_code": "کد درخواست",
                "telegram_user_id": "شناسه کاربر",
                "user_name": "نام پرسنل",
                "telegram_info": "اطلاعات تلگرام",
                "request_type": "نوع درخواست",
                "col1": "اطلاعات اصلی / مبلغ / تاریخ",
                "col2": "جزئیات اول / شهر / پلاک",
                "col3": "جزئیات دوم / کارت / توضیحات",
                "amount": "مبلغ عددی",
                "start_date": "تاریخ شروع",
                "end_date": "تاریخ پایان",
                "location": "مقدار عددی / روز کسر",
                "status": "وضعیت نهایی",
                "created_at": "تاریخ و ساعت ثبت",
                "month_tag": "برچسب ماه",
                "rejection_reason": "دلیل رد درخواست"
            }),
            "staff": ("staff_mapping", "Staff_Mapping_Report.xlsx", "لیست پرسنل", {
                "staff_id": "شناسه پرسنلی",
                "telegram_user_id": "شناسه تلگرام",
                "staff_name": "نام و نام خانوادگی",
                "phone_number": "شماره تماس",
                "is_active": "وضعیت فعالیت",
                "leave_balance": "مانده مرخصی (روز)",
                "role": "نقش سازمانی",
                "employment_date": "تاریخ استخدام",
                "deactivation_date": "تاریخ تسویه/خروج"
            }),
            "assets": ("user_assets", "User_Assets_Report.xlsx", "اموال تحویلی پرسنل", {
                "id": "شناسه مال",
                "staff_id": "شناسه پرسنلی",
                "staff_name": "نام پرسنل",
                "asset_type": "نوع تجهیز",
                "details": "جزئیات و مشخصات کامل",
                "is_active": "وضعیت تحویل",
                "approval_status": "وضعیت تایید پرسنل",
                "return_date": "تاریخ عودت",
                "assigned_at": "تاریخ واگذاری"
            }),
            "ins": ("vehicle_insurances", "Vehicle_Insurances_Report.xlsx", "بیمه‌نامه ناوگان", {
                "id": "شناسه بیمه",
                "car_code": "کد خودرو",
                "car_name": "نام خودرو",
                "plate_number": "شماره پلاک",
                "insurance_company": "شرکت بیمه",
                "third_party_date": "سررسید شخص ثالث",
                "body_date": "سررسید بیمه بدنه"
            })
        }

        if target not in sheet_configs:
            await callback.answer("گزارش نامعتبر است.", show_alert=True)
            return

        table_name, filename, sheet_title, mapping = sheet_configs[target]
        cols_to_fetch = list(mapping.keys())
        cols_query = ", ".join(cols_to_fetch)
        df = pd.read_sql_query(f"SELECT {cols_query} FROM {table_name}", conn)

    df = df.rename(columns=mapping)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name=sheet_title, index=False)
    output.seek(0)

    file_bytes = BufferedInputFile(output.getvalue(), filename=filename)
    await callback.message.answer_document(file_bytes, caption=f"📊 گزارش تخصصی اکسل: {filename}")
    await callback.answer()

@dp.callback_query(F.data == "admin_get_backup")
async def admin_backup_cb(callback: CallbackQuery):
    if os.path.exists(DB_PATH):
        await callback.message.answer_document(FSInputFile(DB_PATH), caption="📦 پشتیبان دیتابیس")
        await callback.answer()

@dp.callback_query(F.data == "admin_selective_reset_menu")
async def admin_selective_reset_menu(callback: CallbackQuery):
    if not check_user_role(callback.from_user.id, "main_admin"):
        await callback.answer("❌ فقط مدیر اصلی مجاز به پاکسازی دیتابیس است!", show_alert=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑️ پاک کردن کل تاریخچه درخواست‌ها", callback_data="confreset_requests")],
        [InlineKeyboardButton(text="🚗 پاک کردن اموال و بیمه‌های ناوگان", callback_data="confreset_assets")],
        [InlineKeyboardButton(text="🌿 صفر کردن تمام مانده مرخصی‌ها", callback_data="confreset_leaves")],
        [InlineKeyboardButton(text="⚠️ ریست جامع (همه جدول‌ها به جز پرسنل)", callback_data="confreset_all_except_staff")],
        [InlineKeyboardButton(text="🔙 بازگشت به پنل", callback_data="admin_panel")]
    ])
    await callback.message.edit_text("⚙️ <b>ریست انتخابی دیتابیس</b>\n\nلطفاً بخش مورد نظر برای پاکسازی را انتخاب کنید:", reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data.startswith("confreset_"))
async def admin_confirm_reset_prompt(callback: CallbackQuery):
    if not check_user_role(callback.from_user.id, "main_admin"):
        await callback.answer("❌ دسترسی غیرمجاز!", show_alert=True)
        return
    target = callback.data.split("confreset_")[1]
    
    titles = {
        "requests": "پاک کردن کل تاریخچه درخواست‌ها",
        "assets": "پاک کردن اموال و بیمه‌های ناوگان",
        "leaves": "صفر کردن تمام مانده مرخصی‌ها و دفتر کل",
        "all_except_staff": "ریست جامع (همه جدول‌ها به جز پرسنل)"
    }
    
    action_title = titles.get(target, "این عملیات")
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ بله، کاملاً مطمئنم", callback_data=f"doreset_{target}"),
            InlineKeyboardButton(text="❌ انصراف", callback_data="admin_selective_reset_menu")
        ]
    ])
    
    await callback.message.edit_text(
        f"⚠️ <b>هشدار جدی:</b>\nآیا از انجام عملیات <b>«{action_title}»</b> اطمینان کامل دارید؟ قبل از پاکسازی نسخه پشتیبان ارسال خواهد شد.",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("doreset_"))
async def admin_execute_selective_reset(callback: CallbackQuery, state: FSMContext):
    if not check_user_role(callback.from_user.id, "main_admin"):
        await callback.answer("❌ دسترسی غیرمجاز!", show_alert=True)
        return

    try:
        if os.path.exists(DB_PATH):
            await callback.message.answer_document(FSInputFile(DB_PATH), caption="📦 نسخه پشتیبان خودکار پیش از پاکسازی دیتابیس")
    except Exception:
        pass

    target = callback.data.split("doreset_")[1]
    msg = ""
    with get_connection() as conn:
        cursor = conn.cursor()
        try:
            if target == "requests":
                cursor.execute("DROP TABLE IF EXISTS requests")
                msg = "✅ جدول درخواست‌ها با موفقیت پاک و بازسازی شد."
            elif target == "assets":
                cursor.execute("DROP TABLE IF EXISTS user_assets")
                cursor.execute("DROP TABLE IF EXISTS vehicle_insurances")
                msg = "✅ اطلاعات اموال و بیمه‌های ناوگان با موفقیت پاک شدند."
            elif target == "leaves":
                cursor.execute("UPDATE staff_mapping SET leave_balance = 0.0")
                cursor.execute("DROP TABLE IF EXISTS leave_ledger")
                msg = "✅ تمام مانده مرخصی‌ها صفر شدند و دفتر کل مرخصی پاک شد."
            elif target == "all_except_staff":
                cursor.execute("DROP TABLE IF EXISTS requests")
                cursor.execute("DROP TABLE IF EXISTS leave_ledger")
                cursor.execute("DROP TABLE IF EXISTS user_assets")
                cursor.execute("DROP TABLE IF EXISTS vehicle_insurances")
                cursor.execute("DROP TABLE IF EXISTS holidays")
                msg = "✅ ریست جامع انجام شد. تمامی درخواست‌ها، اموال و بیمه‌ها پاک شدند، اما <b>اطلاعات پرسنل حفظ شد</b>."
                
            conn.commit()
        except Exception:
            conn.rollback()
            msg = "❌ خطا در پاکسازی دیتابیس."

    init_db()
    await callback.message.edit_text(msg, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 بازگشت به پنل مدیریت", callback_data="admin_panel")]]), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "admin_add_insurance")
async def admin_insurance_start(callback: CallbackQuery, state: FSMContext):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT details FROM user_assets WHERE asset_type = 'خودروی سازمانی' AND is_active = 1")
        rows = cursor.fetchall()

    buttons = []
    for r in rows:
        detail_text = r[0]
        match_code = re.search(r'کد:\s*([^|]+)', detail_text)
        car_code_val = match_code.group(1).strip() if match_code else detail_text[:20]
        buttons.append([InlineKeyboardButton(text=f"🚗 انتخاب خودرو: {car_code_val}", callback_data=f"inselcar_{car_code_val}")])
    
    buttons.append([InlineKeyboardButton(text="➕ ورود کد/خودروی جدید", callback_data="inselcar_NEW")])
    buttons.append([InlineKeyboardButton(text="🔙 بازگشت", callback_data="admin_panel")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)

    await callback.message.edit_text("🛡️ <b>ثبت بیمه‌نامه خودرو</b>\n\nلطفاً خودروی مورد نظر را از لیست اموال انتخاب کنید:", reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data.startswith("inselcar_"))
async def admin_insurance_car_selected(callback: CallbackQuery, state: FSMContext):
    val = callback.data.split("inselcar_")[1]
    if val == "NEW":
        await state.set_state(AdminForm.ins_car_code)
        await callback.message.edit_text("🛡️ <b>ثبت بیمه خودرو جدید</b>\n\n1️⃣ کد خودرو را وارد کنید:", parse_mode="HTML")
    else:
        await state.update_data(ins_code=val, ins_car="خودروی سازمانی", ins_plate="-")
        await state.set_state(AdminForm.ins_company)
        await callback.message.edit_text(f"🛡️ برای خودرو با کد <code>{val}</code>:\n\n2️⃣ نام شرکت بیمه را وارد کنید:", parse_mode="HTML")
    await callback.answer()

@dp.message(AdminForm.ins_car_code)
async def admin_ins_code(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ کد معتبر وارد کنید.")
        return
    await state.update_data(ins_code=message.text.strip())
    await state.set_state(AdminForm.ins_car_name)
    await message.answer("2️⃣ نام خودرو:")

@dp.message(AdminForm.ins_car_name)
async def admin_ins_car_name(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ نام خودرو معتبر وارد کنید.")
        return
    await state.update_data(ins_car=message.text.strip())
    await state.set_state(AdminForm.ins_plate)
    await message.answer("3️⃣ پلاک خودرو:")

@dp.message(AdminForm.ins_plate)
async def admin_ins_plate(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ پلاک معتبر وارد کنید.")
        return
    await state.update_data(ins_plate=message.text.strip())
    await state.set_state(AdminForm.ins_company)
    await message.answer("4️⃣ نام شرکت بیمه:")

@dp.message(AdminForm.ins_company)
async def admin_ins_company(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ شرکت بیمه معتبر وارد کنید.")
        return
    await state.update_data(ins_company=message.text.strip())
    await state.set_state(AdminForm.ins_third)
    await message.answer("5️⃣ سررسید بیمه شخص ثالث (<code>YYYY/MM/DD</code>):", parse_mode="HTML")

@dp.message(AdminForm.ins_third)
async def admin_ins_third(message: Message, state: FSMContext):
    text_date = normalize_jalali_date(message.text) if message.text else ""
    if not validate_custom_date(text_date):
        await message.answer("❌ فرمت تاریخ نامعتبر است:")
        return
    await state.update_data(ins_third=text_date)
    await state.set_state(AdminForm.ins_body)
    await message.answer("6️⃣ سررسید بیمه بدنه (<code>YYYY/MM/DD</code>) (اگر ندارد <code>-</code>):", parse_mode="HTML")

@dp.message(AdminForm.ins_body)
async def admin_ins_body_save(message: Message, state: FSMContext):
    text_date = message.text.strip() if message.text else "-"
    if text_date != "-":
        text_date = normalize_jalali_date(text_date)
        if not validate_custom_date(text_date):
            await message.answer("❌ تاریخ نامعتبر است:")
            return
    body_date = text_date
    data = await state.get_data()
    
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO vehicle_insurances (car_code, car_name, plate_number, insurance_company, third_party_date, body_date) 
            VALUES (?, ?, ?, ?, ?, ?)
        """, (data.get("ins_code"), data.get("ins_car"), data.get("ins_plate"), data.get("ins_company"), data.get("ins_third"), body_date))
        conn.commit()

    success_msg = f"🛡️ <b>ثبت موفق بیمه خودرو</b>\n\n🚗 کد: {html.escape(data.get('ins_code'))}\n📌 خودرو: {html.escape(data.get('ins_car'))} ({html.escape(data.get('ins_plate'))})\n🏢 بیمه: {html.escape(data.get('ins_company'))}\n📅 ثالث: {html.escape(data.get('ins_third'))}\n📅 بدنه: {html.escape(body_date)}"
    await message.answer(success_msg, parse_mode="HTML")
    try:
        await bot.send_message(chat_id=GROUP_ID, message_thread_id=TOPIC_INSURANCE, text=success_msg, parse_mode="HTML")
    except Exception:
        pass
    await state.clear()

@dp.callback_query(F.data.startswith("approve_") | F.data.startswith("reject_") | F.data.startswith("paid_") | F.data.startswith("bought_"))
async def handle_request_decision(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    data = callback.data or ""
    action, sep, raw_req_id = data.partition("_")
    if not sep or not raw_req_id.isdigit():
        await callback.answer("شناسه درخواست نامعتبر است.", show_alert=True)
        return
    req_id = int(raw_req_id)

    if action in ("approve", "reject") and not check_user_role(user_id, "main_admin"):
        await callback.answer("❌ فقط مدیر اصلی مجاز به تأیید یا رد نهایی درخواست است!", show_alert=True)
        return
    if action == "paid" and not (check_user_role(user_id, "finance") or check_user_role(user_id, "main_admin")):
        await callback.answer("فقط واحد مالی یا مدیر اصلی مجاز به ثبت پرداخت است.", show_alert=True)
        return
    if action == "bought" and not (check_user_role(user_id, "purchase") or check_user_role(user_id, "main_admin")):
        await callback.answer("فقط مسئول خرید مجاز به ثبت خرید است.", show_alert=True)
        return

    with get_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT telegram_user_id, user_name, request_type, req_code, col1, col2, col3, sensitive_data, location, created_at, status, admin_chat_id, admin_msg_id FROM requests WHERE id = ?", (req_id,))
            row = cursor.fetchone()
            
            if not row and callback.message and (callback.message.text or callback.message.caption):
                msg_content = callback.message.text or callback.message.caption
                code_match = re.search(r'(REQ-\d{4}-\d{5})', msg_content)
                if code_match:
                    extracted_code = code_match.group(1)
                    cursor.execute("SELECT telegram_user_id, user_name, request_type, req_code, col1, col2, col3, sensitive_data, location, created_at, status, admin_chat_id, admin_msg_id FROM requests WHERE req_code = ?", (extracted_code,))
                    row = cursor.fetchone()

            if not row:
                await callback.answer("❌ درخواست پیدا نشد.", show_alert=True)
                return

            target_telegram_user_id, user_name, req_type, req_code, col1, col2, col3, sensitive_data, location_val, created_at, status, admin_chat_id, admin_msg_id = row

            if action == "reject":
                if "تأیید شده قطعی" in status or "رد شده" in status or "لغو شده" in status:
                    await callback.answer("این درخواست قبلاً تعیین تکلیف شده است.", show_alert=True)
                    return
                await state.update_data(rejecting_req_id=req_id)
                await state.set_state(AdminForm.rejection_reason)
                await callback.message.answer("❌ لطفاً <b>دلیل رد درخواست</b> را بنویسید:", parse_mode="HTML")
                await callback.answer()
                return

            if action == "approve":
                cursor.execute("UPDATE requests SET status = '✅ تأیید شده قطعی' WHERE id = ? AND status LIKE '%در انتظار%'", (req_id,))
                if cursor.rowcount == 0:
                    await callback.answer("این درخواست قبلاً تعیین تکلیف شده است.", show_alert=True)
                    return

                new_status = "✅ تأیید شده قطعی"
                
                target_staff_id = None
                cursor.execute("SELECT staff_id FROM staff_mapping WHERE telegram_user_id = ?", (target_telegram_user_id,))
                s_row = cursor.fetchone()
                if s_row:
                    target_staff_id = s_row[0]

                if req_type == "مرخصی" and location_val and str(location_val).replace('.', '', 1).isdigit():
                    days_num = float(location_val)
                    if days_num > 0 and target_staff_id and col1 and "استحقاقی" in col1:
                        now_str = get_current_tehran_time().strftime("%Y/%m/%d %H:%M")
                        description = f"ثبت بابت مرخصی استحقاقی تایید شده ({req_code})"
                        cursor.execute("SELECT 1 FROM leave_ledger WHERE staff_id = ? AND description = ? LIMIT 1", (target_staff_id, description))
                        if not cursor.fetchone():
                            cursor.execute("INSERT INTO leave_ledger (staff_id, staff_name, change_amount, description, registered_by, created_at) VALUES (?, ?, ?, ?, ?, ?)", (target_staff_id, user_name, -days_num, description, "مدیر اصلی", now_str))
                            cursor.execute("SELECT COALESCE(SUM(change_amount), 0) FROM leave_ledger WHERE staff_id = ?", (target_staff_id,))
                            new_balance = float(cursor.fetchone()[0])
                            cursor.execute("UPDATE staff_mapping SET leave_balance = ? WHERE staff_id = ?", (new_balance, target_staff_id))

                if req_type == "تحویل اموال" and target_staff_id:
                    asset_type_val = location_val if location_val else "سایر تجهیزات"
                    details_val = f"ثبت از طریق درخواست پرسنل ({req_code}) | {col1} | {col2} | {col3}"
                    now_str = get_current_tehran_time().strftime("%Y/%m/%d %H:%M")
                    
                    cursor.execute("""
                        INSERT INTO user_assets (staff_id, staff_name, asset_type, details, is_active, approval_status, assigned_at)
                        VALUES (?, ?, ?, ?, 1, 'تأیید قطعی توسط مدیر/سیستم ✅', ?)
                    """, (target_staff_id, user_name, asset_type_val, details_val, now_str))

                if req_type == "عودت اموال" and location_val and location_val.isdigit():
                    asset_id_to_return = int(location_val)
                    date_now = get_current_tehran_time().strftime("%Y/%m/%d")
                    cursor.execute("""
                        UPDATE user_assets 
                        SET is_active = 0, return_date = ?
                        WHERE id = ?
                    """, (date_now, asset_id_to_return))

                conn.commit()

                try:
                    if callback.message.photo:
                        await callback.message.edit_caption(caption=(callback.message.caption or "") + f"\n\n{new_status} (توسط مدیر اصلی)", reply_markup=None)
                    else:
                        await callback.message.edit_text(text=(callback.message.text or "") + f"\n\n{new_status} (توسط مدیر اصلی)", reply_markup=None)
                except Exception:
                    pass

                try:
                    await bot.send_message(chat_id=target_telegram_user_id, text=f"📄 وضعیت درخواست ({req_code}): <b>{new_status}</b>", parse_mode="HTML")
                except Exception:
                    pass

                if req_type == "خرید ملزومات":
                    purch_text = f"🛒 <b>دستور خرید جدید (ملزومات / انباردیگر)</b>\n\n🔹 <b>کد:</b> {req_code}\n👤 <b>پرسنل:</b> {html.escape(user_name)}\n📦 {html.escape(col1)}\n🔢 {html.escape(col2)}\n📝 {html.escape(col3)}"
                    purch_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="خریدم 🛒", callback_data=f"bought_{req_id}")]])
                    cursor.execute("SELECT telegram_user_id FROM staff_mapping WHERE role = 'purchase' AND is_active = 1")
                    purch_manager = cursor.fetchone()
                    target_purch_id = purch_manager[0] if purch_manager else GROUP_ID
                    try:
                        await bot.send_message(chat_id=target_purch_id, text=purch_text, reply_markup=purch_kb, parse_mode="HTML")
                    except Exception:
                        pass

                if req_type in ["مساعده", "تنخواه"]:
                    decrypted_sensitive = decrypt_data(sensitive_data) if sensitive_data else 'ندارد'
                    fin_text = f"💳 <b>دستور پرداخت جدید (واحد مالی)</b>\n\n🔹 <b>کد:</b> {req_code}\n👤 <b>پرسنل:</b> {html.escape(user_name)}\n📌 نوع: {req_type}\n💵 {html.escape(col1)}\n📝 {html.escape(col2)}\n🔑 <b>اطلاعات مالی/محفوظ:</b> <code>{decrypted_sensitive}</code>"
                    pay_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="پرداخت شد 💳", callback_data=f"paid_{req_id}")]])
                    cursor.execute("SELECT telegram_user_id FROM staff_mapping WHERE role = 'finance' AND is_active = 1")
                    fin_manager = cursor.fetchone()
                    target_fin_id = fin_manager[0] if fin_manager else GROUP_ID
                    try:
                        await bot.send_message(chat_id=target_fin_id, text=fin_text, reply_markup=pay_kb, parse_mode="HTML")
                    except Exception:
                        pass

                await callback.answer("تایید نهایی با موفقیت ثبت شد.")
                return

            if action == "paid":
                cursor.execute("UPDATE requests SET status = '💳 تسویه و پرداخت شده' WHERE id = ? AND status = '✅ تأیید شده قطعی'", (req_id,))
                if cursor.rowcount == 0:
                    await callback.answer("این درخواست یا هنوز تایید نشده یا قبلاً تسویه شده است.", show_alert=True)
                    return
                conn.commit()
                try:
                    await callback.message.edit_text((callback.message.text or "") + "\n\n✅ <b>وجه پرداخت و تسویه گردید.</b>", reply_markup=None, parse_mode="HTML")
                except Exception:
                    pass
                try:
                    await bot.send_message(chat_id=target_telegram_user_id, text=f"🎉 درخواست {req_type} شما پرداخت و تسویه گردید.", parse_mode="HTML")
                except Exception:
                    pass
                await callback.answer("وضعیت پرداخت ثبت شد.")
                return

            if action == "bought":
                cursor.execute("UPDATE requests SET status = '🛒 خریداری شده' WHERE id = ? AND status = '✅ تأیید شده قطعی'", (req_id,))
                if cursor.rowcount == 0:
                    await callback.answer("این درخواست یا هنوز تایید نشده یا قبلاً خریداری شده است.", show_alert=True)
                    return
                conn.commit()
                try:
                    await callback.message.edit_text((callback.message.text or "") + "\n\n✅ <b>وضعیت به خریداری شده تغییر یافت.</b>", reply_markup=None, parse_mode="HTML")
                except Exception:
                    pass
                await callback.answer("تایید خرید ثبت شد.")
                return
        except Exception as e:
            conn.rollback()
            logging.error(f"Request decision error: {e}")
            await callback.answer("خطا در پردازش درخواست.", show_alert=True)

@dp.message(AdminForm.rejection_reason)
async def save_rejection_reason(message: Message, state: FSMContext):
    if not check_user_role(message.from_user.id, "main_admin"):
        return
    if not message.text:
        await message.answer("❌ دلیل معتبر وارد کنید.")
        return
    reason = message.text.strip()
    data = await state.get_data()
    req_id = data.get("rejecting_req_id")

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE requests SET status = '❌ رد شده', rejection_reason = ? WHERE id = ? AND status LIKE '%در انتظار%'", (reason, req_id))
        if cursor.rowcount == 0:
            await message.answer("❌ این درخواست قبلاً تعیین تکلیف شده است.")
            await state.clear()
            return

        cursor.execute("SELECT telegram_user_id, req_code, admin_chat_id, admin_msg_id FROM requests WHERE id = ?", (req_id,))
        row = cursor.fetchone()
        conn.commit()

    await message.answer("✅ درخواست رد شد و دلیل آن برای کاربر ارسال گردید.")
    if row:
        target_uid, r_code, a_chat, a_msg = row[0], row[1], row[2], row[3]
        try:
            await bot.send_message(chat_id=target_uid, text=f"❌ <b>درخواست شما ({r_code}) رد شد.</b>\n\n📝 <b>دلیل رد توسط مدیر اصلی:</b>\n{html.escape(reason)}", parse_mode="HTML")
        except Exception:
            pass
        if a_chat and a_msg:
            try:
                await bot.edit_message_text(chat_id=a_chat, message_id=a_msg, text=f"📩 <b>درخواست ({r_code})</b>\n\n❌ <b>وضعیت: رد شده</b>\n📝 دلیل: {html.escape(reason)}", reply_markup=None, parse_mode="HTML")
            except Exception:
                pass
    await state.clear()

@dp.message(Command("today"))
@dp.callback_query(F.data == "admin_today")
async def cmd_today_leaves(event: Message | CallbackQuery):
    user_id = event.from_user.id
    if not is_any_admin(user_id):
        return
    
    today_jalali = get_current_tehran_time().strftime("%Y/%m/%d")
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_name, request_type, col1, col2, start_date, end_date FROM requests WHERE status LIKE '%تأیید شده%' AND request_type IN ('مرخصی', 'ماموریت')")
        rows = cursor.fetchall()

    matched_rows = []
    for r in rows:
        uname, rtype, c1, c2, s_date, e_date = r
        if s_date and e_date:
            if s_date <= today_jalali <= e_date:
                matched_rows.append((uname, rtype, c1, c2))
        else:
            text_full = f"{c1} | {c2}"
            if today_jalali in text_full:
                matched_rows.append((uname, rtype, c1, c2))

    msg_text = f"📅 <b>لیست غایبین / حاضرین در مأموریت امروز ({today_jalali}):</b>\n\n"
    if not matched_rows:
        msg_text += "امروز هیچ موردی ثبت نشده است."
    else:
        for r in matched_rows:
            msg_text += f"▫️ <b>{html.escape(r[0])}</b> ➔ {r[1]} ({html.escape(r[2])} | {html.escape(r[3])})\n"

    if isinstance(event, CallbackQuery):
        await event.message.answer(msg_text, parse_mode="HTML")
        await event.answer()
    else:
        if event.chat.type == "private":
            await event.answer(msg_text, parse_mode="HTML")

async def background_schedulers():
    last_tomorrow_check = ""
    last_backup_check = ""
    last_salary_notice_date = ""
    last_insurance_check_date = ""

    while True:
        try:
            await asyncio.sleep(60)
            now_j = get_current_tehran_time()
            current_date_str = now_j.strftime("%Y/%m/%d")
            current_hour_str = now_j.strftime("%H:%M")

            with get_connection() as conn:
                cursor = conn.cursor()

                if now_j.day == 25 and last_salary_notice_date != current_date_str:
                    last_salary_notice_date = current_date_str
                    cursor.execute("SELECT telegram_user_id FROM staff_mapping WHERE role = 'main_admin' AND is_active = 1")
                    for adm in cursor.fetchall():
                        try:
                            await bot.send_message(chat_id=adm[0], text="🚨 <b>یادآور مالی:</b> امروز <b>۲۵ام ماه</b> است؛ لطفاً بیمه تأمین اجتماعی پرسنل را پرداخت کنید.", parse_mode="HTML")
                        except Exception:
                            pass

                if last_insurance_check_date != current_date_str:
                    last_insurance_check_date = current_date_str
                    cursor.execute("SELECT car_code, car_name, plate_number, insurance_company, third_party_date, body_date FROM vehicle_insurances")
                    for v in cursor.fetchall():
                        code, car, plate, company, third, body = v
                        for b_date_str in [third, body]:
                            if not b_date_str or b_date_str == "-":
                                continue
                            try:
                                p = [int(x) for x in b_date_str.replace('-', '/').split('/')]
                                b_date = jdatetime.date(p[0], p[1], p[2])
                                delta_days = (b_date - now_j.date()).days
                                if delta_days == 7:
                                    cursor.execute("SELECT telegram_user_id FROM staff_mapping WHERE role = 'main_admin' AND is_active = 1")
                                    for adm in cursor.fetchall():
                                        await bot.send_message(chat_id=adm[0], text=f"⚠️ <b>هشدار بیمه خودرو</b>\nکد: {html.escape(code)} - {html.escape(car)} ({html.escape(plate)})\nبیمه {html.escape(company)} تا <b>۷ روز دیگر</b> ({b_date_str}) مهلت دارد.", parse_mode="HTML")
                            except Exception:
                                pass

                if current_hour_str == "19:00" and last_tomorrow_check != current_date_str:
                    last_tomorrow_check = current_date_str
                    tomorrow_j = now_j + jdatetime.timedelta(days=1)
                    tomorrow_jalali = tomorrow_j.strftime("%Y/%m/%d")

                    cursor.execute("SELECT user_name, request_type, col1, col2, start_date, end_date FROM requests WHERE status LIKE '%تأیید شده%' AND request_type IN ('مرخصی', 'ماموریت')")
                    all_reqs = cursor.fetchall()
                    tomorrow_matched = []
                    for r in all_reqs:
                        uname, rtype, c1, c2, s_date, e_date = r
                        if s_date and e_date:
                            if s_date <= tomorrow_jalali <= e_date:
                                tomorrow_matched.append((uname, rtype, c1, c2))
                        else:
                            if tomorrow_jalali in f"{c1} | {c2}":
                                tomorrow_matched.append((uname, rtype, c1, c2))

                    if tomorrow_matched:
                        rep_text = f"📋 <b>برنامه غایبین و مأموریت‌های فردا ({tomorrow_jalali}):</b>\n\n"
                        for r in tomorrow_matched:
                            rep_text += f"▫️ <b>{html.escape(r[0])}</b> ➔ {r[1]} ({html.escape(r[2])} | {html.escape(r[3])})\n"
                        
                        cursor.execute("SELECT telegram_user_id FROM staff_mapping WHERE role = 'main_admin' AND is_active = 1")
                        for adm in cursor.fetchall():
                            try:
                                await bot.send_message(chat_id=adm[0], text=rep_text, parse_mode="HTML")
                            except Exception:
                                pass

                current_weekday = now_j.togregorian().strftime("%A")
                if current_weekday == "Monday" and current_hour_str == "08:00" and last_backup_check != current_date_str:
                    last_backup_check = current_date_str
                    if os.path.exists(DB_PATH):
                        cursor.execute("SELECT telegram_user_id FROM staff_mapping WHERE role = 'main_admin' AND is_active = 1")
                        for adm in cursor.fetchall():
                            try:
                                await bot.send_document(chat_id=adm[0], document=FSInputFile(DB_PATH), caption="📦 پشتیبان خودکار هفتگی دیتابیس سامانه")
                            except Exception:
                                pass
        except Exception as e:
            logging.error(f"Background Scheduler error: {e}")

async def main():
    print("Enterprise Bot is running with all advanced security, database, and logic fixes applied...")
    asyncio.create_task(background_schedulers())
    asyncio.create_task(reminder_scheduler())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())