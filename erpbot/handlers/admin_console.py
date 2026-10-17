"""Administrative panel and manual backup with explicit dependencies."""
import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.fsm.context import FSMContext
from ..services import admin_console as service


def create_router(get_connection, database_path):
    router = Router(name='admin_console')

    @router.callback_query(F.data == 'admin_panel')
    @router.message(Command('admin'), F.chat.type == 'private')
    async def show_admin_panel(event: CallbackQuery | Message, state: FSMContext):
        try:
            with get_connection() as conn:
                service.require_admin(conn, event.from_user.id, main_only=False)
        except service.PersonnelError as exc:
            if isinstance(event, CallbackQuery):
                await event.answer(str(exc), show_alert=True)
            return
        await state.clear()
        buttons = [
            ('⏳ درخواست‌های در انتظار (بررسی یکجا)', 'admin_pending_reqs'),
            ('👥 مدیریت پرسنل، ویرایش و تاریخ‌ها', 'adm_cat_staff'),
            ('🚗 واگذاری و ویرایش اموال پرسنل', 'admin_assign_asset'),
            ('🛡️ ثبت بیمه شخص ثالث و بدنه', 'admin_add_insurance'),
            ('📅 مدیریت روزهای تعطیل شرکت', 'admin_holidays_menu'),
            ('📊 گزارشات اکسل تخصصی', 'adm_cat_excel'),
            ('🗑️ ریست انتخابی دیتابیس', 'admin_selective_reset_menu'),
            ('📦 دانلود بکاپ دیتابیس', 'admin_get_backup'),
            ('🔙 بازگشت به منوی اصلی', 'back_to_main'),
        ]
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=text, callback_data=data)] for text, data in buttons])
        text = '⚙️ <b>پنل مدیریت پیشرفته ERP</b>\n\nبخش مورد نظر را انتخاب کنید:'
        if isinstance(event, CallbackQuery):
            await event.message.edit_text(text, reply_markup=keyboard, parse_mode='HTML')
            await event.answer()
        else:
            await event.answer(text, reply_markup=keyboard, parse_mode='HTML')

    @router.callback_query(F.data == 'admin_get_backup')
    async def admin_backup_cb(callback: CallbackQuery):
        try:
            with service.authorized_backup(get_connection, database_path, callback.from_user.id) as path:
                await callback.message.answer_document(
                    FSInputFile(path, filename='erpbot_backup.sqlite3'), caption='📦 پشتیبان دیتابیس')
        except service.PersonnelError as exc:
            await callback.answer(str(exc), show_alert=True)
            return
        except Exception as exc:
            logging.error('Manual database backup failed: %s', type(exc).__name__)
            await callback.answer('❌ تهیه یا ارسال پشتیبان انجام نشد؛ دوباره تلاش کنید.', show_alert=True)
            return
        await callback.answer()

    return router
