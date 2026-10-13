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
# تنظیمات اصلی
# ---------------------------------------------------------
TOKEN = os.getenv("BOT_TOKEN", "8865295559:AAEOEDFV-Ikd3rZl6gzyR8V23RIlE7fGcVw")
GROUP_ID = -1003619551361

TOPIC_LEAVE = 2     # تاپیک مرخصی
TOPIC_ADVANCE = 3   # تاپیک مساعده
TOPIC_MISSION = 38  # تاپیک ماموریت
TOPIC_PETTY = 57    # تاپیک تنخواه
TOPIC_ASSETS = 59   # تاپیک تحویل اموال

ADMIN_IDS = [114906446, 827616077]
FINANCE_MANAGER_ID = 114906446 

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
# توابع اعتبارسنجی (فرمت تاریخ اصلاح‌شده: YYYY/DD/MM)
# ---------------------------------------------------------
def validate_custom_date(date_text: str) -> bool:
    # فرمت درخواستی: سال/روز/ماه (YYYY/DD/MM)
    pattern = r'^\d{4}[/-]\d{1,2}[/-]\d{1,2}$'
    if not re.match(pattern, date_text.strip()):
        return False
    try:
        parts = [int(x) for x in date_text.strip().replace('-', '/').split('/')]
        # در jdatetime ترتیب ساخت به صورت (year, month, day) است
        jdatetime.date(parts[0], parts[2], parts[1])
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

# ---------------------------------------------------------
# پایگاه داده (Database)
# ---------------------------------------------------------
def init_db():
    conn = sqlite3.connect("requests.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            leave_balance REAL
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
    
    try:
        cursor.execute("ALTER TABLE staff_mapping ADD COLUMN phone_number TEXT")
    except sqlite3.OperationalError:
        pass

    cursor.execute("SELECT COUNT(*) FROM staff_mapping")
    if cursor.fetchone()[0] == 0:
        for idx, (sname, bal) in enumerate(INITIAL_AUTHORIZED_STAFF.items(), start=1000):
            cursor.execute("INSERT OR IGNORE INTO staff_mapping (user_id, staff_name, leave_balance) VALUES (?, ?, ?)", 
                           (idx, sname, bal))
            
    conn.commit()
    conn.close()

init_db()

def get_finance_manager_id():
    conn = sqlite3.connect("requests.db")
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = 'finance_manager_id'")
    row = cursor.fetchone()
    conn.close()
    if row and row[0].isdigit():
        return int(row[0])
    return FINANCE_MANAGER_ID

def set_finance_manager_id(new_id: int):
    conn = sqlite3.connect("requests.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('finance_manager_id', ?)", (str(new_id),))
    conn.commit()
    conn.close()

# ---------------------------------------------------------
# وضعیت‌های FSM (States)
# ---------------------------------------------------------
class Form(StatesGroup):
    waiting_for_phone = State()
    waiting_for_name_link = State()     # مرحله اول اتصال شماره به نام پرسنل
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
    
    # حالات تحویل اموال شخصی
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

# ---------------------------------------------------------
# توابع کمکی
# ---------------------------------------------------------
def get_staff_info_by_id(user_id: int):
    conn = sqlite3.connect("requests.db")
    cursor = conn.cursor()
    cursor.execute("SELECT staff_name, leave_balance, phone_number FROM staff_mapping WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row if row else (None, 0.0, None)

def get_staff_info_by_phone(phone: str):
    conn = sqlite3.connect("requests.db")
    cursor = conn.cursor()
    cursor.execute("SELECT staff_name, leave_balance FROM staff_mapping WHERE phone_number = ?", (phone,))
    row = cursor.fetchone()
    conn.close()
    return row

def get_holidays_list():
    conn = sqlite3.connect("requests.db")
    cursor = conn.cursor()
    cursor.execute("SELECT h_date FROM holidays")
    rows = [r[0] for r in cursor.fetchall()]
    conn.close()
    return rows

# ---------------------------------------------------------
# دستورات پایه و احراز هویت یک‌باره
# ---------------------------------------------------------
@dp.message(F.text == "/start")
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    staff_name, balance, phone = get_staff_info_by_id(user_id)

    if not staff_name:
        kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="📱 اشتراک‌گذاری شماره تلفن جهت احراز هویت", request_contact=True)]],
            resize_keyboard=True,
            one_time_keyboard=True
        )
        await state.set_state(Form.waiting_for_phone)
        await message.answer("سلام! به سامانه مدیریت پرسنلی خوش آمدید.\nبرای استفاده از ربات و اتصال اکانت خود، لطفا شماره تلفن خود را ارسال نمایید:", reply_markup=kb)
        return

    await show_main_menu(message, staff_name, balance)

@dp.message(Form.waiting_for_phone, F.contact)
async def process_phone_contact(message: Message, state: FSMContext):
    phone = message.contact.phone_number
    # نرمال‌سازی شماره تلفن (پاکسازی +98 یا 0 اول)
    clean_phone = phone.replace("+", "").strip()
    if clean_phone.startswith("98"):
        clean_phone = "0" + clean_phone[2:]

    user_id = message.from_user.id

    # بررسی اینکه آیا این شماره قبلاً در لیست پرسنل ثبت شده است یا خیر
    conn = sqlite3.connect("requests.db")
    cursor = conn.cursor()
    cursor.execute("SELECT staff_name FROM staff_mapping WHERE phone_number = ? OR phone_number = ?", (phone, clean_phone))
    row = cursor.fetchone()

    if row:
        # شماره از قبل وجود دارد، اکانت تلگرام را به آن لینک می‌کنیم
        staff_name = row[0]
        cursor.execute("UPDATE staff_mapping SET user_id = ? WHERE staff_name = ?", (user_id, staff_name))
        conn.commit()
        conn.close()
        await message.answer("✅ اکانت شما با موفقیت به پروفایل پرسنلی متصل شد.", reply_markup=ReplyKeyboardRemove())
        staff_name, balance, _ = get_staff_info_by_id(user_id)
        await show_main_menu(message, staff_name, balance)
    else:
        # شماره در سیستم نیست؛ از کاربر می‌خواهیم نام دقیق خود را وارد کند تا شماره و اکانتش ثبت شود
        await state.update_data(registered_phone=phone)
        cursor.execute("SELECT staff_name FROM staff_mapping WHERE phone_number IS NULL OR phone_number = ''")
        staffs = [r[0] for r in cursor.fetchall()]
        conn.close()
        
        msg = "⚠️ شماره شما در لیست پرسنل یافت نشد یا هنوز متصل نشده است.\nلطفاً **نام و نام خانوادگی خود را دقیقاً مطابق لیست پرسنل** وارد کنید:"
        await state.set_state(Form.waiting_for_name_link)
        await message.answer(msg, reply_markup=ReplyKeyboardRemove())

@dp.message(Form.waiting_for_name_link)
async def process_name_link(message: Message, state: FSMContext):
    entered_name = message.text.strip()
    user_id = message.from_user.id
    data = await state.get_data()
    phone = data.get("registered_phone", "")

    conn = sqlite3.connect("requests.db")
    cursor = conn.cursor()
    cursor.execute("SELECT staff_name FROM staff_mapping WHERE staff_name = ?", (entered_name,))
    row = cursor.fetchone()

    if not row:
        conn.close()
        await message.answer("❌ نام وارد شده در لیست پرسنل مجاز یافت نشد. دوباره نام خود را دقیقاً وارد کنید:")
        return

    cursor.execute("UPDATE staff_mapping SET user_id = ?, phone_number = ? WHERE staff_name = ?", (user_id, phone, entered_name))
    conn.commit()
    conn.close()

    await message.answer(f"✅ احراز هویت با موفقیت برای **{entered_name}** ثبت و به اکانت شما متصل شد.")
    await state.clear()
    staff_name, balance, _ = get_staff_info_by_id(user_id)
    await show_main_menu(message, staff_name, balance)

