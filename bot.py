import sqlite3
import pandas as pd
import jdatetime
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.client.session.aiohttp import AiohttpSession

TOKEN = "8865295559:AAEOEDFV-Ikd3rZl6gzyR8V23RIlE7fGcVw"
GROUP_ID = -1003619551361
RAW_GROUP_ID = "3619551361" 

TOPIC_LEAVE = 2     # تاپیک مرخصی
TOPIC_ADVANCE = 3   # تاپیک مساعده
TOPIC_MISSION = 38  # تاپیک ماموریت

# مدیران سیستم
ADMIN_IDS = [114906446, 827616077]

# سقف‌ها و محدودیت‌های سازمانی
MAX_ADVANCE_AMOUNT = 100_000_000  # حداکثر سقف مساعده (۱۰۰ میلیون ریال)

# 📌 لیست رسمی اسامی پرسنل مجاز همراه با مقدار مرخصی ذخیره اولیه (بر حسب روز)
AUTHORIZED_STAFF = {
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

session = AiohttpSession(proxy="socks5://127.0.0.1:10808")
bot = Bot(token=TOKEN, session=session)
dp = Dispatcher()

def init_db():
    conn = sqlite3.connect("requests.db")
    cursor = conn.cursor()
    # ساختار جدول با ستون‌های تفکیک‌شده برای خروجی اکسل دقیق‌تر
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
            staff_name TEXT,
            leave_balance REAL
        )
    """)
    conn.commit()
    conn.close()

init_db()

class Form(StatesGroup):
    waiting_for_name = State()          
    waiting_for_leave_type = State()    
    waiting_for_leave_start_date = State() 
    waiting_for_leave_end_date = State()   
    waiting_for_hourly_date = State()
    waiting_for_hourly_times = State()
    waiting_for_advance_amount = State()
    waiting_for_advance_reason = State()
    waiting_for_mission_city = State()  
    waiting_for_mission_days = State()  

def get_staff_info(user_id: int):
    conn = sqlite3.connect("requests.db")
    cursor = conn.cursor()
    cursor.execute("SELECT staff_name, leave_balance FROM staff_mapping WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row if row else (None, 0.0)

@dp.message(F.text == "/start")
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    staff_name, balance = get_staff_info(user_id)

    keyboard_buttons = [
        [InlineKeyboardButton(text="⏳ درخواست مرخصی", callback_data="req_leave")],
        [InlineKeyboardButton(text="💵 درخواست مساعده (ریال)", callback_data="req_advance")],
        [InlineKeyboardButton(text="📍 ثبت گزارش ماموریت", callback_data="req_mission")],
        [InlineKeyboardButton(text="📋 پیگیری و لغو درخواست‌ها", callback_data="my_requests")]
    ]
    
    if user_id in ADMIN_IDS:
        keyboard_buttons.append([InlineKeyboardButton(text="📊 گزارش پیشرفته مرخصی‌ها", callback_data="report_leave")])
        keyboard_buttons.append([InlineKeyboardButton(text="💵 گزارش پیشرفته مساعده‌ها", callback_data="report_advance")])
        keyboard_buttons.append([InlineKeyboardButton(text="📍 گزارش پیشرفته ماموریت‌ها", callback_data="report_mission")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    status_text = f"👤 پرسنل متصل: **{staff_name}** | 🌿 مرخصی ذخیره: `{balance} روز`" if staff_name else "⚠️ نام شما هنوز در سیستم ثبت نشده است."
    
    await message.answer(
        f"سلام! به سامانه جامع مدیریت درخواست‌های پرسنلی خوش آمدید.\n{status_text}\n\nلطفاً گزینه مورد نظر را انتخاب کنید:", 
        reply_markup=keyboard
    )

@dp.callback_query(F.data.in_({"req_leave", "req_advance", "req_mission"}))
async def process_request_start(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    staff_name, _ = get_staff_info(user_id)
    
    if callback.data == "req_leave":
        req_type = "مرخصی"
    elif callback.data == "req_advance":
        req_type = "مساعده"
    else:
        req_type = "ماموریت"

    await state.update_data(current_request_type=req_type)

    if not staff_name:
        await state.set_state(Form.waiting_for_name)
        await callback.message.answer(
            f"شما قصد ثبت درخواست **{req_type}** را دارید.\n\n"
            "لطفاً **نام و نام خانوادگی** خود را (دقیقاً مطابق با لیست پرسنل) وارد کنید:"
        )
        await callback.answer()
        return

    await state.update_data(verified_staff_name=staff_name)
    
    if req_type == "مرخصی":
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="استحقاقی", callback_data="ltype_استحقاقی")],
                [InlineKeyboardButton(text="استعلاجی", callback_data="ltype_استعلاجی")],
                [InlineKeyboardButton(text="ساعتی", callback_data="ltype_ساعتی")],
                [InlineKeyboardButton(text="بدون حقوق", callback_data="ltype_بدون_حقوق")]
            ]
        )
        await callback.message.answer(f"ثبت درخواست مرخصی برای: **{staff_name}**\nلطفاً نوع مرخصی خود را انتخاب کنید:", reply_markup=keyboard)
        await state.set_state(Form.waiting_for_leave_type)
    elif req_type == "مساعده":
        await state.set_state(Form.waiting_for_advance_amount)
        await callback.message.answer(
            f"ثبت درخواست مساعده برای: **{staff_name}**\n\n"
            f"⚠️ *سقف مجاز هر درخواست: {MAX_ADVANCE_AMOUNT:,} ریال*\n\n"
            "1️⃣ لطفاً **مبلغ درخواستی (به ریال)** را وارد کنید:"
        )
    else:
        await state.set_state(Form.waiting_for_mission_city)
        await callback.message.answer(
            f"ثبت گزارش ماموریت برای: **{staff_name}**\n\n"
            "1️⃣ لطفاً **شهر مقصد** را وارد کنید:"
        )
    await callback.answer()

@dp.message(Form.waiting_for_name)
async def verify_and_lock_name(message: Message, state: FSMContext):
    entered_name = message.text.strip()
    user_id = message.from_user.id

    if entered_name not in AUTHORIZED_STAFF:
        await message.answer("❌ نام وارد شده در لیست پرسنل مجاز یافت نشد! لطفاً دوباره تلاش کنید:")
        return

    initial_balance = AUTHORIZED_STAFF[entered_name]

    conn = sqlite3.connect("requests.db")
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT OR REPLACE INTO staff_mapping (user_id, staff_name, leave_balance) VALUES (?, ?, ?)", 
                       (user_id, entered_name, initial_balance))
        conn.commit()
    except Exception:
        pass
    conn.close()

    await state.update_data(verified_staff_name=entered_name)
    user_data = await state.get_data()
    req_type = user_data.get("current_request_type")

    if req_type == "مرخصی":
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="استحقاقی", callback_data="ltype_استحقاقی")],
                [InlineKeyboardButton(text="استعلاجی", callback_data="ltype_استعلاجی")],
                [InlineKeyboardButton(text="ساعتی", callback_data="ltype_ساعتی")],
                [InlineKeyboardButton(text="بدون حقوق", callback_data="ltype_بدون_حقوق")]
            ]
        )
        await message.answer(f"✅ نام شما ثبت شد: **{entered_name}** (مرخصی ذخیره: {initial_balance} روز)\n\nلطفاً نوع مرخصی را انتخاب کنید:", reply_markup=keyboard)
        await state.set_state(Form.waiting_for_leave_type)
    elif req_type == "مساعده":
        await state.set_state(Form.waiting_for_advance_amount)
        await message.answer(f"✅ نام شما ثبت شد: **{entered_name}**\n\n1️⃣ مبلغ درخواستی (به ریال) را وارد کنید:")
    else:
        await state.set_state(Form.waiting_for_mission_city)
        await message.answer(f"✅ نام شما ثبت شد: **{entered_name}**\n\n1️⃣ شهر مقصد را وارد کنید:")

@dp.callback_query(Form.waiting_for_leave_type, F.data.startswith("ltype_"))
async def process_leave_type_selected(callback: CallbackQuery, state: FSMContext):
    ltype = callback.data.split("_")[1]
    await state.update_data(leave_type=ltype)
    
    if ltype == "ساعتی":
        await state.set_state(Form.waiting_for_hourly_date)
        await callback.message.answer("⏱️ **مرخصی ساعتی**\n\n1️⃣ لطفاً **تاریخ روز مرخصی** را وارد کنید (مثلاً: 1405/08/20):")
    else:
        await state.set_state(Form.waiting_for_leave_start_date)
        await callback.message.answer(f"نوع مرخصی: **{ltype}**\n\n1️⃣ لطفاً **تاریخ خروج** (شروع مرخصی) را وارد کنید (مثلاً: 1405/08/20):")
    await callback.answer()

@dp.message(Form.waiting_for_hourly_date)
async def receive_hourly_date(message: Message, state: FSMContext):
    await state.update_data(hourly_date=message.text)
    await state.set_state(Form.waiting_for_hourly_times)
    await message.answer("2️⃣ لطفاً **ساعت خروج و ورود** را وارد کنید (مثلاً: از ساعت 09:00 تا 13:00):")

@dp.message(Form.waiting_for_hourly_times)
async def receive_hourly_times(message: Message, state: FSMContext):
    user_data = await state.get_data()
    user_id = message.from_user.id
    staff_name, balance = get_staff_info(user_id)
    user_name = user_data.get("verified_staff_name") or staff_name
    
    leave_date = user_data.get("hourly_date")
    times = message.text
    
    col1 = f"تاریخ: {leave_date}"
    col2 = f"ساعت: {times}"
    col3 = "مدت: ساعتی (0 روز)"
    details = f"تاریخ: {leave_date} | ساعت: {times}"

    await finalize_leave_request(message, user_id, user_name, balance, col1, col2, col3, details, 0.0)

@dp.message(Form.waiting_for_leave_start_date)
async def receive_leave_start(message: Message, state: FSMContext):
    await state.update_data(leave_start=message.text)
    await state.set_state(Form.waiting_for_leave_end_date)
    await message.answer("2️⃣ لطفاً **تاریخ ورود** (پایان مرخصی) را وارد کنید (مثلاً: 1405/08/22):")

@dp.message(Form.waiting_for_leave_end_date)
async def receive_leave_end(message: Message, state: FSMContext):
    user_data = await state.get_data()
    user_id = message.from_user.id
    staff_name, balance = get_staff_info(user_id)
    user_name = user_data.get("verified_staff_name") or staff_name
    
    leave_type = user_data.get("leave_type", "معمولی")
    start_str = user_data.get("leave_start")
    end_str = message.text

    calculated_days = 1.0
    friday_count = 0
    try:
        s_parts = [int(x) for x in start_str.replace('-', '/').split('/')]
        e_parts = [int(x) for x in end_str.replace('-', '/').split('/')]
        
        d1 = jdatetime.date(s_parts[0], s_parts[1], s_parts[2])
        d2 = jdatetime.date(e_parts[0], e_parts[1], e_parts[2])
        
        current_d = d1
        working_days = 0
        while current_d <= d2:
            if current_d.weekday() == 6:  # جمعه
                friday_count += 1
            else:
                working_days += 1
            current_d += jdatetime.timedelta(days=1)
            
        calculated_days = float(working_days) if working_days > 0 else 1.0
    except Exception:
        calculated_days = 1.0

    col1 = f"خروج: {start_str}"
    col2 = f"ورود: {end_str}"
    col3 = f"تعداد روز: {calculated_days} روز (با احتساب {friday_count} روز جمعه)"
    details = f"نوع: {leave_type} | خروج: {start_str} | ورود: {end_str} | کسرشونده: {calculated_days} روز (جمعه‌ها: {friday_count} روز)"

    await finalize_leave_request(message, user_id, user_name, balance, col1, col2, col3, details, calculated_days)

async def finalize_leave_request(message: Message, user_id, user_name, balance, col1, col2, col3, details, days_to_deduct):
    tg_name = message.from_user.full_name
    tg_username = f"@{message.from_user.username}" if message.from_user.username else "ندارد"
    telegram_info = f"{tg_name} ({tg_username} - ID: {user_id})"
    
    now_jalali = jdatetime.datetime.now()
    created_at = now_jalali.strftime("%Y/%m/%d %H:%M")
    month_tag = now_jalali.strftime("%Y/%m")
    
    conn = sqlite3.connect("requests.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO requests (user_id, user_name, telegram_info, request_type, col1, col2, col3, location, status, created_at, month_tag) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_id, user_name, telegram_info, "مرخصی", col1, col2, col3, str(days_to_deduct), "⏳ در انتظار تأیید سرپرست", created_at, month_tag))
    req_id = cursor.lastrowid
    conn.commit()
    conn.close()

    text = (f"📩 **درخواست مرخصی جدید (مرحله 1)** (کد: #{req_id})\n\n"
            f"👤 پرسنل: {user_name} (مرخصی ذخیره: {balance} روز)\n"
            f"📱 تلگرام: {telegram_info}\n"
            f"📝 جزئیات: {details}\n"
            f"📅 تاریخ ثبت: {created_at}\n"
            f"وضعیت: ⏳ در انتظار تأیید سرپرست")
    
    admin_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 تأیید سرپرست ➔ ارسال به مدیریت", callback_data=f"step1_{req_id}")],
        [InlineKeyboardButton(text="❌ رد درخواست", callback_data=f"reject_{req_id}")]
    ])

    try:
        await bot.send_message(chat_id=GROUP_ID, message_thread_id=TOPIC_LEAVE, text=text, reply_markup=admin_keyboard)
        await message.answer(f"✅ درخواست مرخصی شما (کد: #{req_id}) ثبت شد.")
    except Exception as e:
        print(f"❌ خطا: {e}")

    await message.state.clear() if hasattr(message, 'state') else None

# مراحل ثبت مساعده
@dp.message(Form.waiting_for_advance_amount)
async def receive_advance_amount(message: Message, state: FSMContext):
    text_val = message.text.replace(",", "").replace("ریال", "").strip()
    try:
        amount = int(''.join(filter(str.isdigit, text_val)))
    except ValueError:
        amount = 0

    if amount > MAX_ADVANCE_AMOUNT:
        await message.answer(f"⚠️ **اخطار سقف مساعده!** مبلغ درخواستی بیشتر از سقف مجاز ({MAX_ADVANCE_AMOUNT:,} ریال) است. لطفاً مبلغ کمتر وارد کنید:")
        return

    await state.update_data(advance_amount=message.text)
    await state.set_state(Form.waiting_for_advance_reason)
    await message.answer("2️⃣ لطفاً **دلیل درخواست مساعده** را بنویسید:")

@dp.message(Form.waiting_for_advance_reason)
async def receive_advance_reason(message: Message, state: FSMContext):
    user_data = await state.get_data()
    user_id = message.from_user.id
    staff_name, _ = get_staff_info(user_id)
    user_name = user_data.get("verified_staff_name") or staff_name
    
    amount_str = user_data.get("advance_amount")
    reason = message.text

    col1 = f"مبلغ: {amount_str} ریال"
    col2 = f"دلیل: {reason}"
    col3 = "-"
    details = f"مبلغ: {amount_str} ریال | دلیل: {reason}"

    tg_name = message.from_user.full_name
    tg_username = f"@{message.from_user.username}" if message.from_user.username else "ندارد"
    telegram_info = f"{tg_name} ({tg_username} - ID: {user_id})"
    
    now_jalali = jdatetime.datetime.now()
    created_at = now_jalali.strftime("%Y/%m/%d %H:%M")
    month_tag = now_jalali.strftime("%Y/%m")
    
    conn = sqlite3.connect("requests.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO requests (user_id, user_name, telegram_info, request_type, col1, col2, col3, location, status, created_at, month_tag) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_id, user_name, telegram_info, "مساعده", col1, col2, col3, "ندارد", "⏳ در انتظار تأیید سرپرست", created_at, month_tag))
    req_id = cursor.lastrowid
    conn.commit()
    conn.close()

    text = (f"💵 **درخواست مساعده جدید (مرحله 1)** (کد: #{req_id})\n\n"
            f"👤 پرسنل: {user_name}\n"
            f"📱 تلگرام: {telegram_info}\n"
            f"📝 جزئیات: {details}\n"
            f"📅 تاریخ ثبت: {created_at}\n"
            f"وضعیت: ⏳ در انتظار تأیید سرپرست")
    
    admin_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 تأیید سرپرست ➔ ارسال به مدیریت", callback_data=f"step1_{req_id}")],
        [InlineKeyboardButton(text="❌ رد درخواست", callback_data=f"reject_{req_id}")]
    ])

    try:
        await bot.send_message(chat_id=GROUP_ID, message_thread_id=TOPIC_ADVANCE, text=text, reply_markup=admin_keyboard)
        await message.answer(f"✅ درخواست مساعده شما (کد: #{req_id}) ثبت شد.")
    except Exception as e:
        print(f"❌ خطا: {e}")

    await state.clear()

# مراحل ثبت ماموریت
@dp.message(Form.waiting_for_mission_city)
async def receive_mission_city(message: Message, state: FSMContext):
    await state.update_data(mission_city=message.text)
    await state.set_state(Form.waiting_for_mission_days)
    await message.answer("2️⃣ لطفاً **تعداد روز ماموریت** را وارد کنید (مثلاً: ۳):")

@dp.message(Form.waiting_for_mission_days)
async def receive_mission_days(message: Message, state: FSMContext):
    user_data = await state.get_data()
    user_id = message.from_user.id
    staff_name, _ = get_staff_info(user_id)
    user_name = user_data.get("verified_staff_name") or staff_name
    
    city = user_data.get("mission_city", "نامشخص")
    days = message.text

    col1 = f"شهر مقصد: {city}"
    col2 = f"مدت: {days} روز"
    col3 = "-"
    details = f"شهر مقصد: {city} | مدت ماموریت: {days} روز"

    tg_name = message.from_user.full_name
    tg_username = f"@{message.from_user.username}" if message.from_user.username else "ندارد"
    telegram_info = f"{tg_name} ({tg_username} - ID: {user_id})"
    
    now_jalali = jdatetime.datetime.now()
    created_at = now_jalali.strftime("%Y/%m/%d %H:%M")
    month_tag = now_jalali.strftime("%Y/%m")
    
    admin_keyboard_temp = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 تأیید سرپرست ➔ ارسال به مدیریت", callback_data="pending")]
    ])
    
    text_preview = (f"📍 **گزارش ماموریت جدید (مرحله 1)**\n\n"
                    f"👤 پرسنل: {user_name}\n"
                    f"📱 تلگرام: {telegram_info}\n"
                    f"📝 جزئیات: {details}\n"
                    f"📅 تاریخ ثبت: {created_at}\n"
                    f"وضعیت: ⏳ در انتظار تأیید سرپرست")

    try:
        sent_msg = await bot.send_message(
            chat_id=GROUP_ID, 
            message_thread_id=TOPIC_MISSION, 
            text=text_preview, 
            reply_markup=admin_keyboard_temp
        )
        msg_id = sent_msg.message_id
        message_link = f"https://t.me/c/{RAW_GROUP_ID}/{TOPIC_MISSION}/{msg_id}"
        
        conn = sqlite3.connect("requests.db")
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO requests (user_id, user_name, telegram_info, request_type, col1, col2, col3, location, status, created_at, month_tag) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, user_name, telegram_info, "ماموریت", col1, col2, col3, message_link, "⏳ در انتظار تأیید سرپرست", created_at, month_tag))
        req_id = cursor.lastrowid
        conn.commit()
        conn.close()

        real_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👤 تأیید سرپرست ➔ ارسال به مدیریت", callback_data=f"step1_{req_id}")],
            [InlineKeyboardButton(text="❌ رد درخواست", callback_data=f"reject_{req_id}")]
        ])
        
        real_text = (f"📍 **گزارش ماموریت جدید (مرحله 1)** (کد: #{req_id})\n\n"
                     f"👤 پرسنل: {user_name}\n"
                     f"📱 تلگرام: {telegram_info}\n"
                     f"📝 جزئیات: {details}\n"
                     f"🔗 [لینک پیام در تاپیک]({message_link})\n"
                     f"📅 تاریخ ثبت: {created_at}\n"
                     f"وضعیت: ⏳ در انتظار تأیید سرپرست")

        await bot.edit_message_text(chat_id=GROUP_ID, message_id=msg_id, text=real_text, reply_markup=real_keyboard, parse_mode="Markdown")
        await message.answer(f"✅ گزارش ماموریت شما (کد: #{req_id}) ثبت شد و مستقیماً به تاپیک ماموریت ارسال گردید.", reply_markup=None)
    except Exception as e:
        print(f"❌ خطا در ارسال به تاپیک ماموریت: {e}")
        await message.answer("❌ خطا در ارسال اطلاعات به تاپیک ماموریت.")

    await state.clear()

# مدیریت دکمه‌های تایید دو مرحله‌ای، رد و لغو
@dp.callback_query(F.data.startswith("step1_") | F.data.startswith("approve_") | F.data.startswith("reject_") | F.data.startswith("cancel_"))
async def handle_request_decision(callback: CallbackQuery):
    data = callback.data
    user_id = callback.from_user.id
    conn = sqlite3.connect("requests.db")
    cursor = conn.cursor()

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
            else:
                conn.close()
                await callback.answer("⚠️ این درخواست بررسی شده و دیگر قابل لغو نیست.", show_alert=True)
                return
        conn.close()
        return

    if user_id not in ADMIN_IDS:
        await callback.answer("⚠️ شما دسترسی لازم را ندارید!", show_alert=True)
        conn.close()
        return

    admin_name = callback.from_user.full_name

    if data.startswith("step1_"):
        req_id = data.split("_")[1]
        cursor.execute("UPDATE requests SET status = '⏳ در انتظار تأیید نهایی مدیریت' WHERE id = ?", (req_id,))
        conn.commit()
        
        cursor.execute("SELECT user_id, request_type FROM requests WHERE id = ?", (req_id,))
        row = cursor.fetchone()
        conn.close()

        original_text = callback.message.text
        updated_text = original_text.replace("⏳ در انتظار تأیید سرپرست", f"✅ تأیید سرپرست ({admin_name})\nوضعیت: ⏳ در انتظار تأیید نهایی مدیریت")

        final_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ تأیید نهایی", callback_data=f"approve_{req_id}"),
                InlineKeyboardButton(text="❌ رد", callback_data=f"reject_{req_id}")
            ]
        ])

        try:
            await callback.message.edit_text(updated_text, reply_markup=final_keyboard, parse_mode="Markdown")
        except Exception:
            pass
        
        await callback.answer("مرحله اول تایید شد.")
        return

    action, req_id = data.split("_")
    new_status = "✅ تأیید شده قطعی" if action == "approve" else "❌ رد شده"
    
    cursor.execute("SELECT user_id, request_type, location FROM requests WHERE id = ?", (req_id,))
    row = cursor.fetchone()
    
    if row:
        target_user_id, req_type, location_col = row
        cursor.execute("UPDATE requests SET status = ? WHERE id = ?", (new_status, req_id))
        
        if req_type == "مرخصی" and action == "approve":
            try:
                leave_days = float(location_col)
                if leave_days > 0:
                    cursor.execute("UPDATE staff_mapping SET leave_balance = leave_balance - ? WHERE user_id = ?", (leave_days, target_user_id))
            except Exception:
                pass
            
        conn.commit()
    conn.close()

    original_text = callback.message.text
    updated_text = original_text.split("وضعیت:")[0] + f"وضعیت: {new_status} (توسط {admin_name})"

    try:
        await callback.message.edit_text(updated_text, reply_markup=None, parse_mode="Markdown")
    except Exception:
        pass

    if row:
        try:
            await bot.send_message(chat_id=target_user_id, text=f"📢 نتیجه بررسی: درخواست {req_type} شما (کد: #{req_id}) **{new_status}** شد.")
        except Exception:
            pass

    await callback.answer(f"درخواست با موفقیت {new_status} شد.")

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

@dp.callback_query(F.data.in_({"report_leave", "report_advance", "report_mission"}))
async def ask_report_month(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("⚠️ دسترسی ندارید!", show_alert=True)
        return

    rtype_map = {"report_leave": "مرخصی", "report_advance": "مساعده", "report_mission": "ماموریت"}
    await state.update_data(report_type=rtype_map[callback.data])
    
    current_jalali_month = jdatetime.datetime.now().strftime("%Y/%m")
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📁 دریافت کل گزارشات", callback_data="get_rep_all")],
        [InlineKeyboardButton(text=f"📅 گزارش ماه جاری ({current_jalali_month})", callback_data=f"get_rep_{current_jalali_month}")]
    ])
    
    await callback.message.answer("لطفاً بازه مورد نظر برای گزارش را انتخاب کنید:", reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data.startswith("get_rep_"))
async def generate_advanced_report(callback: CallbackQuery, state: FSMContext):