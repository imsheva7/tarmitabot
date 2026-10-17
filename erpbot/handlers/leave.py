"""Leave workflow router with explicit dependencies and no SQL or runtime imports."""
import html
import logging
import jdatetime
from aiogram import Router, F, BaseMiddleware
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from ..core.dates import normalize_jalali_date, normalize_persian_numbers, validate_custom_date
from ..services import leave_workflow as workflow
from ..services.requests import RequestSubmissionError
from .organization_callbacks import callback_number
from .leave_states import Form, AdminForm
from .leave_filters import LeaveDecisionFilter, LeaveRejectionFilter, LeaveCancellationFilter


class LeaveAccess(BaseMiddleware):
    def __init__(self, connection_factory):
        self.connection_factory = connection_factory

    async def __call__(self, handler, event, data):
        try:
            with self.connection_factory() as conn:
                workflow.active_staff(conn, event.from_user.id)
            return await handler(event, data)
        except (workflow.LeaveError, RequestSubmissionError) as exc:
            if isinstance(event, CallbackQuery):
                await event.answer(str(exc), show_alert=True)
            else:
                await event.answer(str(exc))


def create_router(get_connection, bot, *, submit_request):
    router = Router(name="leave")
    access = LeaveAccess(get_connection)
    router.message.middleware(access)
    router.callback_query.middleware(access)

    def staff_info(telegram_id):
        with get_connection() as conn:
            return workflow.active_staff(conn, telegram_id)

    def get_holidays_list():
        with get_connection() as conn:
            return workflow.holidays(conn)

    def cancel_kb(back_callback):
        return InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="❌ انصراف", callback_data=back_callback)
        ]])

    async def ask_for_leave_replacement(message: Message, state: FSMContext):
        current_user_id = message.from_user.id
        with get_connection() as conn:
            rows = workflow.replacement_candidates(conn, current_user_id)

        buttons = []
        for r in rows:
            sid, sname = r[0], r[1]
            buttons.append([InlineKeyboardButton(text=f"👤 {sname}", callback_data=f"repl_{sid}")])
        buttons.append([InlineKeyboardButton(text="❌ بدون جایگزین / هیچکدام", callback_data="repl_None")])
        buttons.append([InlineKeyboardButton(text="❌ انصراف", callback_data="back_to_main")])
    
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        await state.set_state(Form.waiting_for_replacement)
        await message.answer("🟩🟩🟩🟩 <b>مرحله ۴ از ۴:</b> همکار جایگزین خود را در زمان مرخصی انتخاب کنید:", reply_markup=kb, parse_mode="HTML")


    @router.callback_query(F.data == "req_leave")
    async def process_leave_start(callback: CallbackQuery, state: FSMContext):
        staff_info(callback.from_user.id)
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


    @router.callback_query(Form.waiting_for_leave_type, F.data.startswith("ltype_"))
    async def process_leave_type_selected(callback: CallbackQuery, state: FSMContext):
        ltype_key = callback.data.split("_", 1)[1]
        mapping = {
            "estheghaghi": "استحقاقی",
            "estelaji": "استعلاجی",
            "saati": "ساعتی",
            "without_pay": "بدون حقوق"
        }
        ltype = mapping.get(ltype_key)
        if ltype is None:
            raise workflow.LeaveError("نوع مرخصی نامعتبر است.")
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


    @router.message(Form.waiting_for_hourly_date)
    async def receive_hourly_date(message: Message, state: FSMContext):
        text_date = normalize_jalali_date(message.text) if message.text else ""
        if not validate_custom_date(text_date):
            await message.answer("❌ فرمت تاریخ نامعتبر است (<code>YYYY/MM/DD</code>):", parse_mode="HTML")
            return
        await state.update_data(hourly_date=text_date)
        await state.set_state(Form.waiting_for_hourly_times)
        await message.answer("🟩🟩🟩⬜ <b>مرحله ۳ از ۴:</b> ساعت خروج و ورود را وارد کنید (مثلاً 09:00 تا 13:00):", parse_mode="HTML")


    @router.message(Form.waiting_for_hourly_times)
    async def receive_hourly_times(message: Message, state: FSMContext):
        if not message.text:
            await message.answer("❌ لطفاً ساعت معتبر وارد کنید.")
            return
        await state.update_data(hourly_times=normalize_persian_numbers(message.text).strip())
        await ask_for_leave_replacement(message, state)


    @router.message(Form.waiting_for_leave_start_date)
    async def receive_leave_start(message: Message, state: FSMContext):
        text_date = normalize_jalali_date(message.text) if message.text else ""
        if not validate_custom_date(text_date):
            await message.answer("❌ فرمت تاریخ نامعتبر است (<code>YYYY/MM/DD</code>):", parse_mode="HTML")
            return
        await state.update_data(leave_start=text_date)
        await state.set_state(Form.waiting_for_leave_end_date)
        await message.answer("🟩🟩🟩⬜ <b>مرحله ۳ از ۴:</b> تاریخ پایان مرخصی را با فرمت <code>سال/ماه/روز</code> وارد کنید:", parse_mode="HTML")


    @router.message(Form.waiting_for_leave_end_date)
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
            calculated_days = workflow.working_days(start_date, text_date, holidays)

            user_id = message.from_user.id
            _, _, balance = staff_info(user_id)
        
            # محاسبه دربرگیرنده درخواست‌های در انتظار جهت جلوگیری از مانده منفی تجمعی
            with get_connection() as conn:
                pending_leaves = workflow.pending_days(conn, user_id)

            if (calculated_days + pending_leaves) > balance:
                await message.answer(
                    f"⚠️ مانده مرخصی شما ({balance} روز) با احتساب درخواست‌های در انتظار "
                    f"({pending_leaves} روز) برای این درخواست کافی نیست.\n\n"
                    "درخواست شما می‌تواند برای بررسی مدیر اصلی ارسال شود، "
                    "اما تأیید آن نیازمند تأیید استثنایی و مجدد مدیر اصلی است."
                )

        await ask_for_leave_replacement(message, state)


    @router.callback_query(Form.waiting_for_replacement, F.data.startswith("repl_"))
    async def process_leave_replacement_selected(callback: CallbackQuery, state: FSMContext):
        repl_raw = callback.data.split("repl_")[1]
        if repl_raw == "None":
            replacement_text = "بدون جایگزین"
            replacement_staff_id = None
        else:
            repl_sid = callback_number(repl_raw)
            if repl_sid is None:
                raise workflow.LeaveError("شناسه جانشین نامعتبر است.")
            with get_connection() as conn:
                replacement_text = workflow.replacement_name(conn, repl_sid, callback.from_user.id)
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


    @router.callback_query(Form.waiting_for_leave_preview, F.data == "leave_submit_final")
    async def submit_leave_final(callback: CallbackQuery, state: FSMContext):
        user_data = await state.get_data()
        user_id = callback.from_user.id
        _, staff_name, _ = staff_info(user_id)
        ltype = user_data.get("leave_type")
        if ltype not in ("استحقاقی", "استعلاجی", "ساعتی", "بدون حقوق"):
            raise workflow.LeaveError("نوع مرخصی را دوباره انتخاب کنید.")
        replacement_text = user_data.get("replacement_name")
        replacement_staff_id = user_data.get("replacement_staff_id")
        status_repl = "تعیین تکلیف نشده ⏳" if replacement_staff_id else "بدون نیاز به جانشین"

        if ltype == "ساعتی":
            leave_date = user_data.get("hourly_date")
            times = user_data.get("hourly_times")
            if not validate_custom_date(leave_date or "") or not times:
                raise workflow.LeaveError("تاریخ و ساعت مرخصی را دوباره وارد کنید.")
            col1 = f"نوع: {ltype}"
            col2 = f"تاریخ: {leave_date} | ساعت: {times}"
            col3 = f"مدت: ساعتی | جایگزین: {replacement_text} | وضعیت جانشین: {status_repl}"
            await submit_request(callback, user_id, staff_name, "مرخصی", col1, col2, col3, "0.0", amount=0, start_date=leave_date, end_date=leave_date, replacement_staff_id=replacement_staff_id)
        else:
            start_str = user_data.get("leave_start")
            end_str = user_data.get("leave_end")
            if not all(validate_custom_date(value or "") for value in (start_str, end_str)):
                raise workflow.LeaveError("تاریخ مرخصی را دوباره وارد کنید.")
            holidays = get_holidays_list()

            calculated_days = workflow.working_days(start_str, end_str, holidays)

            col1 = f"نوع: {ltype}"
            col2 = f"از: {start_str} ➔ تا: {end_str}"
            col3 = f"روز کسر: {calculated_days} | جایگزین: {replacement_text} | وضعیت جانشین: {status_repl}"
            await submit_request(callback, user_id, staff_name, "مرخصی", col1, col2, col3, str(calculated_days), amount=0, start_date=start_str, end_date=end_str, replacement_staff_id=replacement_staff_id)

        await state.clear()
        await callback.answer()

    @router.callback_query(F.data.startswith("approve_") | F.data.startswith("reject_") | F.data.startswith("leaveoverride_"), LeaveDecisionFilter(get_connection))
    async def handle_leave_decision(callback: CallbackQuery, state: FSMContext):
        user_id = callback.from_user.id
        action, _, raw = (callback.data or "").partition("_")
        req_id = callback_number(raw)
        if req_id is None:
            await callback.answer("شناسه درخواست نامعتبر است.", show_alert=True)
            return
        with get_connection() as conn:
            authorized = workflow.is_main_admin(conn, user_id)
            leave_row = workflow.approval_request(conn, req_id)
        if not authorized:
            await callback.answer("فقط مدیر اصلی مجاز است.", show_alert=True)
            return
        if leave_row is None or leave_row[2] != "مرخصی":
            await callback.answer("درخواست مرخصی پیدا نشد.", show_alert=True)
            return
        if action == "reject":
            with get_connection() as conn:
                result = workflow.rejection_request(conn, req_id, user_id)
            if result.outcome != "pending":
                await callback.answer("این درخواست قبلاً تعیین تکلیف شده است.", show_alert=True)
                return
            await state.update_data(rejecting_req_id=req_id, rejecting_admin_id=user_id)
            await state.set_state(AdminForm.rejection_reason)
            await callback.message.answer("❌ لطفاً <b>دلیل رد درخواست</b> را بنویسید:", parse_mode="HTML")
            await callback.answer()
            return
        if action == "leaveoverride" and "استحقاقی" not in (leave_row[3] or ""):
            await callback.answer("درخواست مرخصی استحقاقی معتبر نیست.", show_alert=True)
            return
        if action == "leaveoverride":
            saved = await state.get_data()
            if (
                saved.get("leave_override_request_id") != req_id
                or saved.get("leave_override_admin_id") != user_id
                or saved.get("leave_override_message_id") != callback.message.message_id
                or saved.get("leave_override_chat_id") != callback.message.chat.id
            ):
                await callback.answer("ابتدا دکمه تأیید عادی را بزنید و هشدار کسری را مشاهده کنید.", show_alert=True)
                return

        try:
            # The service commits the decision before any Telegram notification.
            with get_connection() as leave_conn:
                result = workflow.approve_leave(
                    leave_conn, req_id, user_id, exceptional=(action == "leaveoverride")
                )
        except Exception:
            logging.exception("Annual leave approval failed for request %s", req_id)
            await callback.answer("خطا در ثبت مرخصی؛ هیچ تأییدی اعلام نشد.", show_alert=True)
            return

        if result.outcome == "needs_override":
            try:
                requested_days = float(leave_row[4])
                shortage = max(0.0, requested_days - result.balance)
                warning = (
                    f"⚠️ مانده مرخصی: {result.balance:g} روز\n"
                    f"درخواست: {requested_days:g} روز\n"
                    f"کسری: {shortage:g} روز\n\n"
                    "آیا به‌صورت استثنایی تأیید می‌کنید؟"
                )
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text="⚠️ تأیید استثنایی مرخصی",
                        callback_data=f"leaveoverride_{req_id}",
                    )],
                    [InlineKeyboardButton(text="انصراف", callback_data=f"leavecancel_{req_id}")],
                ])
                warning_message = await callback.message.answer(warning, reply_markup=keyboard)
                await state.update_data(
                    leave_override_request_id=req_id,
                    leave_override_admin_id=user_id,
                    leave_override_message_id=warning_message.message_id,
                    leave_override_chat_id=warning_message.chat.id,
                )
            except Exception:
                logging.exception("Could not show exceptional approval prompt")
                await callback.answer("نمایش دکمه تأیید استثنایی ناموفق بود.", show_alert=True)
                return
            await callback.answer("مانده کافی نیست؛ تأیید دوم لازم است.", show_alert=True)
            return

        messages = {
            "replacement_pending": "جانشین هنوز درخواست را تأیید نکرده است.",
            "already_processed": "این درخواست قبلاً تعیین تکلیف شده است.",
            "staff_not_found": "پرسنل یا مانده مرخصی پیدا نشد.",
            "invalid_days": "تعداد روزهای مرخصی نامعتبر است.",
            "not_found": "درخواست پیدا نشد.",
            "not_annual_leave": "نوع درخواست نامعتبر است.",
        }
        if result.outcome not in ("approved", "exceptional_approved"):
            await callback.answer(messages.get(result.outcome, "تأیید انجام نشد."), show_alert=True)
            return

        await state.update_data(
            leave_override_request_id=None,
            leave_override_admin_id=None,
            leave_override_message_id=None,
            leave_override_chat_id=None,
        )
        status_text = "✅ تأیید شده قطعی"
        suffix = " (استثنایی توسط مدیر اصلی)" if result.outcome == "exceptional_approved" else " (توسط مدیر اصلی)"
        try:
            if callback.message.photo:
                await callback.message.edit_caption(
                    caption=(callback.message.caption or "") + "\n\n" + status_text + suffix,
                    reply_markup=None,
                )
            else:
                await callback.message.edit_text(
                    text=(callback.message.text or "") + "\n\n" + status_text + suffix,
                    reply_markup=None,
                )
        except Exception:
            logging.exception("Could not edit approved leave message")
        try:
            await bot.send_message(
                chat_id=leave_row[0],
                text=f"📄 وضعیت درخواست ({leave_row[1]}): <b>{status_text}</b>{suffix}",
                parse_mode="HTML",
            )
        except Exception:
            logging.exception("Could not notify employee of approved leave")
        await callback.answer("مرخصی با موفقیت تأیید شد.")
        return


    @router.callback_query(F.data.startswith("leavecancel_"))
    async def cancel_exceptional_leave_approval(callback: CallbackQuery, state: FSMContext):
        with get_connection() as conn:
            authorized = workflow.is_main_admin(conn, callback.from_user.id)
        if not authorized:
            await callback.answer("فقط مدیر اصلی مجاز است.", show_alert=True)
            return
        raw_id = (callback.data or "").removeprefix("leavecancel_")
        req_id = callback_number(raw_id)
        if req_id is None:
            await callback.answer("شناسه نامعتبر است.", show_alert=True)
            return
        saved = await state.get_data()
        if not (
            saved.get("leave_override_request_id") == req_id
            and saved.get("leave_override_admin_id") == callback.from_user.id
            and saved.get("leave_override_message_id") == callback.message.message_id
            and saved.get("leave_override_chat_id") == callback.message.chat.id
        ):
            await callback.answer("این هشدار دیگر فعال نیست.", show_alert=True)
            return
        await state.update_data(
            leave_override_request_id=None,
            leave_override_admin_id=None,
            leave_override_message_id=None,
            leave_override_chat_id=None,
        )
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            logging.exception("Could not remove exceptional leave buttons")
        await callback.answer("تأیید استثنایی لغو شد؛ درخواست همچنان در انتظار است.")


    @router.callback_query(F.data.startswith("replapp_") | F.data.startswith("replrej_"))
    async def process_replacement_response(callback: CallbackQuery):
        action, _, raw = (callback.data or "").partition("_")
        request_id = callback_number(raw)
        if request_id is None:
            await callback.answer("شناسه درخواست نامعتبر است.", show_alert=True)
            return
        approved = action == "replapp"
        with get_connection() as conn:
            result = workflow.respond_replacement(conn, request_id, callback.from_user.id, approved)
        if result.outcome not in ("approved", "rejected"):
            messages = {
                "not_found": "درخواست یافت نشد.",
                "already_processed": "این درخواست قبلاً تعیین تکلیف شده است.",
                "already_answered": "پاسخ جانشینی قبلاً ثبت شده است.",
                "forbidden": "فقط جانشین تعیین‌شده مجاز به پاسخ است.",
            }
            await callback.answer(messages[result.outcome], show_alert=True)
            return
        code, name, col1, col2, _, admin_message, admin_chat, _ = result.row
        try:
            await callback.message.edit_text(
                (callback.message.text or "") + f"\n\n<b>پاسخ شما ثبت شد:</b> {html.escape(result.status_tag)}",
                reply_markup=None, parse_mode="HTML",
            )
        except Exception:
            logging.exception("Could not edit replacement response")
        await callback.answer("پاسخ شما با موفقیت ثبت شد.")
        if admin_message and admin_chat:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="✅ تأیید نهایی", callback_data=f"approve_{request_id}"),
                InlineKeyboardButton(text="❌ رد (با دلیل)", callback_data=f"reject_{request_id}"),
            ]])
            status = "⏳ در انتظار تأیید نهایی مدیریت" if approved else "❌ رد شده به دلیل عدم تایید جانشین"
            text = (f"📩 <b>درخواست مرخصی ({code})</b>\n\n👤 پرسنل: {html.escape(name)}\n"
                    f"📌 {html.escape(col1)}\n📌 {html.escape(col2)}\n📌 {html.escape(result.details)}\nوضعیت: {status}")
            try:
                await bot.edit_message_text(chat_id=admin_chat, message_id=admin_message,
                                            text=text, reply_markup=keyboard if approved else None, parse_mode="HTML")
            except Exception:
                logging.exception("Could not notify manager of replacement response")

    @router.message(AdminForm.rejection_reason, LeaveRejectionFilter(get_connection))
    async def save_leave_rejection(message: Message, state: FSMContext):
        data = await state.get_data()
        if data.get("rejecting_admin_id", message.from_user.id) != message.from_user.id:
            await message.answer("دسترسی غیرمجاز است.")
            return
        if not message.text or not message.text.strip():
            await message.answer("❌ دلیل معتبر وارد کنید.")
            return
        reason = message.text.strip()
        with get_connection() as conn:
            result = workflow.reject_leave(conn, data.get("rejecting_req_id"), message.from_user.id, reason)
        if result.outcome != "rejected":
            await message.answer("❌ درخواست در انتظار یا مجوز معتبر یافت نشد.")
            await state.clear()
            return
        target, code, admin_chat, admin_message, _, _ = result.row
        await state.clear()
        await message.answer("✅ درخواست رد شد.")
        try:
            await bot.send_message(chat_id=target, text=f"❌ <b>درخواست شما ({code}) رد شد.</b>\n\n📝 <b>دلیل رد توسط مدیر اصلی:</b>\n{html.escape(reason)}", parse_mode="HTML")
        except Exception:
            logging.exception("Could not notify employee of rejected leave")
        if admin_chat and admin_message:
            try:
                await bot.edit_message_text(chat_id=admin_chat, message_id=admin_message,
                    text=f"📩 <b>درخواست ({code})</b>\n\n❌ <b>وضعیت: رد شده</b>\n📝 دلیل: {html.escape(reason)}", reply_markup=None, parse_mode="HTML")
            except Exception:
                logging.exception("Could not edit rejected leave")

    @router.callback_query(F.data.startswith("cancel_"), LeaveCancellationFilter(get_connection))
    async def cancel_leave_request(callback: CallbackQuery):
        code = (callback.data or "").partition("_")[2]
        with get_connection() as conn:
            result = workflow.cancel_leave(conn, code, callback.from_user.id)
        if result.outcome != "cancelled":
            await callback.answer("امکان لغو این درخواست وجود ندارد.", show_alert=True)
            return
        _, _, _, admin_chat, admin_message, _ = result.row
        if admin_chat and admin_message:
            try:
                await bot.edit_message_text(chat_id=admin_chat, message_id=admin_message,
                    text=f"📩 <b>درخواست ({code})</b>\n\n❌ <b>وضعیت: لغو شده توسط پرسنل</b>", reply_markup=None, parse_mode="HTML")
            except Exception:
                logging.exception("Could not edit cancelled leave")
        try:
            await callback.message.edit_text((callback.message.text or "") + "\n\n<b>[این درخواست توسط شما لغو شد]</b>", reply_markup=None, parse_mode="HTML")
        except Exception:
            logging.exception("Could not edit employee cancellation message")
        await callback.answer("درخواست لغو شد.")

    return router