async def show_main_menu(message: Message, staff_name, balance):
    user_id = message.from_user.id
    keyboard_buttons = [
        [InlineKeyboardButton(text="⏳ درخواست مرخصی", callback_data="req_leave")],
        [InlineKeyboardButton(text="💵 درخواست مساعده (ریال)", callback_data="req_advance")],
        [InlineKeyboardButton(text="📍 ثبت گزارش ماموریت", callback_data="req_mission")],
        [InlineKeyboardButton(text="🧾 ثبت فاکتور تنخواه", callback_data="req_petty")],
        [InlineKeyboardButton(text="🚗 تحویل/ثبت اموال و تجهیزات", callback_data="req_asset")],
        [InlineKeyboardButton(text="📊 وضعیت من (آمار ماه جاری)", callback_data="my_stats")],
        [InlineKeyboardButton(text="📋 پیگیری و لغو درخواست‌ها", callback_data="my_requests")]
    ]
    
    if user_id in ADMIN_IDS:
        keyboard_buttons.append([InlineKeyboardButton(text="⚙️ منوی مدیریت شیشه‌ای", callback_data="admin_panel")])
        keyboard_buttons.append([InlineKeyboardButton(text="📅 مرخصی‌های فعال امروز (/today)", callback_data="admin_today")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    status_text = f"👤 پرسنل: **{staff_name}** | 🌿 مرخصی ذخیره: `{balance} روز`" if staff_name else "⚠️ نام شما ثبت نشده است."
    
    await message.answer(f"سامانه جامع مدیریت پرسنلی\n{status_text}\n\nلطفاً گزینه مورد نظر را انتخاب کنید:", reply_markup=keyboard)

@dp.message(F.text == "/today")
@dp.callback_query(F.data == "admin_today")
async def cmd_today_leaves(event: Message | CallbackQuery):
    user_id = event.from_user.id
    if user_id not in ADMIN_IDS:
        return
    
    today_jalali = jdatetime.datetime.now().strftime("%Y/%m/%d")
    conn = sqlite3.connect("requests.db")
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
# پیگیری و لغو درخواست‌ها توسط پرسنل
# ---------------------------------------------------------
@dp.callback_query(F.data == "my_requests")
async def show_user_requests(callback: CallbackQuery):
    user_id = callback.from_user.id
    conn = sqlite3.connect("requests.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, request_type, col1, col2, col3, status, created_at FROM requests WHERE user_id = ? ORDER BY id DESC LIMIT 5", (user_id,))
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        await callback.answer("شما تاکنون درخواستی ثبت نکرده‌اید.", show_alert=True)
        return

    for r in rows:
        req_id, req_type, c1, c2, c3, status, created_at = r
        text = f"🔹 **کد: #{req_id}** | نوع: {req_type}\n📌 اطلاعات: {c1} | {c2} | {c3}\n📌 وضعیت: {status}\n📅 تاریخ: {created_at}"
        
        keyboard = None
        if "در انتظار تأیید سرپرست" in status:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ لغو این درخواست", callback_data=f"cancel_{req_id}")]
            ])
            
        await callback.message.answer(text, reply_markup=keyboard)

    await callback.answer()

# ---------------------------------------------------------
# آمار و داشبورد پرسنل ("📊 وضعیت من")
# ---------------------------------------------------------
@dp.callback_query(F.data == "my_stats")
async def show_user_stats(callback: CallbackQuery):
    user_id = callback.from_user.id
    staff_name, balance, _ = get_staff_info_by_id(user_id)
    current_month = jdatetime.datetime.now().strftime("%Y/%m")

    conn = sqlite3.connect("requests.db")
    cursor = conn.cursor()
    
    cursor.execute("SELECT location FROM requests WHERE user_id = ? AND request_type = 'مرخصی' AND month_tag = ? AND (status LIKE '%تأیید شده%' OR status LIKE '%پرداخت شده%')", (user_id, current_month))
    leave_rows = cursor.fetchall()
    used_leave = sum([float(r[0]) for r in leave_rows if r[0] and str(r[0]).replace('.', '', 1).isdigit()])

    cursor.execute("SELECT col1 FROM requests WHERE user_id = ? AND request_type = 'مساعده' AND month_tag = ? AND (status LIKE '%تأیید شده%' OR status LIKE '%پرداخت شده%')", (user_id, current_month))
    adv_rows = cursor.fetchall()
    total_adv = 0
    for r in adv_rows:
        text_val = str(r[0])
        digits_only = ''.join(filter(str.isdigit, text_val))
        if digits_only:
            total_adv += int(digits_only)

    cursor.execute("SELECT col2 FROM requests WHERE user_id = ? AND request_type = 'ماموریت' AND month_tag = ? AND (status LIKE '%تأیید شده%' OR status LIKE '%پرداخت شده%')", (user_id, current_month))
    mission_rows = cursor.fetchall()
    total_missions = len(mission_rows)

    conn.close()

    stats_msg = (
        f"📊 **کارنامه و وضعیت ماه جاری ({current_month})**\n\n"
        f"👤 **نام پرسنل:** {staff_name}\n"
        f"🌿 **مرخصی استفاده‌شده ماه:** {used_leave} روز\n"
        f"🍃 **مانده مرخصی کل:** {balance} روز\n"
        f"💵 **مجموع مساعده دریافتی:** {total_adv:,} ریال\n"
        f"📍 **تعداد مأموریت‌ها:** {total_missions} مورد\n"
    )
    await callback.message.answer(stats_msg)
    await callback.answer()

# ---------------------------------------------------------
# پنل مدیریت شیشه‌ای (Interactive Admin Panel)
# ---------------------------------------------------------
@dp.callback_query(F.data == "admin_panel")
@dp.message(F.text == "/admin")
async def show_admin_panel(event: CallbackQuery | Message, state: FSMContext):
    user_id = event.from_user.id
    if user_id not in ADMIN_IDS:
        return

    await state.clear()
    current_fin_id = get_finance_manager_id()
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ افزودن پرسنل جدید", callback_data="admin_add_staff")],
        [InlineKeyboardButton(text="✏️ ویرایش مانده مرخصی", callback_data="admin_edit_balance")],
        [InlineKeyboardButton(text="🚗 تحویل اموال به پرسنل (توسط مدیر)", callback_data="admin_asset_start")],
        [InlineKeyboardButton(text="🗓️ افزودن تعطیل رسمی", callback_data="admin_add_holiday")],
        [InlineKeyboardButton(text=f"💳 تغییر آیدی مسئول مالی (فعلی: {current_fin_id})", callback_data="admin_set_finance")],
        [InlineKeyboardButton(text="📦 دانلود فوری بکاپ دیتابیس", callback_data="admin_get_backup")]
    ])
    
    text = "⚙️ **پنل مدیریت شیشه‌ای پرسنل**\n\nلطفاً گزینه مورد نظر را انتخاب نمایید:"
    if isinstance(event, CallbackQuery):
        await event.message.answer(text, reply_markup=keyboard)
        await event.answer()
    else:
        await event.answer(text, reply_markup=keyboard)

@dp.callback_query(F.data == "admin_set_finance")
async def admin_set_finance_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminForm.set_finance_id)
    await callback.message.answer("💳 **تغییر مسئول واحد مالی**\n\nلطفاً **User ID تلگرام** (یک عدد مانند `114906446`) مسئول جدید مالی را وارد کنید:")
    await callback.answer()

