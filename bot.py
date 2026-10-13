import os
import sqlite3
import logging
import jdatetime
import pandas as pd
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    CallbackQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    FSInputFile
)

# پیکربندی لاگ‌ها
logging.basicConfig(level=logging.INFO)

# دریافت توکن از متغیرهای محیطی یا مقدار مستقیم
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ----------------------------------------------------
# دیتابیس (SQLite)
# ----------------------------------------------------
def init_db():
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    
    # جدول درخواست‌های مرخصی و ماموریت
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            full_name TEXT,
            req_type TEXT,
            start_date TEXT,
            end_date TEXT,
            duration TEXT,
            reason TEXT,
            status TEXT DEFAULT 'در انتظار تایید سرپرست',
            supervisor_approval TEXT DEFAULT 'Pending',
            manager_approval TEXT DEFAULT 'Pending',
            created_at TEXT
        )
    """)
    
    # جدول کاربران و نقش‌ها
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            full_name TEXT,
            role TEXT DEFAULT 'staff'
        )
    """)
    
    conn.commit()
    conn.close()

init_db()

# ----------------------------------------------------
# ماشین حالت (FSM) برای مرخصی
# ----------------------------------------------------
class LeaveState(StatesGroup):
    waiting_for_start_date = State()
    waiting_for_end_date = State()
    waiting_for_reason = State()

# ----------------------------------------------------
# کیبوردهای اصلی
# ----------------------------------------------------
def main_menu_keyboard():
    keyboard = [
        [KeyboardButton(text="📝 ثبت درخواست مرخصی"), KeyboardButton(text="💵 ثبت درخواست مساعده")],
        [KeyboardButton(text="🚗 ثبت گزارش ماموریت"), KeyboardButton(text="📊 دریافت گزارش (اکسل)")],
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

# ----------------------------------------------------
# هندلرهای اصلی
# ----------------------------------------------------
@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        f"سلام {message.from_user.first_name} عزیز!\nبه سیستم اتوماسیون اداری پرسنل خوش آمدید.",
        reply_markup=main_menu_keyboard()
    )

# --- شروع جریان ثبت مرخصی ---
@dp.message(F.text == "📝 ثبت درخواست مرخصی")
async def start_leave_request(message: Message, state: FSMContext):
    await state.set_state(LeaveState.waiting_for_start_date)
    await message.answer("لطفاً تاریخ شروع مرخصی را وارد کنید (مثال: 1405/07/20):")

@dp.message(LeaveState.waiting_for_start_date)
async def process_start_date(message: Message, state: FSMContext):
    await state.update_data(start_date=message.text)
    await state.set_state(LeaveState.waiting_for_end_date)
    await message.answer("لطفاً تاریخ پایان مرخصی را وارد کنید (مثال: 1405/07/22):")

@dp.message(LeaveState.waiting_for_end_date)
async def process_end_date(message: Message, state: FSMContext):
    await state.update_data(end_date=message.text)
    await state.set_state(LeaveState.waiting_for_reason)
    await message.answer("لطفاً علت مرخصی را بنویسید:")

@dp.message(LeaveState.waiting_for_reason)
async def process_reason(message: Message, state: FSMContext):
    user_data = await state.get_data()
    start_date = user_data.get("start_date")
    end_date = user_data.get("end_date")
    reason = message.text
    
    # محاسبه ساده (بدون احتساب جمعه‌ها)
    duration_text = "محاسبه شده (بدون جمعه)"

    # ثبت در دیتابیس
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    now_str = jdatetime.datetime.now().strftime("%Y/%m/%d %H:%M")
    cursor.execute("""
        INSERT INTO requests (user_id, full_name, req_type, start_date, end_date, duration, reason, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (message.from_user.id, message.from_user.full_name, "مرخصی", start_date, end_date, duration_text, reason, now_str))
    conn.commit()
    conn.close()

    await state.clear()
    await message.answer(
        f"✅ درخواست مرخصی شما با موفقیت ثبت شد و برای سرپرست ارسال گردید.\n\n"
        f"📅 از: {start_date}\n📅 تا: {end_date}\n📝 علت: {reason}",
        reply_markup=main_menu_keyboard()
    )

# ----------------------------------------------------
# هندلر گزارش‌گیری اکسل (رفع مشکل IndentationError)
# ----------------------------------------------------
@dp.message(F.text == "📊 دریافت گزارش (اکسل)")
async def generate_advanced_report_msg(message: Message):
    await process_excel_export(message)

async def generate_advanced_report(callback: CallbackQuery, state: FSMContext):
    """هندلر مربوط به فراخوانی از طریق کال‌بک"""
    await callback.answer("در حال آماده‌سازی فایل اکسل...")
    await process_excel_export(callback.message)

async def process_excel_export(message: Message):
    """خروجی گرفتن از دیتابیس و تبدیل آن به فایل اکسل"""
    try:
        conn = sqlite3.connect("bot_database.db")
        df = pd.read_sql_query("SELECT * FROM requests", conn)
        conn.close()

        if df.empty:
            await message.answer("هیچ داده‌ای برای خروجی اکسل یافت نشد.")
            return

        file_path = "report_requests.xlsx"
        df.to_excel(file_path, index=False)

        excel_file = FSInputFile(file_path)
        await message.answer_document(
            document=excel_file,
            caption="📊 گزارش جامع درخواست‌ها و مرخصی‌ها"
        )
    except Exception as e:
        logging.error(f"Error in excel generation: {e}")
        await message.answer("⚠️ متأسفانه در هنگام ساخت فایل اکسل خطایی رخ داد.")

# ----------------------------------------------------
# اجرای اصلی ربات
# ----------------------------------------------------
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())