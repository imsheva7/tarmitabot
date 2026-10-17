"""One canonical holiday Router; duplicate legacy handlers are retired."""
import html
from aiogram import Router,F
from aiogram.types import Message,CallbackQuery,InlineKeyboardMarkup,InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State,StatesGroup
from ..core.dates import normalize_jalali_date,validate_custom_date
from .personnel import Access,cancel_kb
from ..services import holidays


class AdminForm(StatesGroup):
    holiday_date=State()
    holiday_desc=State()


def create_router(get_connection):
    router=Router(name="holidays")
    access=Access(get_connection)
    router.message.middleware(access)
    router.callback_query.middleware(access)

    @router.callback_query(F.data == "admin_holidays_menu")
    async def admin_holidays_menu(callback: CallbackQuery):
        with get_connection() as conn:
            rows = holidays.recent(conn,callback.from_user.id)

        text = "📅 <b>مدیریت روزهای تعطیل شرکت</b>\n(در محاسبات مرخصی کسر نمی‌شوند)\n\n"
        buttons = [[InlineKeyboardButton(text="➕ افزودن روز تعطیل جدید", callback_data="add_holiday_start")]]
        for r in rows:
            h_date, desc = r
            buttons.append([InlineKeyboardButton(text=f"❌ حذف تعطیلی {h_date} ({desc})", callback_data=f"delhol_{h_date}")])
        buttons.append([InlineKeyboardButton(text="🔙 بازگشت به پنل", callback_data="admin_panel")])
    
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        await callback.answer()

    @router.callback_query(F.data == "add_holiday_start")
    async def add_holiday_start(callback: CallbackQuery, state: FSMContext):
        await state.set_state(AdminForm.holiday_date)
        kb = cancel_kb("admin_holidays_menu")
        await callback.message.edit_text("📅 تاریخ روز تعطیل را با فرمت <code>YYYY/MM/DD</code> وارد کنید:", reply_markup=kb, parse_mode="HTML")
        await callback.answer()

    @router.message(AdminForm.holiday_date)
    async def receive_holiday_date(message: Message, state: FSMContext):
        text_date = normalize_jalali_date(message.text) if message.text else ""
        if not validate_custom_date(text_date):
            await message.answer("❌ فرمت تاریخ نامعتبر است (<code>YYYY/MM/DD</code>):", parse_mode="HTML")
            return
        await state.update_data(h_date=text_date)
        await state.set_state(AdminForm.holiday_desc)
        await message.answer("📝 شرح یا دلیل تعطیلی را بنویسید:")


    @router.message(AdminForm.holiday_desc)
    async def receive_holiday_desc(message: Message, state: FSMContext):
        if not message.text:
            await message.answer("❌ شرح معتبر وارد کنید.")
            return
        desc = message.text.strip()
        data = await state.get_data()
        h_date = data.get("h_date")

        with get_connection() as conn:
            holidays.save(conn,message.from_user.id,h_date,desc)

        await message.answer(f"✅ روز تعطیل <code>{h_date}</code> ({html.escape(desc)}) با موفقیت ثبت شد.", parse_mode="HTML")
        await state.clear()


    @router.callback_query(F.data.startswith("delhol_"))
    async def delete_holiday(callback: CallbackQuery):
        h_date = callback.data.split("delhol_")[1]
        with get_connection() as conn:
            holidays.delete(conn,callback.from_user.id,h_date)
        await admin_holidays_menu(callback)
    return router