@dp.message(AdminForm.set_finance_id)
async def admin_set_finance_save(message: Message, state: FSMContext):
    val = message.text.strip()
    if not val.isdigit():
        await message.answer("❌ شناسه باید فقط **عدد** (User ID) باشد. دوباره وارد کنید:")
        return

    set_finance_manager_id(int(val))
    await message.answer(f"✅ مسئول واحد مالی به شناسه `{val}` با موفقیت تغییر یافت.")
    await state.clear()

@dp.callback_query(F.data == "admin_get_backup")
async def admin_backup_cb(callback: CallbackQuery):
    if callback.from_user.id in ADMIN_IDS and os.path.exists("requests.db"):
        await callback.message.answer_document(FSInputFile("requests.db"), caption="📦 پشتیبان دیتابیس")
        await callback.answer()

@dp.callback_query(F.data == "admin_add_holiday")
async def admin_add_holiday_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminForm.add_holiday_date)
    await callback.message.answer("🗓️ تاریخ تعطیل رسمی را با فرمت `سال/روز/ماه` (`YYYY/DD/MM`) وارد کنید:")
    await callback.answer()

@dp.message(AdminForm.add_holiday_date)
async def admin_save_holiday(message: Message, state: FSMContext):
    h_date = message.text.strip()
    if not validate_custom_date(h_date):
        await message.answer("❌ فرمت تاریخ نامعتبر است! با فرمت `سال/روز/ماه` (`YYYY/DD/MM`) وارد کنید:")
        return

    conn = sqlite3.connect("requests.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO holidays (h_date, description) VALUES (?, ?)", (h_date, "تعطیل رسمی"))
    conn.commit()
    conn.close()

    await message.answer(f"✅ تاریخ `{h_date}` به عنوان تعطیل رسمی ثبت شد.")
    await state.clear()

@dp.callback_query(F.data == "admin_add_staff")
async def admin_add_staff_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return
    await state.set_state(AdminForm.add_staff_name)
    await callback.message.answer("➕ **افزودن پرسنل جدید**\n\nنام و نام خانوادگی پرسنل را وارد کنید:")
    await callback.answer()

@dp.message(AdminForm.add_staff_name)
async def admin_add_staff_name_step(message: Message, state: FSMContext):
    name = message.text.strip()
    await state.update_data(new_staff_name=name)
    await state.set_state(AdminForm.add_staff_balance)
    await message.answer(f"مقدار مرخصی ذخیره اولیه برای ({name}) را به عدد وارد کنید:")

@dp.message(AdminForm.add_staff_balance)
async def admin_add_staff_balance_step(message: Message, state: FSMContext):
    try:
        balance = float(message.text.strip())
    except ValueError:
        await message.answer("❌ فقط عدد مجاز است. دوباره وارد کنید:")
        return

    user_data = await state.get_data()
    name = user_data.get("new_staff_name")

    conn = sqlite3.connect("requests.db")
    cursor = conn.cursor()
    cursor.execute("SELECT IFNULL(MAX(user_id), 1000) + 1 FROM staff_mapping")
    dummy_id = cursor.fetchone()[0]
    
    try:
        cursor.execute("INSERT INTO staff_mapping (user_id, staff_name, leave_balance) VALUES (?, ?, ?)", (dummy_id, name, balance))
        conn.commit()
        await message.answer(f"✅ پرسنل **{name}** با {balance} روز مرخصی اضافه شد.")
    except Exception:
        await message.answer("⚠️ خطایی رخ داد یا پرسنل از قبل وجود دارد.")
    conn.close()
    await state.clear()

@dp.callback_query(F.data == "admin_edit_balance")
async def admin_edit_balance_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return
    
    conn = sqlite3.connect("requests.db")
    cursor = conn.cursor()
    cursor.execute("SELECT staff_name, leave_balance FROM staff_mapping ORDER BY staff_name")
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        await callback.message.answer("هیچ پرسنلی یافت نشد.")
        return

    msg_text = "✏️ **لیست پرسنل و مانده مرخصی فعلی:**\n\n"
    for r in rows:
        msg_text += f"▫️ `{r[0]}` ➔ **{r[1]} روز**\n"
    
    msg_text += "\nلطفاً **نام و نام خانوادگی دقیق** پرسنل را تایپ کنید:"
    await state.set_state(AdminForm.edit_balance_select_user)
    await callback.message.answer(msg_text)
    await callback.answer()

