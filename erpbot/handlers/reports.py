"""Personal and administrative reports with explicit storage, clock and renderer."""
import asyncio
import html
import logging
from aiogram import Router,F,BaseMiddleware
from aiogram.filters import Command
from aiogram.types import Message,CallbackQuery,InlineKeyboardMarkup,InlineKeyboardButton,BufferedInputFile
from ..services import reports as service
from ..reporting.xlsx import build_workbook


def esc(value):
    return html.escape('' if value is None else str(value))


class ReportAccess(BaseMiddleware):
    def __init__(self,connection_factory):
        self.connection_factory=connection_factory

    async def __call__(self,handler,event,data):
        try:
            with self.connection_factory() as conn:
                service.active_staff(conn,event.from_user.id)
            return await handler(event,data)
        except service.ReportError as exc:
            if isinstance(event,CallbackQuery):
                await event.answer(str(exc),show_alert=True)
            else:
                await event.answer(str(exc))


def create_router(get_connection,clock,*,renderer=build_workbook):
    router=Router(name='reports')
    access=ReportAccess(get_connection)
    router.message.middleware(access)
    router.callback_query.middleware(access)

    async def send_export(callback,report,caption):
        try:
            contents=await asyncio.to_thread(renderer,report)
        except Exception as exc:
            logging.error('Report generation failed: %s',type(exc).__name__)
            await callback.answer('ساخت گزارش ناموفق بود؛ دوباره تلاش کنید.',show_alert=True)
            return
        with get_connection() as conn:
            service.authorize_export(conn,callback.from_user.id,report)
        await callback.message.answer_document(BufferedInputFile(contents,filename=report.filename),caption=caption)
        await callback.answer()

    @router.callback_query(F.data == "menu_reports_tracking")
    async def sub_menu_reports_tracking(callback: CallbackQuery):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📊 وضعیت من (آمار ماه جاری)", callback_data="my_stats")],
            [InlineKeyboardButton(text="📥 دریافت گزارش اکسل عملکرد من", callback_data="my_excel_report")],
            [InlineKeyboardButton(text="📋 پیگیری و لغو درخواست‌ها", callback_data="my_requests")],
            [InlineKeyboardButton(text="🔙 بازگشت به منوی اصلی", callback_data="back_to_main")]
        ])
        await callback.message.edit_text("📊 <b>کارنامه و پیگیری درخواست‌ها</b>", reply_markup=kb, parse_mode="HTML")
        await callback.answer()


    @router.callback_query(F.data == "my_stats")
    async def show_user_stats(callback: CallbackQuery):
        current_month = clock().strftime("%Y/%m")
        with get_connection() as conn:
            result = service.stats(conn, callback.from_user.id, current_month)
        staff_name, balance = result.name, result.balance
        used_leave, total_adv, mission_count = result.used_leave, result.advances, result.missions

        stats_msg = (
            f"📊 <b>کارنامه و وضعیت ماه جاری ({current_month})</b>\n\n"
            f"👤 <b>نام پرسنل:</b> {esc(staff_name)}\n"
            f"🌿 <b>مرخصی استحقاقی استفاده‌شده ماه:</b> {used_leave} روز\n"
            f"🍃 <b>مانده مرخصی کل (دفتر کل):</b> {balance} روز\n"
            f"💵 <b>مجموع مساعده پرداختی/تاییدشده:</b> {total_adv:,} ریال\n"
            f"📍 <b>تعداد مأموریت‌ها:</b> {mission_count} مورد\n"
        )
        await callback.message.answer(stats_msg, parse_mode="HTML")
        await callback.answer()


    @router.callback_query(F.data == "my_excel_report")
    async def send_my_excel_report(callback: CallbackQuery):
        with get_connection() as conn:
            report = service.personal_export(conn,callback.from_user.id)
            staff_name = service.active_staff(conn,callback.from_user.id)[1]
        await send_export(callback,report,f"📊 گزارش عملکرد و اموال تحویلی شما ({staff_name})")


    @router.callback_query(F.data == "my_requests")
    async def show_user_requests(callback: CallbackQuery):
        user_id = callback.from_user.id
        with get_connection() as conn:
            rows = service.personal_requests(conn,user_id)

        if not rows:
            await callback.answer("شما تاکنون درخواستی ثبت نکرده‌اید.", show_alert=True)
            return

        for r in rows:
            r_code, r_type, c1, c2, c3, status, created_at = r
            text = f"🔹 <b>کد: {esc(r_code)}</b> | نوع: {esc(r_type)}\n📌 اطلاعات: {esc(c1)} | {esc(c2)}\n📌 جزئیات: {esc(c3)}\n📌 وضعیت: <b>{esc(status)}</b>\n📅 تاریخ: {esc(created_at)}"
            keyboard = None
            if "در انتظار" in status:
                keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ لغو این درخواست", callback_data=f"cancel_{r_code}")]])
            await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
        await callback.answer()


    @router.callback_query(F.data == "adm_cat_excel")
    async def admin_category_excel(callback: CallbackQuery):
        with get_connection() as conn:
            service.require_admin(conn,callback.from_user.id)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📊 اکسل درخواست‌ها (Requests)", callback_data="xcl_req")],
            [InlineKeyboardButton(text="👥 اکسل پرسنل و تاریخ‌ها (Staff)", callback_data="xcl_staff")],
            [InlineKeyboardButton(text="🚗 اکسل اموال و تجهیزات (Assets)", callback_data="xcl_assets")],
            [InlineKeyboardButton(text="🛡️ اکسل بیمه ناوگان (Insurances)", callback_data="xcl_ins")],
            [InlineKeyboardButton(text="🔙 بازگشت به پنل", callback_data="admin_panel")]
        ])
        await callback.message.edit_text("📊 <b>انتخاب گزارش اکسل تخصصی:</b>", reply_markup=kb, parse_mode="HTML")
        await callback.answer()


    @router.callback_query(F.data.startswith("xcl_"))
    async def send_specific_excel(callback: CallbackQuery):
        with get_connection() as conn:
            report = service.admin_export(conn,callback.from_user.id,callback.data.removeprefix("xcl_"))
        await send_export(callback,report,f"📊 گزارش تخصصی اکسل: {report.filename}")


    @router.message(Command("today"), F.chat.type == "private")
    @router.callback_query(F.data == "admin_today")
    async def cmd_today_leaves(event: Message | CallbackQuery):
        today_jalali = clock().strftime("%Y/%m/%d")
        with get_connection() as conn:
            matched_rows = service.absences(conn,event.from_user.id,today_jalali)

        msg_text = f"📅 <b>لیست غایبین / حاضرین در مأموریت امروز ({today_jalali}):</b>\n\n"
        if not matched_rows:
            msg_text += "امروز هیچ موردی ثبت نشده است."
        else:
            for r in matched_rows:
                msg_text += f"▫️ <b>{esc(r[0])}</b> ➔ {esc(r[1])} ({esc(r[2])} | {esc(r[3])})\n"

        if isinstance(event, CallbackQuery):
            await event.message.answer(msg_text, parse_mode="HTML")
            await event.answer()
        else:
            if event.chat.type == "private":
                await event.answer(msg_text, parse_mode="HTML")


    @router.callback_query(F.data == "admin_pending_reqs")
    async def admin_show_pending_requests(callback: CallbackQuery):

        with get_connection() as conn:
            rows = service.pending(conn,callback.from_user.id)

        if not rows:
            await callback.answer("هیچ درخواست بلاتکلیف و در انتظاری وجود ندارد.", show_alert=True)
            return

        await callback.message.answer("⏳ <b>لیست درخواست‌های در انتظار تأیید مدیریت:</b>", parse_mode="HTML")
        for r in rows:
            req_id, req_code, uname, rtype, c1, c2, created_at = r
            text = f"📩 <b>کد: {esc(req_code)}</b> | نوع: {esc(rtype)}\n👤 پرسنل: {esc(uname)}\n📌 {esc(c1)}\n📌 {esc(c2)}\n📅 ثبت: {esc(created_at)}"
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ تأیید نهایی", callback_data=f"approve_{req_id}"),
                 InlineKeyboardButton(text="❌ رد درخواست", callback_data=f"reject_{req_id}")]
            ])
            await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
        await callback.answer()


    @router.callback_query(F.data == "admin_list_staff")
    async def admin_list_staff(callback: CallbackQuery):
        with get_connection() as conn:
            rows = service.staff_list(conn,callback.from_user.id)

        text = "📋 <b>لیست پرسنل سامانه:</b>\n\n"
        for r in rows:
            status = "🟢 فعال" if r[2] == 1 else "🔴 غیرفعال"
            emp = r[5] if r[5] else "نامشخص"
            deact = f" | خروج: {esc(r[6])}" if r[6] else ""
            chunk = f"{status} <b>{esc(r[0])}</b> | <code>{esc(r[4])}</code>\n📱 پ: <code>{esc(r[1])}</code> | استخدام: {esc(emp)}{deact} | مانده: {r[3]} روز\n\n"
            if len(text) + len(chunk) > 4000:
                await callback.message.answer(text, parse_mode="HTML")
                text = ""
            text += chunk
        if text:
            await callback.message.answer(text, parse_mode="HTML")
        await callback.answer()

    return router
