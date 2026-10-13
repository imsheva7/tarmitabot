import os
import re
import asyncio
import sqlite3
import jdatetime

from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    FSInputFile
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# ---------------------------------------------------------
# تنظیمات اصلی سیستم
# ---------------------------------------------------------
TOKEN = os.getenv("BOT_TOKEN", "8865295559:AAEOEDFV-Ikd3rZl6gzyR8V23RIlE7fGcVw")
GROUP_ID = int(os.getenv("GROUP_ID", "-1003619551361"))

TOPIC_LEAVE = 2     # تاپیک مرخصی
TOPIC_ADVANCE = 3   # تاپیک مساعده
TOPIC_MISSION = 38  # تاپیک ماموریت
TOPIC_PETTY = 57    # تاپیک تنخواه
TOPIC_ASSETS = 59   # تاپیک تحویل اموال
TOPIC_PURCHASE = 70 # تاپیک خرید ملزومات و انبار
TOPIC_INSURANCE = 73# تاپیک بیمه خودروها

ADMIN_IDS = [114906446, 827616077]
MAIN_ADMIN_ID = 114906446
FINANCE_MANAGER_ID = 114906446 
PURCHASE_MANAGER_PHONE = "+989135001135"

MAX_BASE_ADVANCE = 100_000_000  # سقف کل ماهانه (۱۰۰ میلیون ریال)

INITIAL_AUTHORIZED_STAFF = {
    "امید یزدان پناه": 0.0,
    "ایمان یزدان پناه": 0.0,
    "امین ارکیان": 0.0,
    "محمدصالح یزدان پناه": 5.0,
    "مهدی تقی زاده": 28.0,
    "پویا عابدی": 0.0,
    "فاطمه ارکیان": 41.0,
    "رضا مقصودی": 32.0,
    "شهریار محمدی": 7.0,
    "شهرزاد محمدی": 0.0,
    "امیر حسین اسدی": 31.0,
    "پوریا پیرای": 44.0,
    "علیرضا بابایی": 8.0,
    "حمیده زینلی": 33.0,
    "ابراهیم معاذالهی": 41.0,
    "داریوش دایی زاده": 34.0,
    "ابوالفضل احمدنژاد": 31.0,
    "مهدی نژاد شاهرخ آبادی": 26.0,
    "آرمان خاندان": 0.0,
    "علیرضا نگاری": 43.0,
    "حلیمه امیری": 0.0,
    "احمدرضا آموزنده": 15.0
}

bot = Bot(token=TOKEN)
dp = Dispatcher()