@dp.message(AdminForm.edit_balance_select_user)
async def admin_edit_balance_user_selected(message: Message, state: FSMContext):
    name = message.text.strip()
    conn = sqlite3.connect("requests.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, leave_balance FROM staff_mapping WHERE staff_name = ?", (name,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        await message.answer("❌ نام وارد شده در لیست پرسنل یافت نشد. لطفاً نام را دقیقاً مشابه لیست بالا تایپ کنید:")
        return

    await state.update_data(target_staff_name=name)
    await state.set_state(AdminForm.edit_balance_new_value)
    await message.answer(f"مقدار **جدید مرخصی ذخیره** برای ({name}) را به **عدد** وارد کنید:")

@dp.message(AdminForm.edit_balance_new_value)
async def admin_edit_balance_save(message: Message, state: FSMContext):
    try:
        new_balance = float(message.text.strip())
    except ValueError:
        await message.answer("❌ ورودی نامعتبر! فقط عدد مجاز است (مثلاً 10.5). دوباره وارد کنید:")
        return

    user_data = await state.get_data()
    target_name = user_data.get("target_staff_name")

    conn = sqlite3.connect("requests.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE staff_mapping SET leave_balance = ? WHERE staff_name = ?", (new_balance, target_name))
    conn.commit()
    conn.close()

    await message.answer(f"✅ مانده مرخصی پرسنل **{target_name}** با موفقیت به **{new_balance} روز** تغییر یافت.")
    await state.clear()

# ---------------------------------------------------------
# 🚗 بخش تحویل اموال توسط مدیر به پرسنل خاص
# ---------------------------------------------------------
@dp.callback_query(F.data == "admin_asset_start")
async def admin_asset_select_staff_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return
    
    conn = sqlite3.connect("requests.db")
    cursor = conn.cursor()
    cursor.execute("SELECT staff_name FROM staff_mapping ORDER BY staff_name")
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        await callback.answer("هیچ پرسنلی ثبت نشده است.", show_alert=True)
        return

    msg_text = "👤 **انتخاب پرسنل برای تحویل اموال:**\n\nنام و نام خانوادگی دقیق پرسنل مورد نظر را تایپ کنید:\n\n"
    for r in rows:
        msg_text += f"▫️ `{r[0]}`\n"

    await state.set_state(AdminForm.admin_asset_select_staff)
    await callback.message.answer(msg_text)
    await callback.answer()

@dp.message(AdminForm.admin_asset_select_staff)
async def admin_asset_staff_chosen(message: Message, state: FSMContext):
    staff_name = message.text.strip()
    conn = sqlite3.connect("requests.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM staff_mapping WHERE staff_name = ?", (staff_name,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        await message.answer("❌ پرسنلی با این نام یافت نشد. لطفاً نام را دقیقاً مشابه لیست تایپ کنید:")
        return

    await state.update_data(target_staff_name=staff_name, target_user_id=row[0])
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚗 خودروی سازمانی", callback_data="adm_asset_خودرو")],
        [InlineKeyboardButton(text="⛽ کارت سوخت", callback_data="adm_asset_کارت_سوخت")],
        [InlineKeyboardButton(text="💳 کارت‌خوان (POS)", callback_data="adm_asset_کارتخوان")],
        [InlineKeyboardButton(text="🖨️ پرینتر جیبی", callback_data="adm_asset_پرینتر")]
    ])
    await message.answer(f"✅ پرسنل انتخاب شد: **{staff_name}**\n\nلطفاً نوع قلم امانی را انتخاب کنید:", reply_markup=kb)

@dp.callback_query(F.data == "adm_asset_خودرو")
async def admin_car_1(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminForm.admin_asset_car_code)
    await callback.message.answer("🚗 **[مدیر] خودروی سازمانی - [۱/۵]**\n\nلطفاً **کد خودرو** را وارد کنید:")
    await callback.answer()

@dp.message(AdminForm.admin_asset_car_code)
async def admin_car_2(message: Message, state: FSMContext):
    await state.update_data(car_code=message.text.strip())
    await state.set_state(AdminForm.admin_asset_car_type)
    await message.answer("🚗 **[مدیر] خودروی سازمانی - [۲/۵]**\n\nلطفاً **نوع خودرو** (مثل پراید یا آریسان) را وارد کنید:")

@dp.message(AdminForm.admin_asset_car_type)
async def admin_car_3(message: Message, state: FSMContext):
    await state.update_data(car_type=message.text.strip())
    await state.set_state(AdminForm.admin_asset_car_plate)
    await message.answer("🚗 **[مدیر] خودروی سازمانی - [۳/۵]**\n\nلطفاً **پلاک خودرو** را وارد کنید:")

@dp.message(AdminForm.admin_asset_car_plate)
async def admin_car_4(message: Message, state: FSMContext):
    await state.update_data(car_plate=message.text.strip())
    await state.set_state(AdminForm.admin_asset_car_km)
    await message.answer("🚗 **[مدیر] خودروی سازمانی - [۴/۵]**\n\nلطفاً **کیلومتر تحویلی** را به عدد وارد کنید:")

@dp.message(AdminForm.admin_asset_car_km)
async def admin_car_5(message: Message, state: FSMContext):
    if not message.text.strip().isdigit():
        await message.answer("❌ کیلومتر باید عدد باشد:")
        return
    await state.update_data(car_km=message.text.strip())
    await state.set_state(AdminForm.admin_asset_car_desc)
    await message.answer("🚗 **[مدیر] خودروی سازمانی - [۵/۵]**\n\nتوضیحات تکمیلی (در صورت نداشتن، `-` بگذارید):")

@dp.message(AdminForm.admin_asset_car_desc)
async def admin_car_finish(message: Message, state: FSMContext):
    desc = message.text.strip()
    data = await state.get_data()
    
    col1 = f"کد: {data.get('car_code')} | نوع: {data.get('car_type')}"
    col2 = f"پلاک: {data.get('car_plate')} | کیلومتر: {data.get('car_km')}"
    col3 = f"توضیحات: {desc}"
    
    await finalize_admin_asset(message, state, "خودروی سازمانی", col1, col2, col3)

@dp.callback_query(F.data == "adm_asset_کارت_سوخت")
async def admin_fuel_1(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminForm.admin_asset_fuel_code)
    await callback.message.answer("⛽ **[مدیر] کارت سوخت - [۱/۲]**\n\nلطفاً **کد کارت سوخت** را وارد کنید:")
    await callback.answer()

@dp.message(AdminForm.admin_asset_fuel_code)
async def admin_fuel_2(message: Message, state: FSMContext):
    await state.update_data(fuel_code=message.text.strip())
    await state.set_state(AdminForm.admin_asset_fuel_pass)
    await message.answer("⛽ **[مدیر] کارت سوخت - [۲/۲]**\n\nلطفاً **رمز کارت سوخت** را وارد کنید:")

@dp.message(AdminForm.admin_asset_fuel_pass)
async def admin_fuel_finish(message: Message, state: FSMContext):
    f_pass = message.text.strip()
    data = await state.get_data()
    
    col1 = f"کد کارت سوخت: {data.get('fuel_code')}"
    col2 = f"رمز: {f_pass}"
    col3 = "-"
    
    await finalize_admin_asset(message, state, "کارت سوخت", col1, col2, col3)

@dp.callback_query(F.data == "adm_asset_کارتخوان")
async def admin_pos_1(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminForm.admin_asset_pos_code)
    await callback.message.answer("💳 **[مدیر] کارت‌خوان (POS) - [۱/۳]**\n\nلطفاً **کد دستگاه** را وارد کنید:")
    await callback.answer()

@dp.message(AdminForm.admin_asset_pos_code)
async def admin_pos_2(message: Message, state: FSMContext):
    await state.update_data(pos_code=message.text.strip())
    await state.set_state(AdminForm.admin_asset_pos_bank)
    await message.answer("💳 **[مدیر] کارت‌خوان (POS) - [۲/۳]**\n\nلطفاً **نام بانک** را وارد کنید:")

@dp.message(AdminForm.admin_asset_pos_bank)
async def admin_pos_3(message: Message, state: FSMContext):
    await state.update_data(pos_bank=message.text.strip())
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ بله، شارژر دارد", callback_data="adm_pos_yes"),
         InlineKeyboardButton(text="❌ خیر، ندارد", callback_data="adm_pos_no")]
    ])
    await message.answer("💳 **[مدیر] کارت‌خوان (POS) - [۳/۳]**\n\nآیا دستگاه **شارژر** دارد؟", reply_markup=kb)

@dp.callback_query(F.data.startswith("adm_pos_"))
async def admin_pos_finish(callback: CallbackQuery, state: FSMContext):
    if await state.get_state() is None:
        await callback.answer("قبلاً ثبت شده است.", show_alert=True)
        return
    charger = "دارد" if "yes" in callback.data else "ندارد"
    data = await state.get_data()
    
    col1 = f"کد پوز: {data.get('pos_code')}"
    col2 = f"بانک: {data.get('pos_bank')}"
    col3 = f"شارژر: {charger}"
    
    await finalize_admin_asset(callback.message, state, "کارت‌خوان", col1, col2, col3)
    await callback.answer()

@dp.callback_query(F.data == "adm_asset_پرینتر")
async def admin_printer_1(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminForm.admin_asset_printer_code)
    await callback.message.answer("🖨️ **[مدیر] پرینتر جیبی - [۱/۲]**\n\nلطفاً **کد پرینتر** را وارد کنید:")
    await callback.answer()

@dp.message(AdminForm.admin_asset_printer_code)
async def admin_printer_2(message: Message, state: FSMContext):
    await state.update_data(printer_code=message.text.strip())
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ بله، شارژر دارد", callback_data="adm_printer_yes"),
         InlineKeyboardButton(text="❌ خیر، ندارد", callback_data="adm_printer_no")]
    ])
    await message.answer("🖨️ **[مدیر] پرینتر جیبی - [۲/۲]**\n\nآیا پرینتر **شارژر** دارد؟", reply_markup=kb)

@dp.callback_query(F.data.startswith("adm_printer_"))
async def admin_printer_finish(callback: CallbackQuery, state: FSMContext):
    if await state.get_state() is None:
        await callback.answer("قبلاً ثبت شده است.", show_alert=True)
        return
    charger = "دارد" if "yes" in callback.data else "ندارد"
    data = await state.get_data()
    
    col1 = f"کد پرینتر: {data.get('printer_code')}"
    col2 = f"شارژر: {charger}"
    col3 = "-"
    
    await finalize_admin_asset(callback.message, state, "پرینتر جیبی", col1, col2, col3)
    await callback.answer()

