"""Mission form and approval Router, independent of runtime."""
import html
import logging
from aiogram import Router,F,BaseMiddleware
from aiogram.types import Message,CallbackQuery,InlineKeyboardButton,InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State,StatesGroup
from ..core.dates import normalize_jalali_date,validate_custom_date
from ..services import missions as service
from .mission_filters import MissionApprovalFilter
from .organization_callbacks import callback_number


class Form(StatesGroup):
    waiting_for_mission_city=State()
    waiting_for_mission_end_date=State()
    waiting_for_mission_preview=State()
    waiting_for_mission_start_date=State()


class Access(BaseMiddleware):
    def __init__(self,connection_factory): self.connection_factory=connection_factory

    async def __call__(self,handler,event,data):
        try:
            with self.connection_factory() as conn:
                service.active_staff(conn,event.from_user.id)
            return await handler(event,data)
        except service.MissionError as exc:
            if isinstance(event,CallbackQuery): await event.answer(str(exc),show_alert=True)
            else: await event.answer(str(exc))


def create_router(get_connection,bot,*,submit_request):
    router=Router(name="missions")
    access=Access(get_connection)
    router.message.middleware(access)
    router.callback_query.middleware(access)

    def cancel_kb(back_callback):
        return InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="❌ انصراف و لغو فرم",callback_data=back_callback)
        ]])

    @router.callback_query(F.data == "req_mission")
    async def process_mission_start(callback: CallbackQuery, state: FSMContext):
        await state.set_state(Form.waiting_for_mission_city)
        kb = cancel_kb("menu_admin_finance")
        await callback.message.edit_text("🟩⬜⬜ <b>مرحله ۱ از ۳:</b> شهر مقصد ماموریت را وارد کنید:", reply_markup=kb, parse_mode="HTML")
        await callback.answer()


    @router.message(Form.waiting_for_mission_city)
    async def receive_mission_city(message: Message, state: FSMContext):
        if not message.text:
            await message.answer("❌ نام شهر معتبر وارد کنید.")
            return
        await state.update_data(mission_city=message.text.strip())
        await state.set_state(Form.waiting_for_mission_start_date)
        await message.answer("🟩🟩⬜ <b>مرحله ۲ از ۳:</b> تاریخ شروع ماموریت را با فرمت <code>سال/ماه/روز</code> وارد کنید:", parse_mode="HTML")


    @router.message(Form.waiting_for_mission_start_date)
    async def receive_mission_start(message: Message, state: FSMContext):
        text_date = normalize_jalali_date(message.text) if message.text else ""
        if not validate_custom_date(text_date):
            await message.answer("❌ فرمت تاریخ نامعتبر است (<code>YYYY/MM/DD</code>):", parse_mode="HTML")
            return
        await state.update_data(mission_start=text_date)
        await state.set_state(Form.waiting_for_mission_end_date)
        await message.answer("🟩🟩🟩 <b>مرحله ۳ از ۳:</b> تاریخ پایان ماموریت را با فرمت <code>سال/ماه/روز</code> وارد کنید:", parse_mode="HTML")


    @router.message(Form.waiting_for_mission_end_date)
    async def receive_mission_end(message: Message, state: FSMContext):
        text_date = normalize_jalali_date(message.text) if message.text else ""
        if not validate_custom_date(text_date):
            await message.answer("❌ فرمت تاریخ نامعتبر است (<code>YYYY/MM/DD</code>):", parse_mode="HTML")
            return
        data = await state.get_data()
        start_date = data.get("mission_start")

        start_date, text_date, mission_days = service.date_range(start_date, text_date)

        await state.update_data(mission_end=text_date, mission_days=str(mission_days))
    
        preview_text = f"📋 <b>پیش‌نمایش گزارش ماموریت</b>\n\n📍 شهر مقصد: {html.escape(data.get('mission_city'))}\n📅 از: {html.escape(start_date)} تا {html.escape(text_date)} ({mission_days} روز)\n\nتایید نهایی می‌شود?"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚀 تأیید و ارسال نهایی", callback_data="mission_submit_final"),
             InlineKeyboardButton(text="❌ لغو و انصراف", callback_data="back_to_main")]
        ])
        await state.set_state(Form.waiting_for_mission_preview)
        await message.answer(preview_text, reply_markup=kb, parse_mode="HTML")


    @router.callback_query(Form.waiting_for_mission_preview, F.data == "mission_submit_final")
    async def submit_mission_final(callback: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        user_id = callback.from_user.id
        with get_connection() as conn:
            _, staff_name, _ = service.active_staff(conn,user_id)
    
        service.date_range(data.get("mission_start"),data.get("mission_end"))
        col1 = f"شهر: {data.get('mission_city')}"
        col2 = f"مدت: {data.get('mission_days')} روز (از {data.get('mission_start')} تا {data.get('mission_end')})"
        col3 = "-"
        await submit_request(callback, user_id, staff_name, "ماموریت", col1, col2, col3, "-", start_date=data.get('mission_start'), end_date=data.get('mission_end'))
        await state.clear()
        await callback.answer()

    @router.callback_query(F.data.startswith('approve_'),MissionApprovalFilter(get_connection))
    async def approve_mission(callback: CallbackQuery):
        number=callback_number(callback.data.removeprefix('approve_'))
        try:
            with get_connection() as conn:
                result=service.approve(conn,callback.from_user.id,number)
        except service.MissionError:
            raise
        except Exception as exc:
            logging.error('Mission approval failed: %s',type(exc).__name__)
            await callback.answer('خطا در ثبت تأیید؛ تغییری ثبت نشد.',show_alert=True)
            return
        if result.outcome!='approved':
            messages={'not_found':'درخواست پیدا نشد.','already_processed':'این درخواست قبلاً تعیین تکلیف شده است.',
                      'replacement_pending':'جانشین هنوز درخواست را تأیید نکرده است.'}
            await callback.answer(messages[result.outcome],show_alert=True)
            return
        status='✅ تأیید شده قطعی'
        try:
            await callback.message.edit_text((callback.message.text or '')+f'\n\n{status} (توسط مدیر اصلی)',reply_markup=None)
        except Exception as exc:
            logging.error('Could not edit mission approval: %s',type(exc).__name__)
        try:
            await bot.send_message(chat_id=result.row[0],text=f'📄 وضعیت درخواست ({result.row[1]}): <b>{status}</b>',parse_mode='HTML')
        except Exception as exc:
            logging.error('Could not notify mission requester: %s',type(exc).__name__)
        await callback.answer('تایید نهایی با موفقیت ثبت شد.')

    return router
