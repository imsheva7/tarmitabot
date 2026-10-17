"""Administrative asset assignment and maintenance with explicit dependencies."""
import html
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from ..core.dates import normalize_persian_numbers
from ..services import assets as service
from .assets_states import Form, AdminForm
from .assets_common import AssetAccess, asset_number, charger_value


def create_router(get_connection, bot, clock, encrypt_data, decrypt_data):
    router = Router(name="assets_admin")
    access = AssetAccess(get_connection, admin=True)
    router.message.middleware(access)
    router.callback_query.middleware(access)

    def cancel_kb(back_callback):
        return InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="❌ انصراف و لغو فرم", callback_data=back_callback)
        ]])

    async def save_admin_asset(message_obj, state, staff_id, atype, details, encrypted_password=None):
        with get_connection() as conn:
            asset_id, staff_name, telegram_user_id = service.assign(
                conn, message_obj.from_user.id, staff_id, atype, details,
                clock().strftime("%Y/%m/%d %H:%M"), encrypted_password,
            )
        await state.clear()
        target_msg = message_obj if isinstance(message_obj, Message) else message_obj.message
        await target_msg.answer(f"✅ مال ({atype}) به نام <b>{html.escape(staff_name)}</b> ثبت شد.", parse_mode="HTML")
        if telegram_user_id:
            try:
                user_kb = InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="✅ تحویل گرفتم و تأیید می‌کنم", callback_data=f"confirmasset_{asset_id}")
                ]])
                await bot.send_message(chat_id=telegram_user_id,
                    text=f"📦 <b>تجهیز جدید به نام شما ثبت شد:</b>\n\nنوع: {html.escape(atype)}\nمشخصات: {html.escape(details)}\n\nلطفاً پس از دریافت فیزیکی، روی دکمه زیر کلیک کنید:",
                    reply_markup=user_kb, parse_mode="HTML")
            except Exception:
                logging.exception("Could not notify asset recipient")


    @router.callback_query(F.data == "admin_assign_asset")
    async def admin_assign_asset_menu(callback: CallbackQuery):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ واگذاری تجهیز جدید به پرسنل", callback_data="asgn_new_step1")],
            [InlineKeyboardButton(text="✏️ ویرایش یا مشاهده اموال تحویلی", callback_data="asgn_list_active")],
            [InlineKeyboardButton(text="🔙 بازگشت به پنل", callback_data="admin_panel")]
        ])
        await callback.message.edit_text("🚗 <b>مدیریت اموال و تجهیزات پرسنل</b>", reply_markup=kb, parse_mode="HTML")
        await callback.answer()


    @router.callback_query(F.data == "asgn_new_step1")
    async def admin_assign_asset_start(callback: CallbackQuery):
        with get_connection() as conn:
            rows = service.staff_list(conn, callback.from_user.id)
        if not rows:
            await callback.answer("پرسنل فعالی یافت نشد.", show_alert=True)
            return
        buttons = [[InlineKeyboardButton(text=r[1], callback_data=f"asgnuser_{r[0]}")] for r in rows]
        buttons.append([InlineKeyboardButton(text="🔙 بازگشت", callback_data="admin_assign_asset")])
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        date_now = clock().strftime("%Y/%m/%d")
        await callback.message.edit_text(f"👤 پرسنل مورد نظر جهت واگذاری اموال را انتخاب کنید:\n📅 تاریخ واگذاری: <code>{date_now}</code>", reply_markup=kb, parse_mode="HTML")
        await callback.answer()


    @router.callback_query(F.data.startswith("asgnuser_"))
    async def admin_asgn_user(callback: CallbackQuery, state: FSMContext):
        staff_id = asset_number(callback.data.split("_")[1])
        with get_connection() as conn:
            service.recipient(conn, callback.from_user.id, staff_id)
        await state.update_data(target_staff_id=staff_id)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚗 خودروی سازمانی", callback_data="asgntype_car")],
            [InlineKeyboardButton(text="⛽ کارت سوخت", callback_data="asgntype_fuel")],
            [InlineKeyboardButton(text="💳 کارت‌خوان (POS)", callback_data="asgntype_pos")],
            [InlineKeyboardButton(text="🖨️ پرینتر جیبی", callback_data="asgntype_printer")],
            [InlineKeyboardButton(text="🔙 بازگشت", callback_data="admin_assign_asset")]
        ])
        await callback.message.edit_text("نوع تجهیز را انتخاب کنید:", reply_markup=kb)
        await callback.answer()


    @router.callback_query(F.data.startswith("asgntype_"))
    async def admin_asgn_type(callback: CallbackQuery, state: FSMContext):
        atype_key = callback.data.split("_", 1)[1]
        mapping = {
            "car": "خودروی سازمانی",
            "fuel": "کارت سوخت",
            "pos": "کارت‌خوان",
            "printer": "پرینتر جیبی"
        }
        if atype_key not in mapping:
            raise service.AssetError("نوع تجهیز نامعتبر است.")
        atype = mapping[atype_key]
        await state.update_data(asset_type=atype)
    
        if atype_key == "car":
            await state.set_state(AdminForm.admin_asgn_temp_code)
            await callback.message.edit_text("🚗 1️⃣ کد خودرو را وارد کنید:")
        elif atype_key == "fuel":
            await state.set_state(AdminForm.admin_asgn_temp_fcode)
            await callback.message.edit_text("⛽ 1️⃣ کد کارت سوخت را وارد کنید:")
        elif atype_key == "pos":
            await state.set_state(AdminForm.admin_asgn_temp_pcode)
            await callback.message.edit_text("💳 1️⃣ کد دستگاه پوز را وارد کنید:")
        elif atype_key == "printer":
            await state.set_state(AdminForm.admin_asgn_temp_prcode)
            await callback.message.edit_text("🖨️ 1️⃣ کد پرینتر جیبی را وارد کنید:")
        await callback.answer()


    @router.message(AdminForm.admin_asgn_temp_code)
    async def adm_car_s2(message: Message, state: FSMContext):
        if not message.text:
            await message.answer("❌ کد معتبر وارد کنید.")
            return
        await state.update_data(asgn_car_code=message.text.strip())
        await state.set_state(AdminForm.admin_asgn_temp_plate)
        await message.answer("🚗 2️⃣ پلاک خودرو را وارد کنید:")


    @router.message(AdminForm.admin_asgn_temp_plate)
    async def adm_car_s3(message: Message, state: FSMContext):
        if not message.text:
            await message.answer("❌ پلاک معتبر وارد کنید.")
            return
        await state.update_data(asgn_car_plate=message.text.strip())
        await state.set_state(AdminForm.admin_asgn_temp_type)
        await message.answer("🚗 3️⃣ نوع خودرو را وارد کنید:")


    @router.message(AdminForm.admin_asgn_temp_type)
    async def adm_car_s4(message: Message, state: FSMContext):
        if not message.text:
            await message.answer("❌ نوع خودرو معتبر وارد کنید.")
            return
        await state.update_data(asgn_car_type=message.text.strip())
        await state.set_state(AdminForm.admin_asgn_temp_km)
        await message.answer("🚗 4️⃣ کیلومتر تحویلی را وارد کنید:")


    @router.message(AdminForm.admin_asgn_temp_km)
    async def adm_car_s5(message: Message, state: FSMContext):
        clean_km = normalize_persian_numbers(message.text).strip() if message.text else ""
        if not clean_km.isdigit():
            await message.answer("❌ کیلومتر باید عدد باشد:")
            return
        await state.update_data(asgn_car_km=clean_km)
        await state.set_state(AdminForm.admin_asgn_temp_desc)
        await message.answer("🚗 5️⃣ توضیحات تکمیلی (اگر ندارد <code>-</code>):", parse_mode="HTML")


    @router.message(AdminForm.admin_asgn_temp_desc)
    async def adm_car_save_final(message: Message, state: FSMContext):
        if not message.text:
            await message.answer("❌ توضیحات معتبر وارد کنید.")
            return
        desc = message.text.strip()
        data = await state.get_data()
        staff_id = data.get("target_staff_id")
        date_now = clock().strftime("%Y/%m/%d")
        details = f"تاریخ واگذاری: {date_now} | کد: {data.get('asgn_car_code')} | پلاک: {data.get('asgn_car_plate')} | نوع: {data.get('asgn_car_type')} | کیلومتر: {data.get('asgn_car_km')} | توضیحات: {desc}"
        await save_admin_asset(message, state, staff_id, "خودروی سازمانی", details)


    @router.message(AdminForm.admin_asgn_temp_fcode)
    async def adm_fuel_s2(message: Message, state: FSMContext):
        if not message.text:
            await message.answer("❌ کد معتبر وارد کنید.")
            return
        await state.update_data(asgn_fcode=message.text.strip())
        await state.set_state(AdminForm.admin_asgn_temp_fpass)
        await message.answer("⛽ 2️⃣ رمز کارت سوخت را وارد کنید:")


    @router.message(AdminForm.admin_asgn_temp_fpass)
    async def adm_fuel_s3(message: Message, state: FSMContext):
        if not message.text:
            await message.answer("❌ رمز معتبر وارد کنید.")
            return
        await state.update_data(asgn_fpass=message.text.strip())
        await state.set_state(AdminForm.admin_asgn_temp_l1500)
        await message.answer("⛽ 3️⃣ میزان لیتر سهمیه <b>۱۵۰۰ تومانی</b> ماهیانه را وارد کنید:", parse_mode="HTML")


    @router.message(AdminForm.admin_asgn_temp_l1500)
    async def adm_fuel_s4(message: Message, state: FSMContext):
        if not message.text:
            await message.answer("❌ مقدار معتبر وارد کنید.")
            return
        await state.update_data(asgn_l1500=message.text.strip())
        await state.set_state(AdminForm.admin_asgn_temp_l3000)
        await message.answer("⛽ 4️⃣ میزان لیتر سهمیه <b>۳۰۰۰ تومانی</b> ماهیانه را وارد کنید:", parse_mode="HTML")


    @router.message(AdminForm.admin_asgn_temp_l3000)
    async def adm_fuel_s5(message: Message, state: FSMContext):
        if not message.text:
            await message.answer("❌ مقدار معتبر وارد کنید.")
            return
        await state.update_data(asgn_l3000=message.text.strip())
        await state.set_state(AdminForm.admin_asgn_temp_l10000)
        await message.answer("⛽ 5️⃣ میزان لیتر سهمیه <b>۱۰,۰۰۰ تومانی</b> ماهیانه را وارد کنید:", parse_mode="HTML")


    @router.message(AdminForm.admin_asgn_temp_l10000)
    async def adm_fuel_save_final(message: Message, state: FSMContext):
        if not message.text:
            await message.answer("❌ مقدار معتبر وارد کنید.")
            return
        l10000 = message.text.strip()
        data = await state.get_data()
        staff_id = data.get("target_staff_id")
        date_now = clock().strftime("%Y/%m/%d")
        details = f"تاریخ واگذاری: {date_now} | کد کارت سوخت: {data.get('asgn_fcode')} | رمز: [محفوظ و مختص پرسنل] | ۱۵۰۰ تومانی: {data.get('asgn_l1500')} | ۳۰۰۰ تومانی: {data.get('asgn_l3000')} | ۱۰,۰۰۰ تومانی: {l10000}"
        encrypted_pass = encrypt_data(data.get('asgn_fpass'))
        await save_admin_asset(message, state, staff_id, "کارت سوخت", details, encrypted_password=encrypted_pass)


    @router.message(AdminForm.admin_asgn_temp_pcode)
    async def adm_pos_s2(message: Message, state: FSMContext):
        if not message.text:
            await message.answer("❌ کد معتبر وارد کنید.")
            return
        await state.update_data(asgn_pcode=message.text.strip())
        await state.set_state(AdminForm.admin_asgn_temp_pbank)
        await message.answer("💳 2️⃣ نام بانک را وارد کنید:")


    @router.message(AdminForm.admin_asgn_temp_pbank)
    async def adm_pos_s3(message: Message, state: FSMContext):
        if not message.text:
            await message.answer("❌ نام بانک معتبر وارد کنید.")
            return
        await state.update_data(asgn_pbank=message.text.strip())
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ دارد", callback_data="admposchg_yes"),
             InlineKeyboardButton(text="❌ ندارد", callback_data="admposchg_no")]
        ])
        await state.set_state(AdminForm.admin_asgn_temp_pcharger)
        await message.answer("💳 3️⃣ آیا دستگاه پوز <b>شارژر</b> دارد؟", reply_markup=kb, parse_mode="HTML")


    @router.callback_query(AdminForm.admin_asgn_temp_pcharger, F.data.startswith("admposchg_"))
    async def adm_pos_save_final(callback: CallbackQuery, state: FSMContext):
        charger = charger_value(callback.data)
        data = await state.get_data()
        staff_id = data.get("target_staff_id")
        date_now = clock().strftime("%Y/%m/%d")
        details = f"تاریخ واگذاری: {date_now} | کد پوز: {data.get('asgn_pcode')} | بانک: {data.get('asgn_pbank')} | شارژر: {charger}"
        try:
            await callback.message.edit_text(callback.message.text + f"\n\nشارژر: {charger}")
        except Exception:
            pass
        await save_admin_asset(callback, state, staff_id, "کارت‌خوان", details)
        await callback.answer()


    @router.message(AdminForm.admin_asgn_temp_prcode)
    async def adm_pr_s2(message: Message, state: FSMContext):
        if not message.text:
            await message.answer("❌ کد معتبر وارد کنید.")
            return
        await state.update_data(asgn_prcode=message.text.strip())
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ دارد", callback_data="admprchg_yes"),
             InlineKeyboardButton(text="❌ ندارد", callback_data="admprchg_no")]
        ])
        await state.set_state(AdminForm.admin_asgn_temp_prcharger)
        await message.answer("🖨️ 2️⃣ آیا پرینتر <b>شارژر</b> دارد؟", reply_markup=kb, parse_mode="HTML")


    @router.callback_query(AdminForm.admin_asgn_temp_prcharger, F.data.startswith("admprchg_"))
    async def adm_pr_save_final(callback: CallbackQuery, state: FSMContext):
        charger = charger_value(callback.data)
        data = await state.get_data()
        staff_id = data.get("target_staff_id")
        date_now = clock().strftime("%Y/%m/%d")
        details = f"تاریخ واگذاری: {date_now} | کد پرینتر: {data.get('asgn_prcode')} | شارژر: {charger}"
        try:
            await callback.message.edit_text(callback.message.text + f"\n\nشارژر: {charger}")
        except Exception:
            pass
        await save_admin_asset(callback, state, staff_id, "پرینتر جیبی", details)
        await callback.answer()


    @router.callback_query(F.data == "asgn_list_active")
    async def admin_list_active_assets(callback: CallbackQuery):
        with get_connection() as conn:
            rows = service.recent(conn, callback.from_user.id)

        if not rows:
            await callback.answer("هیچ اموالی ثبت نشده است.", show_alert=True)
            return

        for r in rows:
            aid, sname, atype, details, active, approval_status, enc_pass = r
            status = "🟢 فعال" if active == 1 else "🔴 عودت داده شده"
            pass_info = f"\n🔑 رمز عبور/کارت: <code>{html.escape(decrypt_data(enc_pass))}</code>" if enc_pass else ""
            text = f"🆔 شناسه مال: {aid}\n👤 پرسنل: {html.escape(sname)}\n📦 نوع: {html.escape(atype)}\n📝 جزئیات: {html.escape(details)}{pass_info}\n📌 وضعیت: {status} | تایید: {approval_status}"
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✏️ ویرایش جزئیات", callback_data=f"asgnedit_{aid}"),
                 InlineKeyboardButton(text="🗑️ حذف/غیرفعال (عودت)", callback_data=f"asgndel_{aid}")]
            ])
            await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
        await callback.answer()


    @router.callback_query(F.data.startswith("asgnedit_"))
    async def admin_edit_asset_start(callback: CallbackQuery, state: FSMContext):
        aid = asset_number(callback.data.removeprefix("asgnedit_"))
        with get_connection() as conn:
            service.editable_asset(conn, callback.from_user.id, aid)
        await state.update_data(editing_asset_id=aid)
        await state.set_state(AdminForm.edit_asset_details)
        await callback.message.edit_text("✍️ جزئیات جدید را وارد کنید:")
        await callback.answer()


    @router.message(AdminForm.edit_asset_details)
    async def admin_edit_asset_save(message: Message, state: FSMContext):
        if not message.text:
            await message.answer("❌ جزئیات معتبر وارد کنید.")
            return
        new_details = message.text.strip()
        data = await state.get_data()
        aid = data.get("editing_asset_id")

        with get_connection() as conn:
            service.edit(conn, message.from_user.id, aid, new_details)

        await message.answer("✅ مشخصات مال با موفقیت ویرایش شد.")
        await state.clear()


    @router.callback_query(F.data.startswith("asgndel_"))
    async def admin_delete_asset(callback: CallbackQuery):
        aid = asset_number(callback.data.removeprefix("asgndel_"))
        date_now = clock().strftime("%Y/%m/%d")
        with get_connection() as conn:
            service.return_by_admin(conn, callback.from_user.id, aid, date_now)
        try:
            await callback.message.edit_text(callback.message.text + f"\n\n<b>[غیرفعال و عودت داده شد - تاریخ: {date_now}]</b>", reply_markup=None, parse_mode="HTML")
        except Exception:
            pass
        await callback.answer("مال عودت و غیرفعال شد.")

    return router