async def finalize_admin_asset(message_obj, state, asset_type, col1, col2, col3):
    data = await state.get_data()
    staff_name = data.get("target_staff_name")
    target_uid = data.get("target_user_id")
    
    now_j = jdatetime.datetime.now()
    created_at = now_j.strftime("%Y/%m/%d %H:%M")
    month_tag = now_j.strftime("%Y/%m")

    conn = sqlite3.connect("requests.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO requests (user_id, user_name, telegram_info, request_type, col1, col2, col3, location, status, created_at, month_tag) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (target_uid, staff_name, "ثبت توسط مدیر", "تحویل اموال", col1, col2, col3, asset_type, "✅ تأیید شده قطعی", created_at, month_tag))
    req_id = cursor.lastrowid
    conn.commit()
    conn.close()

    text = (
        f"🚗 **تحویل اموال / تجهیزات به پرسنل (توسط مدیر)**\n"
        f"🔹 **کد ثبت:** #{req_id}\n\n"
        f"👤 پرسنل تحویل‌گیرنده: **{staff_name}**\n"
        f"📦 نوع: {asset_type}\n"
        f"📌 {col1}\n"
        f"📌 {col2}\n"
        f"📌 {col3}\n"
        f"📅 تاریخ ثبت: {created_at}\n"
        f"وضعیت: ✅ تأیید شده قطعی (توسط مدیریت)"
    )

    try:
        await bot.send_message(chat_id=GROUP_ID, message_thread_id=TOPIC_ASSETS, text=text)
        if isinstance(message_obj, Message):
            await message_obj.answer(f"✅ مال مورد نظر با موفقیت به نام **{staff_name}** ثبت شد.")
        else:
            await message_obj.answer(f"✅ مال مورد نظر با موفقیت به نام **{staff_name}** ثبت شد.")
    except Exception:
        pass

    await state.clear()

# ---------------------------------------------------------
# بخش تحویل اموال و تجهیزات توسط پرسنل (عادی)
# ---------------------------------------------------------
@dp.callback_query(F.data == "req_asset")
async def process_asset_start(callback: CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚗 خودروی سازمانی", callback_data="asset_sel_خودرو")],
        [InlineKeyboardButton(text="⛽ کارت سوخت", callback_data="asset_sel_کارت_سوخت")],
        [InlineKeyboardButton(text="💳 کارت‌خوان (POS)", callback_data="asset_sel_کارتخوان")],
        [InlineKeyboardButton(text="🖨️ پرینتر جیبی", callback_data="asset_sel_پرینتر")]
    ])
    await callback.message.answer("🚗 **ثبت تحویل اقلام امانی و تجهیزات**\n\nلطفاً قلم مورد نظر را انتخاب کنید:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data == "asset_sel_خودرو")
async def asset_car_step1(callback: CallbackQuery, state: FSMContext):
    await state.set_state(Form.asset_car_code)
    await callback.message.answer("🚗 **[۱/۵] خودروی سازمانی**\n\nلطفاً **کد خودرو** را وارد کنید:")
    await callback.answer()

@dp.message(Form.asset_car_code)
async def asset_car_step2(message: Message, state: FSMContext):
    await state.update_data(car_code=message.text.strip())
    await state.set_state(Form.asset_car_type)
    await message.answer("🚗 **[۲/۵] خودروی سازمانی**\n\nلطفاً **نوع خودرو** (مثلاً پراید یا آریسان) را وارد کنید:")

@dp.message(Form.asset_car_type)
async def asset_car_step3(message: Message, state: FSMContext):
    await state.update_data(car_type=message.text.strip())
    await state.set_state(Form.asset_car_plate)
    await message.answer("🚗 **[۳/۵] خودروی سازمانی**\n\nلطفاً **پلاک خودرو** را وارد کنید:")

@dp.message(Form.asset_car_plate)
async def asset_car_step4(message: Message, state: FSMContext):
    await state.update_data(car_plate=message.text.strip())
    await state.set_state(Form.asset_car_km)
    await message.answer("🚗 **[۴/۵] خودروی سازمانی**\n\nلطفاً **کیلومتر تحویلی** را به عدد وارد کنید:")

@dp.message(Form.asset_car_km)
async def asset_car_step5(message: Message, state: FSMContext):
    if not message.text.strip().isdigit():
        await message.answer("❌ کیلومتر باید عدد باشد:")
        return
    await state.update_data(car_km=message.text.strip())
    await state.set_state(Form.asset_car_desc)
    await message.answer("🚗 **[۵/۵] خودروی سازمانی**\n\nتوضیحات تکمیلی را بنویسید (در صورت نداشتن، `-` بگذارید):")

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
    await callback.message.answer("⛽ **[۱/۲] کارت سوخت**\n\nلطفاً **کد کارت سوخت** را وارد کنید:")
    await callback.answer()

@dp.message(Form.asset_fuel_code)
async def asset_fuel_step2(message: Message, state: FSMContext):
    await state.update_data(fuel_code=message.text.strip())
    await state.set_state(Form.asset_fuel_pass)
    await message.answer("⛽ **[۲/۲] کارت سوخت**\n\nلطفاً **رمز کارت سوخت** را وارد کنید:")

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
    await callback.message.answer("💳 **[۱/۳] کارت‌خوان (POS)**\n\nلطفاً **کد دستگاه کارت‌خوان** را وارد کنید:")
    await callback.answer()

@dp.message(Form.asset_pos_code)
async def asset_pos_step2(message: Message, state: FSMContext):
    await state.update_data(pos_code=message.text.strip())
    await state.set_state(Form.asset_pos_bank)
    await message.answer("💳 **[۲/۳] کارت‌خوان (POS)**\n\nلطفاً **نام بانک** مربوطه را وارد کنید:")

@dp.message(Form.asset_pos_bank)
async def asset_pos_step3(message: Message, state: FSMContext):
    bank_name = message.text.strip()
    await state.update_data(pos_bank=bank_name)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ بله، شارژر دارد", callback_data="pos_charger_yes"),
         InlineKeyboardButton(text="❌ خیر، ندارد", callback_data="pos_charger_no")]
    ])
    await message.answer("💳 **[۳/۳] کارت‌خوان (POS)**\n\nآیا دستگاه **شارژر** دارد؟", reply_markup=kb)

@dp.callback_query(F.data.startswith("pos_charger_"))
async def asset_pos_finish(callback: CallbackQuery, state: FSMContext):
    if await state.get_state() is None:
        await callback.answer("این درخواست قبلاً ثبت شده است.", show_alert=True)
        return

    charger_status = "دارد" if "yes" in callback.data else "ندارد"
    data = await state.get_data()
    
    col1 = f"کد پوز: {data.get('pos_code')}"
    col2 = f"بانک: {data.get('pos_bank')}"
    col3 = f"شارژر: {charger_status}"
    
    await finalize_asset_request(callback.message, state, "کارت‌خوان", col1, col2, col3)
    await callback.answer()

@dp.callback_query(F.data == "asset_sel_پرینتر")
async def asset_printer_step1(callback: CallbackQuery, state: FSMContext):
    await state.set_state(Form.asset_printer_code)
    await callback.message.answer("🖨️ **[۱/۲] پرینتر جیبی**\n\nلطفاً **کد پرینتر** را وارد کنید:")
    await callback.answer()

@dp.message(Form.asset_printer_code)
async def asset_printer_step2(message: Message, state: FSMContext):
    p_code = message.text.strip()
    await state.update_data(printer_code=p_code)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ بله، شارژر دارد", callback_data="printer_charger_yes"),
         InlineKeyboardButton(text="❌ خیر، ندارد", callback_data="printer_charger_no")]
    ])
    await message.answer("🖨️ **[۲/۲] پرینتر جیبی**\n\nآیا پرینتر **شارژر** دارد؟", reply_markup=kb)