# ---------------------------------------------------------
# پایگاه داده و دفتر کل (Database & Ledger)
# ---------------------------------------------------------
def init_db():
    conn = sqlite3.connect("enterprise_requests.db")
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            req_code TEXT UNIQUE,
            user_id INTEGER,
            user_name TEXT,
            telegram_info TEXT,
            request_type TEXT,
            col1 TEXT,
            col2 TEXT,
            col3 TEXT,
            location TEXT,
            status TEXT,
            created_at TEXT,
            month_tag TEXT
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS staff_mapping (
            user_id INTEGER PRIMARY KEY,
            staff_name TEXT UNIQUE,
            phone_number TEXT,
            is_active INTEGER DEFAULT 1,
            leave_balance REAL
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS leave_ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
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
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
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
    
    cursor.execute("SELECT COUNT(*) FROM staff_mapping")
    if cursor.fetchone()[0] == 0:
        now_str = jdatetime.datetime.now().strftime("%Y/%m/%d %H:%M")
        for idx, (sname, bal) in enumerate(INITIAL_AUTHORIZED_STAFF.items(), start=1000):
            cursor.execute("INSERT OR IGNORE INTO staff_mapping (user_id, staff_name, is_active, leave_balance) VALUES (?, ?, 1, ?)", 
                           (idx, sname, bal))
            if bal > 0:
                cursor.execute("""
                    INSERT INTO leave_ledger (user_id, staff_name, change_amount, description, registered_by, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (idx, sname, bal, "مانده اولیه دوره", "سیستم", now_str))
            
    conn.commit()
    conn.close()

init_db()

def get_connection():
    conn = sqlite3.connect("enterprise_requests.db")
    conn.row_factory = sqlite3.Row
    return conn

def generate_req_code(req_id: int) -> str:
    year_j = jdatetime.datetime.now().year
    return f"REQ-{year_j}-{req_id:05d}"

def get_staff_info_by_id(user_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT staff_name, leave_balance, phone_number, is_active FROM staff_mapping WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row if row else (None, 0.0, None, 0)

def get_user_id_by_phone(phone: str):
    conn = get_connection()
    cursor = conn.cursor()
    clean_p = phone.replace("+", "").strip()
    cursor.execute("SELECT user_id FROM staff_mapping WHERE phone_number = ? OR phone_number = ? OR phone_number = ?", 
                   (phone, clean_p, "+" + clean_p))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

def get_finance_manager_id():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = 'finance_manager_id'")
    row = cursor.fetchone()
    conn.close()
    if row and row[0].isdigit():
        return int(row[0])
    return FINANCE_MANAGER_ID

def set_finance_manager_id(new_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('finance_manager_id', ?)", (str(new_id),))
    conn.commit()
    conn.close()

def get_holidays_list():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT h_date FROM holidays")
    rows = [r[0] for r in cursor.fetchall()]
    conn.close()
    return rows

# ---------------------------------------------------------
# توابع سرویس و اعتبارسنجی
# ---------------------------------------------------------
def validate_custom_date(date_text: str) -> bool:
    clean_text = date_text.strip().replace('-', '/')
    pattern = r'^\d{4}/\d{1,2}/\d{1,2}$'
    if not re.match(pattern, clean_text):
        return False
    try:
        parts = [int(x) for x in clean_text.split('/')]
        jdatetime.date(parts[0], parts[1], parts[2])
        return True
    except Exception:
        return False

def validate_card_or_sheba(text: str) -> bool:
    clean_text = text.strip().replace(" ", "").upper()
    if clean_text.isdigit() and len(clean_text) == 16:
        return True
    if clean_text.startswith("IR") and len(clean_text) == 26 and clean_text[2:].isdigit():
        return True
    if clean_text.isdigit() and len(clean_text) == 24:
        return True
    return False

def get_staff_balance_from_ledger(user_id: int) -> float:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT SUM(change_amount) FROM leave_ledger WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return float(row[0]) if row and row[0] is not None else 0.0

def apply_leave_ledger_transaction(user_id: int, staff_name: str, days: float, req_code: str, registered_by: str):
    now_str = jdatetime.datetime.now().strftime("%Y/%m/%d %H:%M")
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO leave_ledger (user_id, staff_name, change_amount, description, registered_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, staff_name, -days, f"ثبت بابت مرخصی تایید شده ({req_code})", registered_by, now_str))
        
        new_bal = get_staff_balance_from_ledger(user_id)
        cursor.execute("UPDATE staff_mapping SET leave_balance = ? WHERE user_id = ?", (new_bal, user_id))
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

# ---------------------------------------------------------
# وضعیت‌های FSM (States)
# ---------------------------------------------------------
class Form(StatesGroup):
    waiting_for_phone = State()
    waiting_for_leave_type = State()    
    waiting_for_leave_start_date = State()   
    waiting_for_leave_end_date = State()    
    waiting_for_hourly_date = State()
    waiting_for_hourly_times = State()
    waiting_for_advance_amount = State()
    waiting_for_advance_card = State()
    waiting_for_advance_reason = State()
    waiting_for_mission_city = State()  
    waiting_for_mission_days = State()
    waiting_for_petty_photo = State()
    waiting_for_petty_amount = State()
    waiting_for_petty_desc = State()
    
    # تحویل اموال شخصی
    asset_car_code = State()
    asset_car_type = State()
    asset_car_plate = State()
    asset_car_km = State()
    asset_car_desc = State()
    asset_fuel_code = State()
    asset_fuel_pass = State()
    asset_pos_code = State()
    asset_pos_bank = State()
    asset_pos_charger = State()
    asset_printer_code = State()
    asset_printer_charger = State()

    # درخواست خرید ملزومات / انبار
    purch_item_name = State()
    purch_qty = State()
    purch_desc = State()

    # اصلاح درخواست رد شده
    editing_req_id = State()
    editing_new_col1 = State()

class AdminForm(StatesGroup):
    add_staff_name = State()
    add_staff_balance = State()
    edit_balance_select_user = State()
    edit_balance_new_value = State()
    add_holiday_date = State()
    set_finance_id = State()
    
    # تحویل اموال توسط مدیر
    admin_asset_select_staff = State()
    admin_asset_car_code = State()
    admin_asset_car_type = State()
    admin_asset_car_plate = State()
    admin_asset_car_km = State()
    admin_asset_car_desc = State()
    admin_asset_fuel_code = State()
    admin_asset_fuel_pass = State()
    admin_asset_pos_code = State()
    admin_asset_pos_bank = State()
    admin_asset_pos_charger = State()
    admin_asset_printer_code = State()
    admin_asset_printer_charger = State()

    # ثبت بیمه خودرو
    ins_car_code = State()
    ins_car_name = State()
    ins_plate = State()
    ins_company = State()
    ins_third = State()
    ins_body = State()

    rejection_reason = State()

# ---------------------------------------------------------
# احراز هویت خودکار (بدون نیاز به تایپ نام)
# ---------------------------------------------------------
@dp.message(F.text == "/start")
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    staff_name, balance, phone, is_active = get_staff_info_by_id(user_id)

    if not staff_name or is_active == 0:
        if is_active == 0 and staff_name:
            await message.answer("❌ دسترسی شما به سامانه مسدود شده است. با مدیریت تماس بگیرید.")
            return

        kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="📱 تایید و اتصال خودکار حساب کاربری", request_contact=True)]],
            resize_keyboard=True,
            one_time_keyboard=True
        )
        await state.set_state(Form.waiting_for_phone)
        await message.answer("سلام! به سامانه جامع مدیریت پرسنلی خوش آمدید.\n\nلطفاً برای اتصال خودکار حساب خود، روی دکمه زیر کلیک کنید:", reply_markup=kb)
        return

    await show_main_menu(message, staff_name, balance)

@dp.message(Form.waiting_for_phone, F.contact)
async def process_phone_contact(message: Message, state: FSMContext):
    phone = message.contact.phone_number
    clean_phone = phone.replace("+", "").strip()
    if clean_phone.startswith("98"):
        clean_phone = "0" + clean_phone[2:]

    user_id = message.from_user.id
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT staff_name FROM staff_mapping WHERE phone_number = ? OR phone_number = ? OR phone_number = ?", 
                   (phone, clean_phone, "+" + clean_phone))
    row = cursor.fetchone()

    if row:
        staff_name = row[0]
        cursor.execute("UPDATE staff_mapping SET user_id = ?, is_active = 1 WHERE staff_name = ?", (user_id, staff_name))
        conn.commit()
        conn.close()
        
        await message.answer(f"✅ احراز هویت با موفقیت انجام شد.\nخوش آمدید، **{staff_name}** عزیز.", reply_markup=ReplyKeyboardRemove())
        await state.clear()
        
        staff_name, balance, _, _ = get_staff_info_by_id(user_id)
        await show_main_menu(message, staff_name, balance)
    else:
        conn.close()
        kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="📱 تلاش مجدد با اشتراک‌گذاری شماره", request_contact=True)]],
            resize_keyboard=True,
            one_time_keyboard=True
        )
        await message.answer("⚠️ شماره شما در لیست پرسنل مجاز یافت نشد. لطفاً با مدیر سیستم هماهنگ کنید.", reply_markup=kb)

async def show_main_menu(message: Message, staff_name, balance):
    user_id = message.from_user.id
    
    # ساختار سه‌گانه منوی پرسنل
    keyboard_buttons = [
        [InlineKeyboardButton(text="📝 امور اداری و مالی (مرخصی، مساعده، ماموریت)", callback_data="menu_admin_finance")],
        [InlineKeyboardButton(text="🏢 حسابداری، اموال و خرید انبار", callback_data="menu_assets_purchase")],
        [InlineKeyboardButton(text="📊 کارنامه و پیگیری درخواست‌ها", callback_data="menu_reports_tracking")]
    ]
    
    if user_id in ADMIN_IDS:
        keyboard_buttons.append([InlineKeyboardButton(text="⚙️ منوی مدیریت سیستم", callback_data="admin_panel")])
        keyboard_buttons.append([InlineKeyboardButton(text="📅 مرخصی‌های فعال امروز (/today)", callback_data="admin_today")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    status_text = f"👤 پرسنل: **{staff_name}** | 🌿 مانده مرخصی: `{balance} روز`" if staff_name else "⚠️ نام شما ثبت نشده است."
    
    await message.answer(f"سامانه جامع مدیریت پرسنلی\n{status_text}\n\nلطفاً بخش مورد نظر خود را انتخاب کنید:", reply_markup=keyboard)

@dp.callback_query(F.data == "menu_admin_finance")
async def sub_menu_admin_finance(callback: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏳ درخواست مرخصی", callback_data="req_leave")],
        [InlineKeyboardButton(text="💵 درخواست مساعده (ریال)", callback_data="req_advance")],
        [InlineKeyboardButton(text="📍 ثبت گزارش ماموریت", callback_data="req_mission")],
        [InlineKeyboardButton(text="🔙 بازگشت به منوی اصلی", callback_data="back_to_main")]
    ])
    await callback.message.edit_text("📝 **امور اداری و مالی**\n\nلطفاً گزینه مورد نظر را انتخاب کنید:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data == "menu_assets_purchase")
async def sub_menu_assets_purchase(callback: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧾 ثبت فاکتور تنخواه", callback_data="req_petty")],
        [InlineKeyboardButton(text="🚗 تحویل/ثبت اموال و تجهیزات", callback_data="req_asset")],
        [InlineKeyboardButton(text="🛒 درخواست خرید ملزومات / انبار", callback_data="req_purchase")],
        [InlineKeyboardButton(text="🔙 بازگشت به منوی اصلی", callback_data="back_to_main")]
    ])
    await callback.message.edit_text("🏢 **حسابداری، اموال و خرید انبار**\n\nلطفاً گزینه مورد نظر را انتخاب کنید:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data == "menu_reports_tracking")
async def sub_menu_reports_tracking(callback: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 وضعیت من (آمار ماه جاری)", callback_data="my_stats")],
        [InlineKeyboardButton(text="📋 پیگیری و لغو درخواست‌ها", callback_data="my_requests")],
        [InlineKeyboardButton(text="🔙 بازگشت به منوی اصلی", callback_data="back_to_main")]
    ])
    await callback.message.edit_text("📊 **کارنامه و پیگیری درخواست‌ها**\n\nلطفاً گزینه مورد نظر را انتخاب کنید:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data == "back_to_main")
async def back_to_main_menu(callback: CallbackQuery):
    user_id = callback.from_user.id
    staff_name, balance, _, _ = get_staff_info_by_id(user_id)
    
    keyboard_buttons = [
        [InlineKeyboardButton(text="📝 امور اداری و مالی (مرخصی، مساعده، ماموریت)", callback_data="menu_admin_finance")],
        [InlineKeyboardButton(text="🏢 حسابداری، اموال و خرید انبار", callback_data="menu_assets_purchase")],
        [InlineKeyboardButton(text="📊 کارنامه و پیگیری درخواست‌ها", callback_data="menu_reports_tracking")]
    ]
    if user_id in ADMIN_IDS:
        keyboard_buttons.append([InlineKeyboardButton(text="⚙️ منوی مدیریت سیستم", callback_data="admin_panel")])
        keyboard_buttons.append([InlineKeyboardButton(text="📅 مرخصی‌های فعال امروز (/today)", callback_data="admin_today")])

    kb = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    status_text = f"👤 پرسنل: **{staff_name}** | 🌿 مانده مرخصی: `{balance} روز`" if staff_name else "⚠️ نام شما ثبت نشده است."
    await callback.message.edit_text(f"سامانه جامع مدیریت پرسنلی\n{status_text}\n\nلطفاً بخش مورد نظر را انتخاب کنید:", reply_markup=kb)
    await callback.answer()

# ---------------------------------------------------------
# بخش ۱: ثبت مرخصی (استحقاقی، استعلاجی، ساعتی، بدون حقوق)
# ---------------------------------------------------------
@dp.callback_query(F.data == "req_leave")
async def process_leave_start(callback: CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="استحقاقی", callback_data="ltype_استحقاقی")],
        [InlineKeyboardButton(text="استعلاجی", callback_data="ltype_استعلاجی")],
        [InlineKeyboardButton(text="ساعتی", callback_data="ltype_ساعتی")],
        [InlineKeyboardButton(text="بدون حقوق", callback_data="ltype_بدون_حقوق")]
    ])
    await callback.message.answer("نوع مرخصی را انتخاب کنید:", reply_markup=kb)
    await state.set_state(Form.waiting_for_leave_type)
    await callback.answer()

@dp.callback_query(Form.waiting_for_leave_type, F.data.startswith("ltype_"))
async def process_leave_type_selected(callback: CallbackQuery, state: FSMContext):
    ltype = callback.data.split("_")[1]
    await state.update_data(leave_type=ltype)
    
    if ltype == "ساعتی":
        await state.set_state(Form.waiting_for_hourly_date)
        await callback.message.answer("تاریخ روز مرخصی را با فرمت `سال/ماه/روز` (`YYYY/MM/DD`) وارد کنید:")
    else:
        await state.set_state(Form.waiting_for_leave_start_date)
        await callback.message.answer("تاریخ خروج (شروع مرخصی) را با فرمت `سال/ماه/روز` (`YYYY/MM/DD`) وارد کنید:")
    await callback.answer()

@dp.message(Form.waiting_for_hourly_date)
async def receive_hourly_date(message: Message, state: FSMContext):
    if not validate_custom_date(message.text):
        await message.answer("❌ فرمت تاریخ نامعتبر است! با فرمت `سال/ماه/روز` (`YYYY/MM/DD`) وارد کنید:")
        return
    await state.update_data(hourly_date=message.text.strip())
    await state.set_state(Form.waiting_for_hourly_times)
    await message.answer("ساعت خروج و ورود را وارد کنید (مثلاً: 09:00 تا 13:00):")

@dp.message(Form.waiting_for_hourly_times)
async def receive_hourly_times(message: Message, state: FSMContext):
    user_data = await state.get_data()
    user_id = message.from_user.id
    staff_name, balance, _, _ = get_staff_info_by_id(user_id)
    
    leave_date = user_data.get("hourly_date")
    times = message.text.strip()
    ltype = user_data.get("leave_type")
    
    col1 = f"نوع: {ltype}"
    col2 = f"تاریخ: {leave_date} | ساعت: {times}"
    col3 = "مدت: ساعتی"
    details = f"نوع: {ltype} | تاریخ: {leave_date} | ساعت: {times}"

    await finalize_leave_request(message, user_id, staff_name, balance, col1, col2, col3, details, 0.0)

@dp.message(Form.waiting_for_leave_start_date)
async def receive_leave_start(message: Message, state: FSMContext):
    if not validate_custom_date(message.text):
        await message.answer("❌ فرمت تاریخ نامعتبر است! با فرمت `سال/ماه/روز` (`YYYY/MM/DD`) وارد کنید:")
        return
    await state.update_data(leave_start=message.text.strip())
    await state.set_state(Form.waiting_for_leave_end_date)
    await message.answer("تاریخ ورود (پایان مرخصی) را با فرمت `سال/ماه/روز` (`YYYY/MM/DD`) وارد کنید:")

@dp.message(Form.waiting_for_leave_end_date)
async def receive_leave_end(message: Message, state: FSMContext):
    if not validate_custom_date(message.text):
        await message.answer("❌ فرمت تاریخ نامعتبر است! با فرمت `سال/ماه/روز` (`YYYY/MM/DD`) وارد کنید:")
        return

    user_data = await state.get_data()
    user_id = message.from_user.id
    staff_name, balance, _, _ = get_staff_info_by_id(user_id)
    
    start_str = user_data.get("leave_start")
    end_str = message.text.strip()
    ltype = user_data.get("leave_type")
    holidays = get_holidays_list()

    # محاسبه روزهای کاری با کسر تعطیلات
    calculated_days = 1.0
    try:
        s_p = [int(x) for x in start_str.replace('-', '/').split('/')]
        e_p = [int(x) for x in end_str.replace('-', '/').split('/')]
        d1 = jdatetime.date(s_p[0], s_p[1], s_p[2])
        d2 = jdatetime.date(e_p[0], e_p[1], e_p[2])
        
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
    col2 = f"خروج: {start_str} ➔ ورود: {end_str}"
    col3 = f"تعداد روز کسر: {calculated_days} روز"
    details = f"نوع: {ltype} | خروج: {start_str} | ورود: {end_str} | کسر: {calculated_days} روز"

    await finalize_leave_request(message, user_id, staff_name, balance, col1, col2, col3, details, calculated_days)

async def finalize_leave_request(message, user_id, user_name, balance, col1, col2, col3, details, days_to_deduct):
    now_j = jdatetime.datetime.now()
    created_at = now_j.strftime("%Y/%m/%d %H:%M")
    month_tag = now_j.strftime("%Y/%m")
    
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO requests (user_id, user_name, telegram_info, request_type, col1, col2, col3, location, status, created_at, month_tag) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_id, user_name, message.from_user.full_name, "مرخصی", col1, col2, col3, str(days_to_deduct), "⏳ در انتظار تأیید سرپرست", created_at, month_tag))
    req_id = cursor.lastrowid
    
    req_code = generate_req_code(req_id)
    cursor.execute("UPDATE requests SET req_code = ? WHERE id = ?", (req_code, req_id))
    conn.commit()
    conn.close()

    text = f"📩 **درخواست مرخصی ({req_code})**\n\n👤 پرسنل: {user_name} (مانده کل: {balance} روز)\n📝 {details}\n📅 ثبت: {created_at}\nوضعیت: ⏳ در انتظار تأیید سرپرست"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="👤 تأیید سرپرست ➔ ارسال به مدیریت", callback_data=f"step1_{req_id}")]])

    try:
        await bot.send_message(chat_id=GROUP_ID, message_thread_id=TOPIC_LEAVE, text=text, reply_markup=kb)
        await message.answer(f"✅ درخواست مرخصی شما ({req_code}) ثبت و ارسال شد.")
    except Exception:
        await message.answer("❌ خطا در ارسال به گروه.")
    await state.clear()

# ---------------------------------------------------------
# بخش ۲: ثبت مساعده (با سقف پویا و شماره کارت/شبا)
# ---------------------------------------------------------
@dp.callback_query(F.data == "req_advance")
async def process_advance_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(Form.waiting_for_advance_amount)
    await callback.message.answer("💵 **درخواست مساعده حقوق**\n\nمبلغ درخواستی (به ریال) را به عدد وارد کنید:")
    await callback.answer()

@dp.message(Form.waiting_for_advance_amount)
async def receive_advance_amount(message: Message, state: FSMContext):
    raw_text = message.text.replace(",", "").replace("ریال", "").strip()
    if not raw_text.isdigit():
        await message.answer("❌ مبلغ فقط باید عدد باشد:")
        return

    amount = int(raw_text)
    today_day = jdatetime.datetime.now().day
    daily_rate = MAX_BASE_ADVANCE / 30.0
    allowed_limit = int(today_day * daily_rate)

    if amount > allowed_limit:
        await message.answer(f"⚠️ سقف مجاز مساعده تا امروز ({today_day} روز از ماه): {allowed_limit:,} ریال است. مبلغ کمتری وارد کنید:")
        return

    await state.update_data(advance_amount=f"{amount:,}")
    await state.set_state(Form.waiting_for_advance_card)
    await message.answer("شماره کارت (۱۶ رقم) یا شبا جهت واریز را وارد کنید:")

@dp.message(Form.waiting_for_advance_card)
async def receive_advance_card(message: Message, state: FSMContext):
    card = message.text.strip()
    if not validate_card_or_sheba(card):
        await message.answer("❌ شماره کارت یا شبا نامعتبر است:")
        return
    await state.update_data(advance_card=card)
    await state.set_state(Form.waiting_for_advance_reason)
    await message.answer("دلیل درخواست مساعده را بنویسید:")

@dp.message(Form.waiting_for_advance_reason)
async def receive_advance_reason(message: Message, state: FSMContext):
    reason = message.text.strip()
    user_data = await state.get_data()
    user_id = message.from_user.id
    staff_name, _, _, _ = get_staff_info_by_id(user_id)
    
    amount = user_data.get("advance_amount")
    card = user_data.get("advance_card")
    now_j = jdatetime.datetime.now()
    created_at = now_j.strftime("%Y/%m/%d %H:%M")
    month_tag = now_j.strftime("%Y/%m")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO requests (user_id, user_name, telegram_info, request_type, col1, col2, col3, location, status, created_at, month_tag) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_id, staff_name, message.from_user.full_name, "مساعده", f"مبلغ: {amount} ریال", f"دلیل: {reason}", f"کارت: {card}", "-", "⏳ در انتظار تأیید سرپرست", created_at, month_tag))
    req_id = cursor.lastrowid
    
    req_code = generate_req_code(req_id)
    cursor.execute("UPDATE requests SET req_code = ? WHERE id = ?", (req_code, req_id))
    conn.commit()
    conn.close()

    text = f"💵 **درخواست مساعده ({req_code})**\n\n👤 پرسنل: {staff_name}\n💵 مبلغ: {amount} ریال\n📝 دلیل: {reason}\n💳 کارت: `{card}`\n📅 ثبت: {created_at}\nوضعیت: ⏳ در انتظار تأیید سرپرست"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="👤 تأیید سرپرست ➔ ارسال به مدیریت", callback_data=f"step1_{req_id}")]])

    try:
        await bot.send_message(chat_id=GROUP_ID, message_thread_id=TOPIC_ADVANCE, text=text, reply_markup=kb)
        await message.answer(f"✅ درخواست مساعده شما ({req_code}) ثبت شد.")
    except Exception:
        await message.answer("❌ خطا در ارسال به گروه.")
    await state.clear()

# ---------------------------------------------------------
# بخش ۳: ثبت گزارش ماموریت
# ---------------------------------------------------------
@dp.callback_query(F.data == "req_mission")
async def process_mission_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(Form.waiting_for_mission_city)
    await callback.message.answer("📍 **ثبت گزارش ماموریت**\n\nشهر مقصد ماموریت را وارد کنید:")
    await callback.answer()

@dp.message(Form.waiting_for_mission_city)
async def receive_mission_city(message: Message, state: FSMContext):
    await state.update_data(mission_city=message.text.strip())
    await state.set_state(Form.waiting_for_mission_days)
    await message.answer("تعداد روز ماموریت را به عدد وارد کنید:")

@dp.message(Form.waiting_for_mission_days)
async def receive_mission_days(message: Message, state: FSMContext):
    if not message.text.strip().isdigit():
        await message.answer("❌ تعداد روز باید عدد باشد:")
        return

    user_data = await state.get_data()
    user_id = message.from_user.id
    staff_name, _, _, _ = get_staff_info_by_id(user_id)
    
    city = user_data.get("mission_city")
    days = message.text.strip()
    now_j = jdatetime.datetime.now()
    created_at = now_j.strftime("%Y/%m/%d %H:%M")
    month_tag = now_j.strftime("%Y/%m")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO requests (user_id, user_name, telegram_info, request_type, col1, col2, col3, location, status, created_at, month_tag) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_id, staff_name, message.from_user.full_name, "ماموریت", f"شهر: {city}", f"مدت: {days} روز", "-", "-", "⏳ در انتظار تأیید سرپرست", created_at, month_tag))
    req_id = cursor.lastrowid
    
    req_code = generate_req_code(req_id)
    cursor.execute("UPDATE requests SET req_code = ? WHERE id = ?", (req_code, req_id))
    conn.commit()
    conn.close()

    text = f"📍 **گزارش ماموریت ({req_code})**\n\n👤 پرسنل: {staff_name}\n🏙️ مقصد: {city}\n⏳ مدت: {days} روز\n📅 ثبت: {created_at}\nوضعیت: ⏳ در انتظار تأیید سرپرست"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="👤 تأیید سرپرست ➔ ارسال به مدیریت", callback_data=f"step1_{req_id}")]])

    try:
        await bot.send_message(chat_id=GROUP_ID, message_thread_id=TOPIC_MISSION, text=text, reply_markup=kb)
        await message.answer(f"✅ گزارش ماموریت شما ({req_code}) ثبت شد.")
    except Exception:
        await message.answer("❌ خطا در ارسال به گروه.")
    await state.clear()

# ---------------------------------------------------------
# بخش ۴: فاکتور تنخواه
# ---------------------------------------------------------
@dp.callback_query(F.data == "req_petty")
async def process_petty_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(Form.waiting_for_petty_photo)
    await callback.message.answer("🧾 **ثبت فاکتور تنخواه شرکت**\n\n1️⃣ لطفاً **عکس واضح فاکتور خرید** را ارسال نمایید:")
    await callback.answer()

@dp.message(Form.waiting_for_petty_photo, F.photo)
async def receive_petty_photo(message: Message, state: FSMContext):
    photo_id = message.photo[-1].file_id
    await state.update_data(petty_photo=photo_id)
    await state.set_state(Form.waiting_for_petty_amount)
    await message.answer("2️⃣ لطفاً **مبلغ فاکتور (به ریال)** را به عدد وارد کنید:")

@dp.message(Form.waiting_for_petty_amount)
async def receive_petty_amount(message: Message, state: FSMContext):
    raw_val = message.text.replace(",", "").strip()
    if not raw_val.isdigit():
        await message.answer("❌ مبلغ فقط باید **عدد** باشد:")
        return

    await state.update_data(petty_amount=f"{int(raw_val):,} ریال")
    await state.set_state(Form.waiting_for_petty_desc)
    await message.answer("3️⃣ لطفاً **بابت / شرح هزینه** را بنویسید:")

@dp.message(Form.waiting_for_petty_desc)
async def receive_petty_desc(message: Message, state: FSMContext):
    desc = message.text.strip()
    user_data = await state.get_data()
    user_id = message.from_user.id
    staff_name, _, _, _ = get_staff_info_by_id(user_id)

    photo_id = user_data.get("petty_photo")
    amount_str = user_data.get("petty_amount")

    now_j = jdatetime.datetime.now()
    created_at = now_j.strftime("%Y/%m/%d %H:%M")
    month_tag = now_j.strftime("%Y/%m")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO requests (user_id, user_name, telegram_info, request_type, col1, col2, col3, location, status, created_at, month_tag) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_id, staff_name, message.from_user.full_name, "تنخواه", f"مبلغ: {amount_str}", f"بابت: {desc}", "-", photo_id, "⏳ در انتظار تأیید سرپرست", created_at, month_tag))
    req_id = cursor.lastrowid
    
    req_code = generate_req_code(req_id)
    cursor.execute("UPDATE requests SET req_code = ? WHERE id = ?", (req_code, req_id))
    conn.commit()
    conn.close()

    caption = (f"🧾 **فاکتور تنخواه جدید ({req_code})**\n\n"
               f"👤 پرسنل: {staff_name}\n"
               f"💵 مبلغ: {amount_str}\n"
               f"📝 بابت: {desc}\n"
               f"📅 تاریخ: {created_at}\n"
               f"وضعیت: ⏳ در انتظار تأیید سرپرست")

    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 تأیید سرپرست ➔ ارسال به مدیریت", callback_data=f"step1_{req_id}")],
        [InlineKeyboardButton(text="❌ رد فاکتور", callback_data=f"reject_{req_id}")]
    ])

    try:
        await bot.send_photo(chat_id=GROUP_ID, message_thread_id=TOPIC_PETTY, photo=photo_id, caption=caption, reply_markup=admin_kb)
        await message.answer(f"✅ فاکتور تنخواه شما ({req_code}) ثبت و ارسال شد.")
    except Exception:
        await message.answer("❌ خطا در ارسال فاکتور.")

    await state.clear()

# ---------------------------------------------------------
# بخش ۵: تحویل اموال و تجهیزات توسط پرسنل
# ---------------------------------------------------------
@dp.callback_query(F.data == "req_asset")
async def process_asset_start(callback: CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚗 خودروی سازمانی", callback_data="asset_sel_خودرو")],
        [InlineKeyboardButton(text="⛽ کارت سوخت", callback_data="asset_sel_کارت_سوخت")],
        [InlineKeyboardButton(text="💳 کارت‌خوان (POS)", callback_data="asset_sel_کارتخوان")],
        [InlineKeyboardButton(text="🖨️ پرینتر جیبی", callback_data="asset_sel_پرینتر")]
    ])
    await callback.message.answer("🚗 **ثبت تحویل اقلام امانی و تجهیزات**\n\nقلم مورد نظر را انتخاب کنید:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data == "asset_sel_خودرو")
async def asset_car_step1(callback: CallbackQuery, state: FSMContext):
    await state.set_state(Form.asset_car_code)
    await callback.message.answer("🚗 **[۱/۵] خودروی سازمانی**\n\nکد خودرو را وارد کنید:")
    await callback.answer()

@dp.message(Form.asset_car_code)
async def asset_car_step2(message: Message, state: FSMContext):
    await state.update_data(car_code=message.text.strip())
    await state.set_state(Form.asset_car_type)
    await message.answer("🚗 **[۲/۵] خودروی سازمانی**\n\nنوع خودرو را وارد کنید:")

@dp.message(Form.asset_car_type)
async def asset_car_step3(message: Message, state: FSMContext):
    await state.update_data(car_type=message.text.strip())
    await state.set_state(Form.asset_car_plate)
    await message.answer("🚗 **[۳/۵] خودروی سازمانی**\n\nپلاک خودرو را وارد کنید:")

@dp.message(Form.asset_car_plate)
async def asset_car_step4(message: Message, state: FSMContext):
    await state.update_data(car_plate=message.text.strip())
    await state.set_state(Form.asset_car_km)
    await message.answer("🚗 **[۴/۵] خودروی سازمانی**\n\nکیلومتر تحویلی را به عدد وارد کنید:")

@dp.message(Form.asset_car_km)
async def asset_car_step5(message: Message, state: FSMContext):
    if not message.text.strip().isdigit():
        await message.answer("❌ کیلومتر باید عدد باشد:")
        return
    await state.update_data(car_km=message.text.strip())
    await state.set_state(Form.asset_car_desc)
    await message.answer("🚗 **[۵/۵] خودروی سازمانی**\n\nتوضیحات تکمیلی (اگر ندارد `-` بگذارید):")

@dp.message(Form.asset_car_desc)
async def asset_car_finish(message: Message, state: FSMContext):
    desc = message.text.strip()
    data = await state.get_data()
    col1 = f"کد: {data.get('car_code')} | نوع: {data.get('car_type')}"
    col2 = f"پلاک: {data.get('car_plate')} | کیلومتر: {data.get('car_km')}"
    col3 = f"توضیحات: {desc}"
    await finalize_asset_request(message, state, "خودروی سازمانی", col1, col2, col3)

@dp.callback_query(F.data == "asset_sel_کارت_سوخت")
async def asset_fuel_step1(callback: CallbackQuery, state: FSMContext):
    await state.set_state(Form.asset_fuel_code)
    await callback.message.answer("⛽ **[۱/۲] کارت سوخت**\n\nکد کارت سوخت را وارد کنید:")
    await callback.answer()

@dp.message(Form.asset_fuel_code)
async def asset_fuel_step2(message: Message, state: FSMContext):
    await state.update_data(fuel_code=message.text.strip())
    await state.set_state(Form.asset_fuel_pass)
    await message.answer("⛽ **[۲/۲] کارت سوخت**\n\nرمز کارت سوخت را وارد کنید:")

@dp.message(Form.asset_fuel_pass)
async def asset_fuel_finish(message: Message, state: FSMContext):
    f_pass = message.text.strip()
    data = await state.get_data()
    col1 = f"کد کارت سوخت: {data.get('fuel_code')}"
    col2 = f"رمز: {f_pass}"
    col3 = "-"
    await finalize_asset_request(message, state, "کارت سوخت", col1, col2, col3)

@dp.callback_query(F.data == "asset_sel_کارتخوان")
async def asset_pos_step1(callback: CallbackQuery, state: FSMContext):
    await state.set_state(Form.asset_pos_code)
    await callback.message.answer("💳 **[۱/۳] کارت‌خوان (POS)**\n\nکد دستگاه را وارد کنید:")
    await callback.answer()

@dp.message(Form.asset_pos_code)
async def asset_pos_step2(message: Message, state: FSMContext):
    await state.update_data(pos_code=message.text.strip())
    await state.set_state(Form.asset_pos_bank)
    await message.answer("💳 **[۲/۳] کارت‌خوان (POS)**\n\nنام بانک را وارد کنید:")

@dp.message(Form.asset_pos_bank)
async def asset_pos_step3(message: Message, state: FSMContext):
    await state.update_data(pos_bank=message.text.strip())
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ بله، شارژر دارد", callback_data="pos_charger_yes"),
         InlineKeyboardButton(text="❌ خیر، ندارد", callback_data="pos_charger_no")]
    ])
    await message.answer("💳 **[۳/۳] کارت‌خوان (POS)**\n\nآیا شارژر دارد؟", reply_markup=kb)

@dp.callback_query(F.data.startswith("pos_charger_"))
async def asset_pos_finish(callback: CallbackQuery, state: FSMContext):
    charger = "دارد" if "yes" in callback.data else "ندارد"
    data = await state.get_data()
    col1 = f"کد پوز: {data.get('pos_code')}"
    col2 = f"بانک: {data.get('pos_bank')}"
    col3 = f"شارژر: {charger}"
    await finalize_asset_request(callback.message, state, "کارت‌خوان", col1, col2, col3)
    await callback.answer()

@dp.callback_query(F.data == "asset_sel_پرینتر")
async def asset_printer_step1(callback: CallbackQuery, state: FSMContext):
    await state.set_state(Form.asset_printer_code)
    await callback.message.answer("🖨️ **[۱/۲] پرینتر جیبی**\n\nکد پرینتر را وارد کنید:")
    await callback.answer()

@dp.message(Form.asset_printer_code)
async def asset_printer_step2(message: Message, state: FSMContext):
    await state.update_data(printer_code=message.text.strip())
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ بله، شارژر دارد", callback_data="printer_charger_yes"),
         InlineKeyboardButton(text="❌ خیر، ندارد", callback_data="printer_charger_no")]
    ])
    await message.answer("🖨️ **[۲/۲] پرینتر جیبی**\n\nآیا شارژر دارد؟", reply_markup=kb)

@dp.callback_query(F.data.startswith("printer_charger_"))
async def asset_printer_finish(callback: CallbackQuery, state: FSMContext):
    charger = "دارد" if "yes" in callback.data else "ندارد"
    data = await state.get_data()
    col1 = f"کد پرینتر: {data.get('printer_code')}"
    col2 = f"شارژر: {charger}"
    col3 = "-"
    await finalize_asset_request(callback.message, state, "پرینتر جیبی", col1, col2, col3)
    await callback.answer()

async def finalize_asset_request(message_obj, state, asset_type, col1, col2, col3):
    user_id = message_obj.chat.id if hasattr(message_obj, 'chat') else message_obj.from_user.id
    staff_name, _, _, _ = get_staff_info_by_id(user_id)
    
    now_j = jdatetime.datetime.now()
    created_at = now_j.strftime("%Y/%m/%d %H:%M")
    month_tag = now_j.strftime("%Y/%m")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO requests (user_id, user_name, telegram_info, request_type, col1, col2, col3, location, status, created_at, month_tag) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_id, staff_name, "تجهیزات", "تحویل اموال", col1, col2, col3, asset_type, "⏳ در انتظار تأیید سرپرست", created_at, month_tag))
    req_id = cursor.lastrowid
    
    req_code = generate_req_code(req_id)
    cursor.execute("UPDATE requests SET req_code = ? WHERE id = ?", (req_code, req_id))
    conn.commit()
    conn.close()

    text = f"🚗 **گزارش تحویل اموال ({req_code})**\n\n👤 پرسنل: {staff_name}\n📦 نوع: {asset_type}\n📌 {col1}\n📌 {col2}\n📌 {col3}\n📅 ثبت: {created_at}\nوضعیت: ⏳ در انتظار تأیید سرپرست"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="👤 تأیید سرپرست ➔ ارسال به مدیریت", callback_data=f"step1_{req_id}")]])

    try:
        msg_target = message_obj if isinstance(message_obj, Message) else message_obj.message
        await bot.send_message(chat_id=GROUP_ID, message_thread_id=TOPIC_ASSETS, text=text, reply_markup=kb)
        await msg_target.answer(f"✅ فرم تحویل اموال ({req_code}) ثبت و ارسال شد.")
    except Exception:
        pass
    await state.clear()

# ---------------------------------------------------------
# بخش ۶: کارنامه و وضعیت من ("📊 وضعیت من")
# ---------------------------------------------------------
@dp.callback_query(F.data == "my_stats")
async def show_user_stats(callback: CallbackQuery):
    user_id = callback.from_user.id
    staff_name, balance, _, _ = get_staff_info_by_id(user_id)
    current_month = jdatetime.datetime.now().strftime("%Y/%m")

    conn = get_connection()
    cursor = conn.cursor()
    
    # مرخصی‌های تاییدشده ماه
    cursor.execute("SELECT location FROM requests WHERE user_id = ? AND request_type = 'مرخصی' AND month_tag = ? AND (status LIKE '%تأیید شده%' OR status LIKE '%پرداخت شده%')", (user_id, current_month))
    leave_rows = cursor.fetchall()
    used_leave = sum([float(r[0]) for r in leave_rows if r[0] and str(r[0]).replace('.', '', 1).isdigit()])

    # مساعده‌های ماه
    cursor.execute("SELECT col1 FROM requests WHERE user_id = ? AND request_type = 'مساعده' AND month_tag = ? AND (status LIKE '%تأیید شده%' OR status LIKE '%پرداخت شده%')", (user_id, current_month))
    adv_rows = cursor.fetchall()
    total_adv = 0
    for r in adv_rows:
        digits = ''.join(filter(str.isdigit, str(r[0])))
        if digits:
            total_adv += int(digits)

    # مأموریت‌های ماه
    cursor.execute("SELECT col1 FROM requests WHERE user_id = ? AND request_type = 'ماموریت' AND month_tag = ? AND (status LIKE '%تأیید شده%' OR status LIKE '%پرداخت شده%')", (user_id, current_month))
    mission_count = len(cursor.fetchall())
    conn.close()

    stats_msg = (
        f"📊 **کارنامه و وضعیت ماه جاری ({current_month})**\n\n"
        f"👤 **نام پرسنل:** {staff_name}\n"
        f"🌿 **مرخصی استفاده‌شده ماه:** {used_leave} روز\n"
        f"🍃 **مانده مرخصی کل (دفتر کل):** {balance} روز\n"
        f"💵 **مجموع مساعده دریافتی:** {total_adv:,} ریال\n"
        f"📍 **تعداد مأموریت‌ها:** {mission_count} مورد\n"
    )
    await callback.message.answer(stats_msg)
    await callback.answer()

# ---------------------------------------------------------
# پیگیری و لغو درخواست‌ها
# ---------------------------------------------------------
@dp.callback_query(F.data == "my_requests")
async def show_user_requests(callback: CallbackQuery):
    user_id = callback.from_user.id
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT req_code, request_type, col1, col2, status, created_at FROM requests WHERE user_id = ? ORDER BY id DESC LIMIT 5", (user_id,))
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        await callback.answer("شما تاکنون درخواستی ثبت نکرده‌اید.", show_alert=True)
        return

    for r in rows:
        r_code, r_type, c1, c2, status, created_at = r
        text = f"🔹 **کد: {r_code}** | نوع: {r_type}\n📌 اطلاعات: {c1} | {c2}\n📌 وضعیت: {status}\n📅 تاریخ: {created_at}"
        
        keyboard = None
        if "در انتظار تأیید سرپرست" in status:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ لغو این درخواست", callback_data=f"cancel_{r_code}")]
            ])
        elif "رد شده" in status:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✏️ اصلاح و ارسال مجدد", callback_data=f"editreq_{r_code}")]
            ])
        await callback.message.answer(text, reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data.startswith("cancel_"))
async def cancel_request_cb(callback: CallbackQuery):
    r_code = callback.data.split("_")[1]
    user_id = callback.from_user.id
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, status FROM requests WHERE req_code = ?", (r_code,))
    row = cursor.fetchone()
    if row and row[0] == user_id and "در انتظار تأیید سرپرست" in row[1]:
        cursor.execute("UPDATE requests SET status = '❌ لغو شده توسط پرسنل' WHERE req_code = ?", (r_code,))
        conn.commit()
        conn.close()
        await callback.message.edit_text(callback.message.text + "\n\n**[این درخواست توسط شما لغو شد]**", reply_markup=None)
        await callback.answer("درخواست لغو شد.")
    else:
        conn.close()
        await callback.answer("امکان لغو این درخواست وجود ندارد.", show_alert=True)

# ---------------------------------------------------------
# دستورات کمکی /today
# ---------------------------------------------------------
@dp.message(F.text == "/today")
@dp.callback_query(F.data == "admin_today")
async def cmd_today_leaves(event: Message | CallbackQuery):
    user_id = event.from_user.id
    if user_id not in ADMIN_IDS:
        return
    
    today_jalali = jdatetime.datetime.now().strftime("%Y/%m/%d")
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_name, request_type, col1, col2 FROM requests WHERE status LIKE '%تأیید شده%' AND (col1 LIKE ? OR col2 LIKE ?)", 
                   (f"%{today_jalali}%", f"%{today_jalali}%"))
    rows = cursor.fetchall()
    conn.close()

    msg_text = f"📅 **لیست غایبین / حاضرین در مأموریت ({today_jalali}):**\n\n"
    if not rows:
        msg_text += "امروز هیچ موردی ثبت نشده است."
    else:
        for r in rows:
            msg_text += f"▫️ **{r[0]}** ➔ {r[1]} ({r[2]} | {r[3]})\n"

    if isinstance(event, CallbackQuery):
        await event.message.answer(msg_text)
        await event.answer()
    else:
        await event.answer(msg_text)

# ---------------------------------------------------------
# وظایف پس‌زمینه (یادآور بیمه خودرو و تامین اجتماعی ۲۵ام)
# ---------------------------------------------------------
async def background_schedulers():
    while True:
        try:
            await asyncio.sleep(43200) # هر ۱۲ ساعت
            now_j = jdatetime.datetime.now()
            conn = get_connection()
            cursor = conn.cursor()

            if now_j.day == 25:
                try:
                    await bot.send_message(chat_id=MAIN_ADMIN_ID, text="🚨 **یادآور مالی:** امروز **۲۵ام ماه** است؛ لطفاً بیمه تأمین اجتماعی پرسنل را پرداخت کنید.")
                except Exception:
                    pass

            cursor.execute("SELECT car_code, car_name, plate_number, insurance_company, third_party_date, body_date FROM vehicle_insurances")
            vehicles = cursor.fetchall()

            for v in vehicles:
                code, car, plate, company, third, body = v
                for b_date_str in [third, body]:
                    if not b_date_str or b_date_str == "-":
                        continue
                    try:
                        p = [int(x) for x in b_date_str.replace('-', '/').split('/')]
                        b_date = jdatetime.date(p[0], p[1], p[2])
                        delta_days = (b_date - now_j.date()).days
                        if delta_days == 7:
                            await bot.send_message(chat_id=MAIN_ADMIN_ID, text=f"⚠️ **هشدار بیمه خودرو**\nکد: {code} - {car} (پلاک: {plate})\nبیمه {company} تا **۷ روز دیگر** ({b_date_str}) مهلت دارد.")
                    except Exception:
                        pass
            conn.close()
        except Exception as e:
            print(f"Scheduler error: {e}")
        await asyncio.sleep(43200)

async def main():
    print("Full Unified Enterprise Bot is running with all 3-tier personnel menus...")
    asyncio.create_task(background_schedulers())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())