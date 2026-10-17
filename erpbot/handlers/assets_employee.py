"""Employee asset receipt and return forms, independent of runtime."""
import html
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from ..core.dates import normalize_persian_numbers
from ..services import assets as service
from .assets_states import Form, AdminForm
from .assets_common import AssetAccess, asset_number, charger_value
from .asset_filters import AssetApprovalFilter


def create_router(get_connection, bot, clock, encrypt_data, *, submit_request):
    router = Router(name="assets_employee")
    access = AssetAccess(get_connection, admin=False)
    router.message.middleware(access)
    router.callback_query.middleware(access)

    def cancel_kb(back_callback):
        return InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="❌ انصراف و لغو فرم", callback_data=back_callback)
        ]])

    def staff_info(actor_id):
        with get_connection() as conn:
            return service.active_staff(conn,actor_id)

    @router.callback_query(F.data == "req_return_asset")
    async def process_return_asset_start(callback: CallbackQuery, state: FSMContext):
        user_id = callback.from_user.id
        staff_id, _, _ = staff_info(user_id)

        with get_connection() as conn:
            assets = service.owned_assets(conn, user_id)

        if not assets:
            await callback.answer("شما هیچ تجهیز فعالی برای عودت ندارید.", show_alert=True)
            return

        buttons = [[InlineKeyboardButton(text=f"📦 {a[1]} ({html.escape(a[2][:30])})", callback_data=f"retasset_{a[0]}")] for a in assets]
        buttons.append([InlineKeyboardButton(text="❌ انصراف", callback_data="back_to_main")])
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        await callback.message.edit_text("🔄 <b>درخواست عودت اموال و تجهیزات</b>\n\nکدام تجهیز را می‌خواهید عودت دهید؟", reply_markup=kb, parse_mode="HTML")
        await callback.answer()


    @router.callback_query(F.data.startswith("retasset_"))
    async def process_return_asset_selected(callback: CallbackQuery, state: FSMContext):
        asset_id = asset_number(callback.data.removeprefix("retasset_"))
        user_id = callback.from_user.id
        staff_id, _, _ = staff_info(user_id)

        with get_connection() as conn:
            service.owned_asset(conn, user_id, asset_id)

        await state.update_data(return_asset_id=asset_id)
        await state.set_state(Form.return_asset_desc)
        kb = cancel_kb("menu_assets_purchase")
        await callback.message.edit_text("📝 لطفاً دلیل یا توضیحات عودت این تجهیز را بنویسید:", reply_markup=kb)
        await callback.answer()


    @router.message(Form.return_asset_desc)
    async def receive_return_asset_desc(message: Message, state: FSMContext):
        if not message.text:
            await message.answer("❌ توضیحات معتبر وارد کنید.")
            return
        desc = message.text.strip()
        await state.update_data(return_desc=desc)

        preview_text = f"📋 <b>پیش‌نمایش درخواست عودت اموال</b>\n\n📝 توضیحات: {html.escape(desc)}\n\nثبت نهایی شود؟"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚀 تأیید و ارسال نهایی", callback_data="return_submit_final"),
             InlineKeyboardButton(text="❌ لغو و انصراف", callback_data="back_to_main")]
        ])
        await state.set_state(Form.return_asset_preview)
        await message.answer(preview_text, reply_markup=kb, parse_mode="HTML")


    @router.callback_query(Form.return_asset_preview, F.data == "return_submit_final")
    async def submit_return_final(callback: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        user_id = callback.from_user.id
        _, staff_name, _ = staff_info(user_id)
        date_now = clock().strftime("%Y/%m/%d %H:%M")

        asset_id = data.get("return_asset_id")
        with get_connection() as conn:
            arow = service.owned_asset(conn, user_id, asset_id)

        asset_info = f"{arow[1]} - {arow[2]}"

        col1 = f"تاریخ عودت: {date_now} | تجهیز: {asset_info}"
        col2 = f"توضیحات: {data.get('return_desc')}"
        col3 = f"شناسه مال: {asset_id} | وضعیت: در انتظار تحویل فیزیکی و تأیید"
        await submit_request(callback, user_id, staff_name, "عودت اموال", col1, col2, col3, str(asset_id))
        await state.clear()
        await callback.answer()

    @router.callback_query(F.data == "req_asset")
    async def process_asset_start(callback: CallbackQuery, state: FSMContext):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚗 خودروی سازمانی", callback_data="asset_sel_car")],
            [InlineKeyboardButton(text="⛽ کارت سوخت", callback_data="asset_sel_fuel")],
            [InlineKeyboardButton(text="💳 کارت‌خوان (POS)", callback_data="asset_sel_pos")],
            [InlineKeyboardButton(text="🖨️ پرینتر جیبی", callback_data="asset_sel_printer")],
            [InlineKeyboardButton(text="❌ انصراف", callback_data="menu_assets_purchase")]
        ])
        date_now = clock().strftime("%Y/%m/%d")
        await callback.message.edit_text(f"🚗 <b>ثبت تحویل اقلام امانی و تجهیزات</b>\n📅 تاریخ امروز: <code>{date_now}</code>\n\nقلم مورد نظر را انتخاب کنید:", reply_markup=kb, parse_mode="HTML")
        await callback.answer()


    @router.callback_query(F.data == "asset_sel_car")
    async def asset_car_step1(callback: CallbackQuery, state: FSMContext):
        await state.set_state(Form.asset_car_code)
        kb = cancel_kb("menu_assets_purchase")
        await callback.message.edit_text("🚗 <b>مرحله ۱ از ۵:</b> کد خودرو را وارد کنید:", reply_markup=kb, parse_mode="HTML")
        await callback.answer()


    @router.message(Form.asset_car_code)
    async def asset_car_step2(message: Message, state: FSMContext):
        if not message.text:
            await message.answer("❌ کد معتبر وارد کنید.")
            return
        await state.update_data(car_code=message.text.strip())
        await state.set_state(Form.asset_car_plate)
        await message.answer("🚗 <b>مرحله ۲ از ۵:</b> پلاک خودرو را وارد کنید:", parse_mode="HTML")


    @router.message(Form.asset_car_plate)
    async def asset_car_step3(message: Message, state: FSMContext):
        if not message.text:
            await message.answer("❌ پلاک معتبر وارد کنید.")
            return
        await state.update_data(car_plate=message.text.strip())
        await state.set_state(Form.asset_car_type)
        await message.answer("🚗 <b>مرحله ۳ از ۵:</b> نوع خودرو را وارد کنید:", parse_mode="HTML")


    @router.message(Form.asset_car_type)
    async def asset_car_step4(message: Message, state: FSMContext):
        if not message.text:
            await message.answer("❌ نوع خودرو معتبر وارد کنید.")
            return
        await state.update_data(car_type=message.text.strip())
        await state.set_state(Form.asset_car_km)
        await message.answer("🚗 <b>مرحله ۴ از ۵:</b> کیلومتر تحویلی را وارد کنید:", parse_mode="HTML")


    @router.message(Form.asset_car_km)
    async def asset_car_step5(message: Message, state: FSMContext):
        clean_km = normalize_persian_numbers(message.text).strip() if message.text else ""
        if not clean_km.isdigit():
            await message.answer("❌ کیلومتر باید عدد باشد:")
            return
        await state.update_data(car_km=clean_km)
        await state.set_state(Form.asset_car_desc)
        await message.answer("🚗 <b>مرحله ۵ از ۵:</b> توضیحات تکمیلی (اگر ندارد <code>-</code> بگذارید):", parse_mode="HTML")


    @router.message(Form.asset_car_desc)
    async def asset_car_preview(message: Message, state: FSMContext):
        if not message.text:
            await message.answer("❌ توضیحات معتبر وارد کنید.")
            return
        desc = message.text.strip()
        await state.update_data(car_desc=desc)
        data = await state.get_data()

        preview_text = (
            f"📋 <b>پیش‌نمایش کامل تحویل خودروی سازمانی</b>\n\n"
            f"🔹 کد: {html.escape(data.get('car_code'))} | پلاک: {html.escape(data.get('car_plate'))}\n"
            f"🔹 نوع خودرو: {html.escape(data.get('car_type'))} | کیلومتر: {html.escape(data.get('car_km'))}\n"
            f"📝 توضیحات: {html.escape(desc)}\n\nتایید نهایی می‌شود?"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚀 تأیید و ارسال نهایی", callback_data="asset_car_submit_final"),
             InlineKeyboardButton(text="❌ لغو و انصراف", callback_data="back_to_main")]
        ])
        await state.set_state(Form.asset_car_preview)
        await message.answer(preview_text, reply_markup=kb, parse_mode="HTML")


    @router.callback_query(Form.asset_car_preview, F.data == "asset_car_submit_final")
    async def submit_asset_car_final(callback: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        date_now = clock().strftime("%Y/%m/%d")
        col1 = f"تاریخ تحویل: {date_now} | کد: {data.get('car_code')} | پلاک: {data.get('car_plate')}"
        col2 = f"نوع: {data.get('car_type')} | کیلومتر: {data.get('car_km')}"
        col3 = f"توضیحات: {data.get('car_desc')}"
        user_id = callback.from_user.id
        _, staff_name, _ = staff_info(user_id)
        await submit_request(callback, user_id, staff_name, "تحویل اموال", col1, col2, col3, "خودروی سازمانی")
        await state.clear()
        await callback.answer()


    @router.callback_query(F.data == "asset_sel_fuel")
    async def asset_fuel_step1(callback: CallbackQuery, state: FSMContext):
        await state.set_state(Form.asset_fuel_code)
        kb = cancel_kb("menu_assets_purchase")
        await callback.message.edit_text("⛽ <b>مرحله ۱ از ۵:</b> کد کارت سوخت را وارد کنید:", reply_markup=kb, parse_mode="HTML")
        await callback.answer()


    @router.message(Form.asset_fuel_code)
    async def asset_fuel_step2(message: Message, state: FSMContext):
        if not message.text:
            await message.answer("❌ کد معتبر وارد کنید.")
            return
        await state.update_data(fuel_code=message.text.strip())
        await state.set_state(Form.asset_fuel_pass)
        await message.answer("⛽ <b>مرحله ۲ از ۵:</b> رمز کارت سوخت را وارد کنید:", parse_mode="HTML")


    @router.message(Form.asset_fuel_pass)
    async def asset_fuel_step3(message: Message, state: FSMContext):
        if not message.text:
            await message.answer("❌ رمز معتبر وارد کنید.")
            return
        await state.update_data(fuel_pass=message.text.strip())
        await state.set_state(Form.asset_fuel_l1500)
        await message.answer("⛽ <b>مرحله ۳ از ۵:</b> میزان لیتر سهمیه <b>۱۵۰۰ تومانی</b> ماهیانه:", parse_mode="HTML")


    @router.message(Form.asset_fuel_l1500)
    async def asset_fuel_step4(message: Message, state: FSMContext):
        if not message.text:
            await message.answer("❌ مقدار معتبر وارد کنید.")
            return
        await state.update_data(fuel_l1500=message.text.strip())
        await state.set_state(Form.asset_fuel_l3000)
        await message.answer("⛽ <b>مرحله ۴ از ۵:</b> میزان لیتر سهمیه <b>۳۰۰۰ تومانی</b> ماهیانه:", parse_mode="HTML")


    @router.message(Form.asset_fuel_l3000)
    async def asset_fuel_step5(message: Message, state: FSMContext):
        if not message.text:
            await message.answer("❌ مقدار معتبر وارد کنید.")
            return
        await state.update_data(fuel_l3000=message.text.strip())
        await state.set_state(Form.asset_fuel_l10000)
        await message.answer("⛽ <b>مرحله ۵ از ۵:</b> میزان لیتر سهمیه <b>۱۰,۰۰۰ تومانی</b> ماهیانه:", parse_mode="HTML")


    @router.message(Form.asset_fuel_l10000)
    async def asset_fuel_preview(message: Message, state: FSMContext):
        if not message.text:
            await message.answer("❌ مقدار معتبر وارد کنید.")
            return
        l10000 = message.text.strip()
        await state.update_data(fuel_l10000=l10000)
        data = await state.get_data()

        preview_text = (
            f"📋 <b>پیش‌نمایش کامل تحویل کارت سوخت</b>\n\n"
            f"⛽ کد کارت: {html.escape(data.get('fuel_code'))} | رمز: <code>محفوظ (ارسال امن به مالی)</code>\n"
            f"🔹 سهمیه ۱۵۰۰: {html.escape(data.get('fuel_l1500'))} | ۳۰۰۰: {html.escape(data.get('fuel_l3000'))}\n"
            f"🔹 سهمیه ۱۰,۰۰۰: {html.escape(l10000)} لیتر\n\nتایید نهایی می‌شود?"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚀 تأیید و ارسال نهایی", callback_data="asset_fuel_submit_final"),
             InlineKeyboardButton(text="❌ لغو و انصراف", callback_data="back_to_main")]
        ])
        await state.set_state(Form.asset_fuel_preview)
        await message.answer(preview_text, reply_markup=kb, parse_mode="HTML")


    @router.callback_query(Form.asset_fuel_preview, F.data == "asset_fuel_submit_final")
    async def submit_asset_fuel_final(callback: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        date_now = clock().strftime("%Y/%m/%d")
        col1 = f"تاریخ تحویل: {date_now} | کد کارت سوخت: {data.get('fuel_code')} | رمز: [محفوظ و مختص واحد مالی]"
        col2 = f"سهمیه ۱۵۰۰ تومانی: {data.get('fuel_l1500')} | ۳۰۰۰ تومانی: {data.get('fuel_l3000')}"
        col3 = f"سهمیه ۱۰,۰۰۰ تومانی: {data.get('fuel_l10000')} لیتر"
        sensitive_data = encrypt_data(f"رمز کارت سوخت: {data.get('fuel_pass')}")
        user_id = callback.from_user.id
        _, staff_name, _ = staff_info(user_id)
        await submit_request(callback, user_id, staff_name, "تحویل اموال", col1, col2, col3, "کارت سوخت", sensitive_data=sensitive_data)
        await state.clear()
        await callback.answer()


    @router.callback_query(F.data == "asset_sel_pos")
    async def asset_pos_step1(callback: CallbackQuery, state: FSMContext):
        await state.set_state(Form.asset_pos_code)
        kb = cancel_kb("menu_assets_purchase")
        await callback.message.edit_text("💳 <b>مرحله ۱ از ۳:</b> کد دستگاه پوز را وارد کنید:", reply_markup=kb, parse_mode="HTML")
        await callback.answer()


    @router.message(Form.asset_pos_code)
    async def asset_pos_step2(message: Message, state: FSMContext):
        if not message.text:
            await message.answer("❌ کد معتبر وارد کنید.")
            return
        await state.update_data(pos_code=message.text.strip())
        await state.set_state(Form.asset_pos_bank)
        await message.answer("💳 <b>مرحله ۲ از ۳:</b> نام بانک را وارد کنید:", parse_mode="HTML")


    @router.message(Form.asset_pos_bank)
    async def asset_pos_step3(message: Message, state: FSMContext):
        if not message.text:
            await message.answer("❌ نام بانک معتبر وارد کنید.")
            return
        await state.update_data(pos_bank=message.text.strip())
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ دارد", callback_data="poschg_yes"),
             InlineKeyboardButton(text="❌ ندارد", callback_data="poschg_no")]
        ])
        await state.set_state(Form.asset_pos_charger)
        await message.answer("💳 <b>مرحله ۳ از ۳:</b> آیا دستگاه پوز <b>شارژر</b> دارد؟", reply_markup=kb, parse_mode="HTML")


    @router.callback_query(Form.asset_pos_charger, F.data.startswith("poschg_"))
    async def asset_pos_preview(callback: CallbackQuery, state: FSMContext):
        charger = charger_value(callback.data)
        await state.update_data(pos_charger=charger)
        data = await state.get_data()

        preview_text = (
            f"📋 <b>پیش‌نمایش کامل تحویل کارت‌خوان (POS)</b>\n\n"
            f"💳 کد پوز: {html.escape(data.get('pos_code'))} | بانک: {html.escape(data.get('pos_bank'))}\n"
            f"🔌 شارژر: {charger}\n\nتایید نهایی می‌شود?"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚀 تأیید و ارسال نهایی", callback_data="asset_pos_submit_final"),
             InlineKeyboardButton(text="❌ لغو و انصراف", callback_data="back_to_main")]
        ])
        await state.set_state(Form.asset_pos_preview)
        try:
            await callback.message.edit_text(preview_text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            await callback.message.answer(preview_text, reply_markup=kb, parse_mode="HTML")
        await callback.answer()


    @router.callback_query(Form.asset_pos_preview, F.data == "asset_pos_submit_final")
    async def submit_asset_pos_final(callback: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        date_now = clock().strftime("%Y/%m/%d")
        col1 = f"تاریخ تحویل: {date_now} | کد پوز: {data.get('pos_code')}"
        col2 = f"بانک: {data.get('pos_bank')}"
        col3 = f"شارژر: {data.get('pos_charger')}"
        user_id = callback.from_user.id
        _, staff_name, _ = staff_info(user_id)
        await submit_request(callback, user_id, staff_name, "تحویل اموال", col1, col2, col3, "کارت‌خوان")
        await state.clear()
        await callback.answer()


    @router.callback_query(F.data == "asset_sel_printer")
    async def asset_printer_step1(callback: CallbackQuery, state: FSMContext):
        await state.set_state(Form.asset_printer_code)
        kb = cancel_kb("menu_assets_purchase")
        await callback.message.edit_text("🖨️ <b>مرحله ۱ از ۲:</b> کد پرینتر جیبی را وارد کنید:", reply_markup=kb, parse_mode="HTML")
        await callback.answer()


    @router.message(Form.asset_printer_code)
    async def asset_printer_step2(message: Message, state: FSMContext):
        if not message.text:
            await message.answer("❌ کد معتبر وارد کنید.")
            return
        await state.update_data(printer_code=message.text.strip())
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ دارد", callback_data="prchg_yes"),
             InlineKeyboardButton(text="❌ ندارد", callback_data="prchg_no")]
        ])
        await state.set_state(Form.asset_printer_charger)
        await message.answer("🖨️ <b>مرحله ۲ از ۲:</b> آیا پرینتر <b>شارژر</b> دارد؟", reply_markup=kb, parse_mode="HTML")


    @router.callback_query(Form.asset_printer_charger, F.data.startswith("prchg_"))
    async def asset_printer_preview(callback: CallbackQuery, state: FSMContext):
        charger = charger_value(callback.data)
        await state.update_data(printer_charger=charger)
        data = await state.get_data()

        preview_text = (
            f"📋 <b>پیش‌نمایش کامل تحویل پرینتر جیبی</b>\n\n"
            f"🖨️ کد پرینتر: {html.escape(data.get('printer_code'))}\n"
            f"🔌 شارژر: {charger}\n\nتایید نهایی می‌شود?"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚀 تأیید و ارسال نهایی", callback_data="asset_printer_submit_final"),
             InlineKeyboardButton(text="❌ لغو و انصراف", callback_data="back_to_main")]
        ])
        await state.set_state(Form.asset_printer_preview)
        try:
            await callback.message.edit_text(preview_text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            await callback.message.answer(preview_text, reply_markup=kb, parse_mode="HTML")
        await callback.answer()


    @router.callback_query(Form.asset_printer_preview, F.data == "asset_printer_submit_final")
    async def submit_asset_printer_final(callback: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        date_now = clock().strftime("%Y/%m/%d")
        col1 = f"تاریخ تحویل: {date_now} | کد پرینتر: {data.get('printer_code')}"
        col2 = f"شارژر: {data.get('printer_charger')}"
        col3 = "-"
        user_id = callback.from_user.id
        _, staff_name, _ = staff_info(user_id)
        await submit_request(callback, user_id, staff_name, "تحویل اموال", col1, col2, col3, "پرینتر جیبی")
        await state.clear()
        await callback.answer()

    @router.callback_query(F.data.startswith("confirmasset_"))
    async def user_confirm_asset_receipt(callback: CallbackQuery):
        aid = asset_number(callback.data.removeprefix("confirmasset_"))
        user_id = callback.from_user.id
        staff_id, _, _ = staff_info(user_id)

        confirm_date = clock().strftime("%Y/%m/%d %H:%M")
        with get_connection() as conn:
            service.confirm_receipt(conn, user_id, aid, confirm_date)

        await callback.message.edit_text(callback.message.text + f"\n\n<b>✅ تحویل این تجهیز توسط شما در تاریخ {confirm_date} تأیید شد.</b>", reply_markup=None, parse_mode="HTML")
        await callback.answer("تأیید دریافت با موفقیت ثبت شد.")

    @router.callback_query(F.data.startswith("approve_"), AssetApprovalFilter(get_connection))
    async def approve_asset_request(callback: CallbackQuery):
        request_id=asset_number(callback.data.removeprefix("approve_"))
        with get_connection() as conn:
            result=service.approve(conn,callback.from_user.id,request_id,clock().strftime("%Y/%m/%d %H:%M"))
        if result.outcome!='approved':
            messages={'not_found':'درخواست پیدا نشد.','already_processed':'این درخواست قبلاً تعیین تکلیف شده است.',
                      'replacement_pending':'جانشین هنوز درخواست را تأیید نکرده است.'}
            await callback.answer(messages[result.outcome],show_alert=True)
            return
        status='✅ تأیید شده قطعی'
        try:
            if callback.message.photo:
                await callback.message.edit_caption(caption=(callback.message.caption or '')+f'\n\n{status} (توسط مدیر اصلی)',reply_markup=None)
            else:
                await callback.message.edit_text((callback.message.text or '')+f'\n\n{status} (توسط مدیر اصلی)',reply_markup=None)
        except Exception:
            logging.exception('Could not edit approved asset request')
        try:
            await bot.send_message(chat_id=result.row[0],text=f'📄 وضعیت درخواست ({result.row[3]}): <b>{status}</b>',parse_mode='HTML')
        except Exception:
            logging.exception('Could not notify asset requester')
        await callback.answer('تایید نهایی با موفقیت ثبت شد.')

    return router