@dp.callback_query(F.data.startswith("printer_charger_"))
async def asset_printer_finish(callback: CallbackQuery, state: FSMContext):
    if await state.get_state() is None:
        await callback.answer("این درخواست قبلاً ثبت شده است.", show_alert=True)
        return

    charger_status = "دارد" if "yes" in callback.data else "ندارد"
    data = await state.get_data()
    
    col1 = f"کد پرینتر: {data.get('printer_code')}"
    col2 = f"شارژر: {charger_status}"
    col3 = "-"
    
    await finalize_asset_request(callback.message, state, "پرینتر جیبی", col1, col2, col3)
    await callback.answer()

async def finalize_asset_request(message_obj, state, asset_type, col1, col2, col3):
    user_id = message_obj.chat.id
    staff_name, _, _ = get_staff_info_by_id(user_id)
    
    now_j = jdatetime.datetime.now()
    created_at = now_j.strftime("%Y/%m/%d %H:%M")
    month_tag = now_j.strftime("%Y/%m")

    conn = sqlite3.connect("requests.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO requests (user_id, user_name, telegram_info, request_type, col1, col2, col3, location, status, created_at, month_tag) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_id, staff_name, message_obj.from_user.full_name if hasattr(message_obj, 'from_user') else "تجهیزات", "تحویل اموال", col1, col2, col3, asset_type, "⏳ در انتظار تأیید سرپرست", created_at, month_tag))
    req_id = cursor.lastrowid
    conn.commit()
    conn.close()

    text = (
        f"🚗 **گزارش تحویل اموال / تجهیزات (کد: #{req_id})**\n\n"
        f"👤 پرسنل تحویل‌گیرنده: {staff_name}\n"
        f"📦 نوع: {asset_type}\n"
        f"📌 {col1}\n"
        f"📌 {col2}\n"
        f"📌 {col3}\n"
        f"📅 تاریخ ثبت: {created_at}\n"
        f"وضعیت: ⏳ در انتظار تأیید سرپرست"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 تأیید سرپرست ➔ ارسال به مدیریت", callback_data=f"step1_{req_id}")]
    ])

    try:
        await bot.send_message(chat_id=GROUP_ID, message_thread_id=TOPIC_ASSETS, text=text, reply_markup=kb)
        if isinstance(message_obj, Message):
            await message_obj.answer(f"✅ فرم تحویل اموال ({asset_type}) با کد #{req_id} ثبت و ارسال شد.")
        else:
            await message_obj.answer(f"✅ فرم تحویل اموال ({asset_type}) با کد #{req_id} ثبت و ارسال شد.")
    except Exception:
        pass

    await state.clear()

# ---------------------------------------------------------
# ثبت فاکتور تنخواه (Petty Cash)
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
        await message.answer("❌ مبلغ فقط باید **عدد** باشد. دوباره وارد کنید:")
        return

    await state.update_data(petty_amount=f"{int(raw_val):,} ریال")
    await state.set_state(Form.waiting_for_petty_desc)
    await message.answer("3️⃣ لطفاً **بابت / شرح هزینه** را بنویسید:")

@dp.message(Form.waiting_for_petty_desc)
async def receive_petty_desc(message: Message, state: FSMContext):
    desc = message.text.strip()
    user_data = await state.get_data()
    user_id = message.from_user.id
    staff_name, _, _ = get_staff_info_by_id(user_id)

    photo_id = user_data.get("petty_photo")
    amount_str = user_data.get("petty_amount")

    now_jalali = jdatetime.datetime.now().strftime("%Y/%m/%d %H:%M")
    month_tag = jdatetime.datetime.now().strftime("%Y/%m")

    conn = sqlite3.connect("requests.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO requests (user_id, user_name, telegram_info, request_type, col1, col2, col3, location, status, created_at, month_tag) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_id, staff_name, message.from_user.full_name, "تنخواه", f"مبلغ: {amount_str}", f"بابت: {desc}", "-", photo_id, "⏳ در انتظار تأیید سرپرست", now_jalali, month_tag))
    req_id = cursor.lastrowid
    conn.commit()
    conn.close()

    caption = (f"🧾 **فاکتور تنخواه جدید (کد: #{req_id})**\n\n"
               f"👤 پرسنل: {staff_name}\n"
               f"💵 مبلغ: {amount_str}\n"
               f"📝 بابت: {desc}\n"
               f"📅 تاریخ: {now_jalali}\n"
               f"وضعیت: ⏳ در انتظار تأیید سرپرست")

    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 تأیید سرپرست ➔ ارسال به مدیریت", callback_data=f"step1_{req_id}")],
        [InlineKeyboardButton(text="❌ رد فاکتور", callback_data=f"reject_{req_id}")]
    ])

    try:
        await bot.send_photo(chat_id=GROUP_ID, message_thread_id=TOPIC_PETTY, photo=photo_id, caption=caption, reply_markup=admin_kb)
        await message.answer(f"✅ فاکتور تنخواه شما (کد: #{req_id}) ثبت و به تاپیک تنخواه ارسال شد.")
    except Exception as e:
        print(f"❌ خطا در ارسال فاکتور تنخواه: {e}")
        await message.answer("❌ خطا در ارسال فاکتور به تاپیک تنخواه.")

    await state.clear()

# ---------------------------------------------------------
# شروع درخواست‌های مرخصی، مساعده، ماموریت (بدون پرسش نام به دلیل اتصال به اکانت)
# ---------------------------------------------------------
@dp.callback_query(F.data.in_({"req_leave", "req_advance", "req_mission"}))
async def process_request_start(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    staff_name, _, _ = get_staff_info_by_id(user_id)
    
    if not staff_name:
        await callback.answer("⚠️ ابتدا باید با دستور /start احراز هویت کنید.", show_alert=True)
        return

    if callback.data == "req_leave":
        req_type = "مرخصی"
    elif callback.data == "req_advance":
        req_type = "مساعده"
    else:
        req_type = "ماموریت"

    await state.update_data(current_request_type=req_type)

    if req_type == "مرخصی":
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="استحقاقی", callback_data="ltype_استحقاقی")],
            [InlineKeyboardButton(text="استعلاجی", callback_data="ltype_استعلاجی")],
            [InlineKeyboardButton(text="ساعتی", callback_data="ltype_ساعتی")],
            [InlineKeyboardButton(text="بدون حقوق", callback_data="ltype_بدون_حقوق")]
        ])
        await callback.message.answer("نوع مرخصی را انتخاب کنید:", reply_markup=kb)
        await state.set_state(Form.waiting_for_leave_type)
    elif req_type == "مساعده":
        await state.set_state(Form.waiting_for_advance_amount)
        await callback.message.answer("مبلغ درخواستی مساعده (به ریال) را به عدد وارد کنید:")
    else:
        await state.set_state(Form.waiting_for_mission_city)
        await callback.message.answer("شهر مقصد ماموریت را وارد کنید:")
    await callback.answer()

@dp.callback_query(Form.waiting_for_leave_type, F.data.startswith("ltype_"))
async def process_leave_type_selected(callback: CallbackQuery, state: FSMContext):
    ltype = callback.data.split("_")[1]
    await state.update_data(leave_type=ltype)
    
    if ltype == "ساعتی":
        await state.set_state(Form.waiting_for_hourly_date)
        await callback.message.answer("تاریخ روز مرخصی را با فرمت `سال/روز/ماه` (`YYYY/DD/MM`) وارد کنید:")
    else:
        await state.set_state(Form.waiting_for_leave_start_date)
        await callback.message.answer(f"تاریخ خروج (شروع مرخصی) را با فرمت `سال/روز/ماه` (`YYYY/DD/MM`) وارد کنید:")
    await callback.answer()

