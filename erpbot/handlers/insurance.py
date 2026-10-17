"""Insurance registration with current role checks on every form step."""
import html
import logging
from aiogram import Router,F,BaseMiddleware
from aiogram.types import Message,CallbackQuery,InlineKeyboardButton,InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State,StatesGroup
from ..core.dates import normalize_jalali_date,validate_custom_date
from ..services import insurance as service
from .organization_callbacks import callback_number


class AdminForm(StatesGroup):
    ins_body=State()
    ins_car_code=State()
    ins_car_name=State()
    ins_company=State()
    ins_plate=State()
    ins_third=State()


class Access(BaseMiddleware):
    def __init__(self,connection_factory): self.connection_factory=connection_factory

    async def __call__(self,handler,event,data):
        try:
            with self.connection_factory() as conn:
                service.require_admin(conn,event.from_user.id)
            return await handler(event,data)
        except service.InsuranceError as exc:
            if isinstance(event,CallbackQuery): await event.answer(str(exc),show_alert=True)
            else: await event.answer(str(exc))


def create_router(get_connection,bot,group_id,insurance_topic):
    router=Router(name="insurance")
    access=Access(get_connection)
    router.message.middleware(access)
    router.callback_query.middleware(access)

    @router.callback_query(F.data == "admin_add_insurance")
    async def admin_insurance_start(callback: CallbackQuery, state: FSMContext):
        with get_connection() as conn:
            rows=service.cars(conn,callback.from_user.id)
        buttons=[[InlineKeyboardButton(text=f"🚗 انتخاب خودرو: {code}",callback_data=f"insasset_{asset_id}")] for asset_id,code in rows]

        buttons.append([InlineKeyboardButton(text="➕ ورود کد/خودروی جدید", callback_data="inselcar_NEW")])
        buttons.append([InlineKeyboardButton(text="🔙 بازگشت", callback_data="admin_panel")])
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)

        await callback.message.edit_text("🛡️ <b>ثبت بیمه‌نامه خودرو</b>\n\nلطفاً خودروی مورد نظر را از لیست اموال انتخاب کنید:", reply_markup=kb, parse_mode="HTML")
        await callback.answer()


    @router.callback_query(F.data.startswith("inselcar_") | F.data.startswith("insasset_"))
    async def admin_insurance_car_selected(callback: CallbackQuery, state: FSMContext):
        numeric = callback.data.startswith('insasset_')
        val = callback.data.partition('_')[2]
        if not numeric and val == "NEW":
            await state.update_data(ins_selector=None,ins_asset_id=None)
            await state.set_state(AdminForm.ins_car_code)
            await callback.message.edit_text("🛡️ <b>ثبت بیمه خودرو جدید</b>\n\n1️⃣ کد خودرو را وارد کنید:", parse_mode="HTML")
        else:
            selector=val
            asset_id=None
            with get_connection() as conn:
                if numeric:
                    asset_id=callback_number(val)
                    if asset_id is None or asset_id<=0:
                        raise service.InsuranceError('شناسه خودرو نامعتبر است.')
                    val=service.selected_car(conn,callback.from_user.id,asset_id=asset_id)
                else:
                    val=service.selected_car(conn,callback.from_user.id,selector)
            await state.update_data(ins_code=val, ins_car="خودروی سازمانی", ins_plate="-",
                                    ins_selector=None if numeric else selector,ins_asset_id=asset_id)
            await state.set_state(AdminForm.ins_company)
            await callback.message.edit_text(f"🛡️ برای خودرو با کد <code>{html.escape(val)}</code>:\n\n2️⃣ نام شرکت بیمه را وارد کنید:", parse_mode="HTML")
        await callback.answer()


    @router.message(AdminForm.ins_car_code)
    async def admin_ins_code(message: Message, state: FSMContext):
        if not message.text:
            await message.answer("❌ کد معتبر وارد کنید.")
            return
        await state.update_data(ins_code=message.text.strip())
        await state.set_state(AdminForm.ins_car_name)
        await message.answer("2️⃣ نام خودرو:")


    @router.message(AdminForm.ins_car_name)
    async def admin_ins_car_name(message: Message, state: FSMContext):
        if not message.text:
            await message.answer("❌ نام خودرو معتبر وارد کنید.")
            return
        await state.update_data(ins_car=message.text.strip())
        await state.set_state(AdminForm.ins_plate)
        await message.answer("3️⃣ پلاک خودرو:")


    @router.message(AdminForm.ins_plate)
    async def admin_ins_plate(message: Message, state: FSMContext):
        if not message.text:
            await message.answer("❌ پلاک معتبر وارد کنید.")
            return
        await state.update_data(ins_plate=message.text.strip())
        await state.set_state(AdminForm.ins_company)
        await message.answer("4️⃣ نام شرکت بیمه:")


    @router.message(AdminForm.ins_company)
    async def admin_ins_company(message: Message, state: FSMContext):
        if not message.text:
            await message.answer("❌ شرکت بیمه معتبر وارد کنید.")
            return
        await state.update_data(ins_company=message.text.strip())
        await state.set_state(AdminForm.ins_third)
        await message.answer("5️⃣ سررسید بیمه شخص ثالث (<code>YYYY/MM/DD</code>):", parse_mode="HTML")


    @router.message(AdminForm.ins_third)
    async def admin_ins_third(message: Message, state: FSMContext):
        text_date = normalize_jalali_date(message.text) if message.text else ""
        if not validate_custom_date(text_date):
            await message.answer("❌ فرمت تاریخ نامعتبر است:")
            return
        await state.update_data(ins_third=text_date)
        await state.set_state(AdminForm.ins_body)
        await message.answer("6️⃣ سررسید بیمه بدنه (<code>YYYY/MM/DD</code>) (اگر ندارد <code>-</code>):", parse_mode="HTML")


    @router.message(AdminForm.ins_body)
    async def admin_ins_body_save(message: Message, state: FSMContext):
        text_date = message.text.strip() if message.text else "-"
        if text_date != "-":
            text_date = normalize_jalali_date(text_date)
            if not validate_custom_date(text_date):
                await message.answer("❌ تاریخ نامعتبر است:")
                return
        body_date = text_date
        data = await state.get_data()
    
        with get_connection() as conn:
            service.save(conn,message.from_user.id,data.get("ins_code"),data.get("ins_car"),data.get("ins_plate"),
                         data.get("ins_company"),data.get("ins_third"),body_date,
                         selector=data.get("ins_selector"),asset_id=data.get("ins_asset_id"))
        await state.clear()

        success_msg = f"🛡️ <b>ثبت موفق بیمه خودرو</b>\n\n🚗 کد: {html.escape(data.get('ins_code'))}\n📌 خودرو: {html.escape(data.get('ins_car'))} ({html.escape(data.get('ins_plate'))})\n🏢 بیمه: {html.escape(data.get('ins_company'))}\n📅 ثالث: {html.escape(data.get('ins_third'))}\n📅 بدنه: {html.escape(body_date)}"
        await message.answer(success_msg, parse_mode="HTML")
        try:
            await bot.send_message(chat_id=group_id, message_thread_id=insurance_topic, text=success_msg, parse_mode="HTML")
        except Exception:
            pass

    return router
