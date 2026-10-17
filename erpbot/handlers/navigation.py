"""Login and navigation Router with explicitly supplied storage, bot and group."""
import html
import logging
import sqlite3
from aiogram import Router,F,BaseMiddleware
from aiogram.filters import Command,CommandObject,ChatMemberUpdatedFilter,IS_MEMBER
from aiogram.types import (Message,CallbackQuery,ChatMemberUpdated,InlineKeyboardMarkup,
                          InlineKeyboardButton,ReplyKeyboardMarkup,KeyboardButton,ReplyKeyboardRemove)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State,StatesGroup
from ..services import navigation as service
from .reminders import ReminderStartFilter


class Form(StatesGroup):
    waiting_for_phone=State()


def main_menu(account):
    buttons=[('📝 امور اداری و مالی (مرخصی، مساعده، ماموریت)','menu_admin_finance'),
             ('🏢 حسابداری، اموال و خرید انبار','menu_assets_purchase'),
             ('📊 کارنامه و پیگیری درخواست‌ها','menu_reports_tracking')]
    if service.is_admin(account):
        buttons.extend([('⚙️ پنل مدیریت و گزارشات اکسل','admin_panel'),
                        ('📅 مرخصی‌های فعال امروز (/today)','admin_today')])
    keyboard=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text,callback_data=data)] for text,data in buttons])
    text=('سامانه جامع مدیریت پرسنلی\n'
          f'👤 پرسنل: <b>{html.escape(account.name or "")}</b> | 🌿 مانده مرخصی: <code>{html.escape(str(account.balance))} روز</code>'
          '\n\nبخش مورد نظر را انتخاب کنید:')
    return text,keyboard


async def show_main_menu(message,account):
    text,keyboard=main_menu(account)
    await message.answer(text,reply_markup=keyboard,parse_mode='HTML')


class NavigationErrors(BaseMiddleware):
    async def __call__(self,handler,event,data):
        try:
            return await handler(event,data)
        except service.LoginError as exc:
            text=str(exc)
        except sqlite3.Error as exc:
            logging.error('Account navigation failed: %s',type(exc).__name__)
            text='خطا در بررسی یا اتصال حساب؛ دوباره تلاش کنید.'
        if isinstance(event,CallbackQuery):
            await event.answer(text,show_alert=True)
        else:
            await event.answer(text)


def create_router(get_connection,bot,group_id):
    router=Router(name='navigation')
    errors=NavigationErrors()
    router.message.middleware(errors)
    router.callback_query.middleware(errors)

    @router.my_chat_member(ChatMemberUpdatedFilter(member_status_changed=IS_MEMBER))
    async def on_bot_added_to_chat(event: ChatMemberUpdated):
        if event.chat.type=='private':
            return
        with get_connection() as conn:
            allowed=service.group_allowed(conn,event.from_user.id,event.chat.id,group_id)
        if allowed:
            return
        try:
            await bot.send_message(chat_id=event.from_user.id,
                text='❌ شما اجازه ندارید ربات را به گروه‌های متفرقه اضافه کنید. این ربات صرفاً توسط مدیر اصلی قابل مدیریت است.')
        except Exception as exc:
            logging.error('Could not notify group inviter: %s',type(exc).__name__)
        try:
            await bot.leave_chat(chat_id=event.chat.id)
        except Exception as exc:
            logging.error('Could not leave unauthorized group: %s',type(exc).__name__)

    @router.message(Command('start'),ReminderStartFilter(include_reminder=False))
    async def cmd_start(message: Message,command: CommandObject,state: FSMContext):
        await state.clear()
        with get_connection() as conn:
            account=service.account(conn,message.from_user.id)
        if account is not None and account.active!=1:
            await message.answer('❌ دسترسی شما به سامانه مسدود است.')
            return
        if account is not None:
            await show_main_menu(message,account)
            return
        if message.chat.type!='private':
            await message.answer('برای اتصال حساب، /start را در چت خصوصی ربات بفرستید.')
            return
        await state.set_state(Form.waiting_for_phone)
        keyboard=ReplyKeyboardMarkup(keyboard=[[
            KeyboardButton(text='📱 تایید و اتصال خودکار حساب کاربری',request_contact=True)]],
            resize_keyboard=True,one_time_keyboard=True)
        await message.answer('سلام! لطفاً برای اتصال امن حساب کاربری روی دکمه زیر کلیک کنید:',reply_markup=keyboard)

    @router.message(Form.waiting_for_phone,F.contact)
    async def process_phone_contact(message: Message,state: FSMContext):
        if message.chat.type!='private':
            await message.answer('اتصال حساب را در چت خصوصی ربات انجام دهید.')
            return
        if message.contact.user_id!=message.from_user.id:
            await state.clear()
            await message.answer('❌ خطای امنیتی: شماره تماسی که ارسال کردید متعلق به حساب تلگرام شما نیست!',
                                 reply_markup=ReplyKeyboardRemove())
            return
        with get_connection() as conn:
            account=service.link_contact(conn,message.from_user.id,message.contact.user_id,message.contact.phone_number)
        await state.clear()
        await message.answer(f'✅ احراز هویت با موفقیت انجام شد. خوش آمدید، <b>{html.escape(account.name or "")}</b>.',
                             reply_markup=ReplyKeyboardRemove(),parse_mode='HTML')
        await show_main_menu(message,account)

    @router.callback_query(F.data=='back_to_main')
    async def back_to_main_menu(callback: CallbackQuery,state: FSMContext):
        with get_connection() as conn:
            account=service.active_account(conn,callback.from_user.id)
        await state.clear()
        text,keyboard=main_menu(account)
        try:
            await callback.message.edit_text(text,reply_markup=keyboard,parse_mode='HTML')
        except Exception:
            await callback.message.answer(text,reply_markup=keyboard,parse_mode='HTML')
        await callback.answer()

    @router.callback_query(F.data=='menu_admin_finance')
    async def sub_menu_admin_finance(callback: CallbackQuery):
        with get_connection() as conn:
            service.active_account(conn,callback.from_user.id)
        keyboard=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=text,callback_data=data)] for text,data in [
                ('⏳ درخواست مرخصی','req_leave'),('💵 درخواست مساعده','req_advance'),
                ('📍 ثبت گزارش ماموریت','req_mission'),('🔙 بازگشت به منوی اصلی','back_to_main')]])
        await callback.message.edit_text('📝 <b>امور اداری و مالی</b>',reply_markup=keyboard,parse_mode='HTML')
        await callback.answer()

    @router.callback_query(F.data=='menu_assets_purchase')
    async def sub_menu_assets_purchase(callback: CallbackQuery):
        with get_connection() as conn:
            service.active_account(conn,callback.from_user.id)
        keyboard=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=text,callback_data=data)] for text,data in [
                ('🧾 ثبت فاکتور تنخواه','req_petty'),('🚗 تحویل اموال','req_asset'),
                ('🔄 عودت اموال','req_return_asset'),('🛒 خرید ملزومات / انبار','req_purchase'),
                ('🔙 بازگشت به منوی اصلی','back_to_main')]])
        await callback.message.edit_text('🏢 <b>حسابداری، اموال و خرید انبار</b>',reply_markup=keyboard,parse_mode='HTML')
        await callback.answer()

    return router