@dp.message(Form.waiting_for_hourly_date)
async def receive_hourly_date(message: Message, state: FSMContext):
    if not validate_custom_date(message.text):
        await message.answer("❌ فرمت تاریخ نامعتبر است! با فرمت `سال/روز/ماه` (`YYYY/DD/MM`) وارد کنید:")
        return
    await state.update_data(hourly_date=message.text.strip())
    await state.set_state(Form.waiting_for_hourly_times)
    await message.answer("ساعت خروج و ورود را وارد کنید (مثلاً: 09:00 تا 13:00):")

@dp.message(Form.waiting_for_hourly_times)
async def receive_hourly_times(message: Message, state: FSMContext):
    user_data = await state.get_data()
    user_id = message.from_user.id
    staff_name, balance, _ = get_staff_info_by_id(user_id)
    
    leave_date = user_data.get("hourly_date")
    times = message.text.strip()
    
    col1 = f"تاریخ: {leave_date}"
    col2 = f"ساعت: {times}"
    col3 = "مدت: ساعتی"
    details = f"تاریخ: {leave_date} | ساعت: {times}"

    await finalize_leave_request(message, user_id, staff_name, balance, col1, col2, col3, details, 0.0)

@dp.message(Form.waiting_for_leave_start_date)
async def receive_leave_start(message: Message, state: FSMContext):
    if not validate_custom_date(message.text):
        await message.answer("❌ فرمت تاریخ نامعتبر است! با فرمت `سال/روز/ماه` (`YYYY/DD/MM`) وارد کنید:")
        return
    await state.update_data(leave_start=message.text.strip())
    await state.set_state(Form.waiting_for_leave_end_date)
    await message.answer("تاریخ ورود (پایان مرخصی) را با فرمت `سال/روز/ماه` (`YYYY/DD/MM`) وارد کنید:")

@dp.message(Form.waiting_for_leave_end_date)
async def receive_leave_end(message: Message, state: FSMContext):
    if not validate_custom_date(message.text):
        await message.answer("❌ فرمت تاریخ نامعتبر است! با فرمت `سال/روز/ماه` (`YYYY/DD/MM`) وارد کنید:")
        return

    user_data = await state.get_data()
    user_id = message.from_user.id
    staff_name, balance, _ = get_staff_info_by_id(user_id)
    
    start_str = user_data.get("leave_start")
    end_str = message.text.strip()
    holidays = get_holidays_list()

    calculated_days = 1.0
    try:
        s_p = [int(x) for x in start_str.replace('-', '/').split('/')]
        e_p = [int(x) for x in end_str.replace('-', '/').split('/')]
        d1 = jdatetime.date(s_p[0], s_p[2], s_p[1])
        d2 = jdatetime.date(e_p[0], e_p[2], e_p[1])
        
        current_d = d1
        working_days = 0
        while current_d <= d2:
            d_str = current_d.strftime("%Y/%d/%m")
            if current_d.weekday() != 6 and d_str not in holidays:
                working_days += 1
            current_d += jdatetime.timedelta(days=1)
        calculated_days = float(working_days) if working_days > 0 else 1.0
    except Exception:
        calculated_days = 1.0

    col1 = f"خروج: {start_str}"
    col2 = f"ورود: {end_str}"
    col3 = f"تعداد روز کسر: {calculated_days} روز"
    details = f"خروج: {start_str} | ورود: {end_str} | کسر از مرخصی: {calculated_days} روز"

    await finalize_leave_request(message, user_id, staff_name, balance, col1, col2, col3, details, calculated_days)

async def finalize_leave_request(message, user_id, user_name, balance, col1, col2, col3, details, days_to_deduct):
    now_j = jdatetime.datetime.now()
    created_at = now_j.strftime("%Y/%d/%m %H:%M")
    month_tag = now_j.strftime("%Y/%m")
    
    conn = sqlite3.connect("requests.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO requests (user_id, user_name, telegram_info, request_type, col1, col2, col3, location, status, created_at, month_tag) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_id, user_name, message.from_user.full_name, "مرخصی", col1, col2, col3, str(days_to_deduct), "⏳ در انتظار تأیید سرپرست", created_at, month_tag))
    req_id = cursor.lastrowid
    conn.commit()
    conn.close()

    text = f"📩 **درخواست مرخصی (کد: #{req_id})**\n\n👤 پرسنل: {user_name} (مانده: {balance} روز)\n📝 {details}\n📅 ثبت: {created_at}\nوضعیت: ⏳ در انتظار تأیید سرپرست"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="👤 تأیید سرپرست ➔ ارسال به مدیریت", callback_data=f"step1_{req_id}")]])

    try:
        await bot.send_message(chat_id=GROUP_ID, message_thread_id=TOPIC_LEAVE, text=text, reply_markup=kb)
        await message.answer(f"✅ درخواست مرخصی شما (کد: #{req_id}) ثبت شد.")
    except Exception:
        await message.answer("❌ خطا در ارسال به گروه.")
    await state.clear()

# ---------------------------------------------------------
# مساعده با سقف پویا
# ---------------------------------------------------------
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
    staff_name, _, _ = get_staff_info_by_id(user_id)
    
    amount = user_data.get("advance_amount")
    card = user_data.get("advance_card")
    now_j = jdatetime.datetime.now()
    created_at = now_j.strftime("%Y/%d/%m %H:%M")
    month_tag = now_j.strftime("%Y/%m")

    conn = sqlite3.connect("requests.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO requests (user_id, user_name, telegram_info, request_type, col1, col2, col3, location, status, created_at, month_tag) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_id, staff_name, message.from_user.full_name, "مساعده", f"مبلغ: {amount}", f"دلیل: {reason}", f"کارت: {card}", "ندارد", "⏳ در انتظار تأیید سرپرست", created_at, month_tag))
    req_id = cursor.lastrowid
    conn.commit()
    conn.close()

    text = f"💵 **درخواست مساعده (کد: #{req_id})**\n\n👤 پرسنل: {staff_name}\n💵 مبلغ: {amount} ریال\n📝 دلیل: {reason}\n💳 کارت: `{card}`\n📅 ثبت: {created_at}\nوضعیت: ⏳ در انتظار تأیید سرپرست"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="👤 تأیید سرپرست ➔ ارسال به مدیریت", callback_data=f"step1_{req_id}")]])

    try:
        await bot.send_message(chat_id=GROUP_ID, message_thread_id=TOPIC_ADVANCE, text=text, reply_markup=kb)
        await message.answer(f"✅ درخواست مساعده شما (کد: #{req_id}) ثبت شد.")
    except Exception:
        await message.answer("❌ خطا در ارسال به گروه.")
    await state.clear()

# ---------------------------------------------------------
# گزارش ماموریت
# ---------------------------------------------------------
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
    staff_name, _, _ = get_staff_info_by_id(user_id)
    
    city = user_data.get("mission_city")
    days = message.text.strip()
    now_j = jdatetime.datetime.now()
    created_at = now_j.strftime("%Y/%d/%m %H:%M")
    month_tag = now_j.strftime("%Y/%m")

    conn = sqlite3.connect("requests.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO requests (user_id, user_name, telegram_info, request_type, col1, col2, col3, location, status, created_at, month_tag) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_id, staff_name, message.from_user.full_name, "ماموریت", f"شهر: {city}", f"مدت: {days} روز", "-", "ندارد", "⏳ در انتظار تأیید سرپرست", created_at, month_tag))
    req_id = cursor.lastrowid
    conn.commit()
    conn.close()

    text = f"📍 **گزارش ماموریت (کد: #{req_id})**\n\n👤 پرسنل: {staff_name}\n🏙️ مقصد: {city}\n⏳ مدت: {days} روز\n📅 ثبت: {created_at}\nوضعیت: ⏳ در انتظار تأیید سرپرست"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="👤 تأیید سرپرست ➔ ارسال به مدیریت", callback_data=f"step1_{req_id}")]])

    try:
        await bot.send_message(chat_id=GROUP_ID, message_thread_id=TOPIC_MISSION, text=text, reply_markup=kb)
        await message.answer(f"✅ گزارش ماموریت شما (کد: #{req_id}) ثبت شد.")
    except Exception:
        await message.answer("❌ خطا در ارسال به گروه.")
    await state.clear()

# ---------------------------------------------------------
# مراحل تأیید / رد درخواست‌ها (بدون صدور PDF)
# ---------------------------------------------------------
@dp.callback_query(F.data.startswith("step1_") | F.data.startswith("approve_") | F.data.startswith("reject_") | F.data.startswith("cancel_") | F.data.startswith("paid_"))
async def handle_request_decision(callback: CallbackQuery):
    data = callback.data
    user_id = callback.from_user.id
    conn = sqlite3.connect("requests.db")
    cursor = conn.cursor()

    if data.startswith("paid_"):
        req_id = data.split("_")[1]
        cursor.execute("SELECT user_id, request_type, col1 FROM requests WHERE id = ?", (req_id,))
        row = cursor.fetchone()
        
        if row:
            target_user_id, req_type, col1 = row
            cursor.execute("UPDATE requests SET status = '💳 تسویه و پرداخت شده' WHERE id = ?", (req_id,))
            conn.commit()
            conn.close()

            try:
                await callback.message.edit_text(callback.message.text + "\n\n✅ **وجه پرداخت و تسویه گردید.**", reply_markup=None)
            except Exception:
                pass

            try:
                await bot.send_message(chat_id=target_user_id, text=f"🎉 **خبر خوش!** درخواست {req_type} (کد: #{req_id}) پرداخت و تسویه گردید.")
            except Exception:
                pass

            await callback.answer("وضعیت پرداخت ثبت شد.")
            return

    if data.startswith("cancel_"):
        req_id = data.split("_")[1]
        cursor.execute("SELECT user_id, status FROM requests WHERE id = ?", (req_id,))
        row = cursor.fetchone()
        
        if row and row[0] == user_id:
            if "در انتظار تأیید سرپرست" in row[1]:
                cursor.execute("UPDATE requests SET status = '❌ لغو شده توسط پرسنل' WHERE id = ?", (req_id,))
                conn.commit()
                conn.close()
                await callback.message.edit_text(callback.message.text + "\n\n**[این درخواست توسط شما لغو شد]**", reply_markup=None)
                await callback.answer("درخواست شما با موفقیت لغو شد.")
                return
        conn.close()
        return

    if data.startswith("step1_"):
        req_id = data.split("_")[1]
        cursor.execute("UPDATE requests SET status = '⏳ در انتظار تأیید نهایی مدیریت' WHERE id = ?", (req_id,))
        conn.commit()
        conn.close()

        updated_text = callback.message.text or callback.message.caption or ""
        updated_text = updated_text.replace("⏳ در انتظار تأیید سرپرست", "⏳ در انتظار تأیید نهایی مدیریت")

        final_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ تأیید نهایی", callback_data=f"approve_{req_id}"),
             InlineKeyboardButton(text="❌ رد", callback_data=f"reject_{req_id}")]
        ])

        try:
            if callback.message.photo:
                await callback.message.edit_caption(caption=updated_text, reply_markup=final_kb)
            else:
                await callback.message.edit_text(text=updated_text, reply_markup=final_kb)
        except Exception:
            pass
        await callback.answer("مرحله اول تایید شد.")
        return

    action, req_id = data.split("_")
    new_status = "✅ تأیید شده قطعی" if action == "approve" else "❌ رد شده"
    
    cursor.execute("SELECT user_id, user_name, request_type, col1, col2, col3, location, created_at FROM requests WHERE id = ?", (req_id,))
    row = cursor.fetchone()
    
    if row:
        target_user_id, user_name, req_type, col1, col2, col3, location, created_at = row
        cursor.execute("UPDATE requests SET status = ? WHERE id = ?", (new_status, req_id))
        
        if req_type == "مرخصی" and action == "approve":
            try:
                days = float(location)
                cursor.execute("UPDATE staff_mapping SET leave_balance = leave_balance - ? WHERE user_id = ?", (days, target_user_id))
            except Exception:
                pass
        conn.commit()
        conn.close()

        try:
            if callback.message.photo:
                await callback.message.edit_caption(caption=callback.message.caption + f"\n\n{new_status}", reply_markup=None)
            else:
                await callback.message.edit_text(text=callback.message.text + f"\n\n{new_status}", reply_markup=None)
        except Exception:
            pass

        try:
            await bot.send_message(chat_id=target_user_id, text=f"📄 وضعیت درخواست #{req_id} ({req_type}): **{new_status}**")
        except Exception:
            pass

        if action == "approve" and req_type in ["مساعده", "تنخواه"]:
            fin_id = get_finance_manager_id()
            fin_text = (
                f"💳 **دستور پرداخت جدید (واحد مالی)**\n\n"
                f"🔹 **کد درخواست:** #{req_id}\n"
                f"👤 **نام پرسنل:** {user_name}\n"
                f"📌 **نوع:** {req_type}\n"
                f"💵 {col1}\n"
                f"📝 {col2}\n"
                f"💳 {col3}\n"
                f"📅 **تاریخ ثبت:** {created_at}\n\n"
                f"لطفاً پس از واریز وجه، روی دکمه زیر کلیک کنید:"
            )
            pay_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="پرداخت شد 💳", callback_data=f"paid_{req_id}")]
            ])
            try:
                await bot.send_message(chat_id=fin_id, text=fin_text, reply_markup=pay_kb)
            except Exception as e:
                print(f"❌ خطا در ارسال پیام به مسئول مالی: {e}")

    await callback.answer(f"درخواست {new_status} شد.")

# ---------------------------------------------------------
# وظایف پس‌زمینه (Background Schedulers)
# ---------------------------------------------------------
async def pending_requests_checker():
    while True:
        try:
            await asyncio.sleep(21600)  # هر ۶ ساعت
            conn = sqlite3.connect("requests.db")
            cursor = conn.cursor()
            cursor.execute("SELECT id, user_name, request_type, created_at FROM requests WHERE status LIKE '%در انتظار%'")
            rows = cursor.fetchall()
            conn.close()

            now_j = jdatetime.datetime.now()
            for r in rows:
                req_id, u_name, r_type, c_at = r
                try:
                    c_date = jdatetime.datetime.strptime(c_at, "%Y/%d/%m %H:%M")
                    if (now_j - c_date).total_seconds() / 3600 >= 24:
                        t_id = TOPIC_LEAVE if r_type == "مرخصی" else (TOPIC_ADVANCE if r_type == "مساعده" else (TOPIC_PETTY if r_type == "تنخواه" else (TOPIC_ASSETS if r_type == "تحویل اموال" else TOPIC_MISSION)))
                        await bot.send_message(chat_id=GROUP_ID, message_thread_id=t_id, 
                                               text=f"⚠️ هشدار: درخواست #{req_id} ({u_name}) بیش از ۲۴ ساعت معطل است.")
                except Exception:
                    pass
        except Exception:
            pass

async def main():
    print("Bot is running with persistent phone binding, exact name matching eliminated for active users, YYYY/DD/MM date format, and no PDF/Excel reports...")
    asyncio.create_task(pending_requests_checker())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())