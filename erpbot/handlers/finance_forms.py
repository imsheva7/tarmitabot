"""Advance, petty cash and purchase forms with explicit dependencies."""
import html
from aiogram import Router, F, BaseMiddleware
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from ..core.dates import normalize_persian_numbers
from ..services import finance as service


class Form(StatesGroup):
    purch_desc = State()
    purch_item_name = State()
    purch_preview = State()
    purch_qty = State()
    waiting_for_advance_amount = State()
    waiting_for_advance_card = State()
    waiting_for_advance_preview = State()
    waiting_for_advance_reason = State()
    waiting_for_petty_amount = State()
    waiting_for_petty_desc = State()
    waiting_for_petty_photo = State()
    waiting_for_petty_preview = State()


class FinanceAccess(BaseMiddleware):
    def __init__(self, connection_factory):
        self.connection_factory=connection_factory

    async def __call__(self, handler, event, data):
        try:
            with self.connection_factory() as conn:
                service.active_staff(conn,event.from_user.id)
            return await handler(event,data)
        except service.FinanceError as exc:
            if isinstance(event,CallbackQuery):
                await event.answer(str(exc),show_alert=True)
            else:
                await event.answer(str(exc))


def create_router(get_connection, clock, encrypt_data, *, submit_request):
    router=Router(name="finance_forms")
    access=FinanceAccess(get_connection)
    router.message.middleware(access)
    router.callback_query.middleware(access)

    def staff_info(actor_id):
        with get_connection() as conn:
            return service.active_staff(conn,actor_id)

    def cancel_kb(back_callback):
        return InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="❌ انصراف و لغو فرم",callback_data=back_callback)
        ]])

    @router.callback_query(F.data == "req_advance")
    async def process_advance_start(callback: CallbackQuery, state: FSMContext):
        await state.set_state(Form.waiting_for_advance_amount)
        kb = cancel_kb("menu_admin_finance")
        await callback.message.edit_text("🟩⬜⬜ <b>مرحله ۱ از ۳:</b> مبلغ درخواستی مساعده (به ریال) را به عدد وارد کنید:", reply_markup=kb, parse_mode="HTML")
        await callback.answer()


    @router.message(Form.waiting_for_advance_amount)
    async def receive_advance_amount(message: Message, state: FSMContext):
        if not message.text:
            await message.answer("❌ لطفاً مبلغ معتبر وارد کنید.")
            return
        amount = service.amount_value(message.text, allow_rial=True)
        now = clock()
        with get_connection() as conn:
            service.require_advance_capacity(conn, message.from_user.id, now.strftime("%Y/%m"), now.day, amount)

        await state.update_data(advance_amount_int=amount, advance_amount=f"{amount:,}")
        await state.set_state(Form.waiting_for_advance_card)
        await message.answer("🟩🟩⬜ <b>مرحله ۲ از ۳:</b> شماره کارت (۱۶ رقم) یا شبا جهت واریز را وارد کنید:", parse_mode="HTML")


    @router.message(Form.waiting_for_advance_card)
    async def receive_advance_card(message: Message, state: FSMContext):
        if not message.text:
            await message.answer("❌ لطفاً شماره کارت یا شبا معتبر وارد کنید.")
            return
        card = normalize_persian_numbers(message.text).strip()
        if not service.valid_card(card):
            await message.answer("❌ شماره کارت یا شبا نامعتبر است:")
            return
        await state.update_data(advance_card=card)
        await state.set_state(Form.waiting_for_advance_reason)
        await message.answer("🟩🟩🟩 <b>مرحله ۳ از ۳:</b> دلیل درخواست مساعده را بنویسید:", parse_mode="HTML")


    @router.message(Form.waiting_for_advance_reason)
    async def receive_advance_reason(message: Message, state: FSMContext):
        if not message.text:
            await message.answer("❌ لطفاً دلیل معتبر وارد کنید.")
            return
        reason = message.text.strip()
        await state.update_data(advance_reason=reason)
        data = await state.get_data()

        preview_text = (
            f"📋 <b>پیش‌نمایش درخواست مساعده</b>\n\n"
            f"💵 مبلغ: {html.escape(data.get('advance_amount'))} ریال\n"
            f"💳 شماره کارت/شبا: <code>محفوظ (ارسال امن به مالی)</code>\n"
            f"📝 دلیل: {html.escape(reason)}\n\n"
            f"آیا اطلاعات تایید می‌شود؟"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚀 تأیید و ارسال نهایی", callback_data="adv_submit_final"),
             InlineKeyboardButton(text="❌ لغو و انصراف", callback_data="back_to_main")]
        ])
        await state.set_state(Form.waiting_for_advance_preview)
        await message.answer(preview_text, reply_markup=kb, parse_mode="HTML")


    @router.callback_query(Form.waiting_for_advance_preview, F.data == "adv_submit_final")
    async def submit_advance_final(callback: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        user_id = callback.from_user.id
        _, staff_name, _ = staff_info(user_id)
    
        col1 = f"مبلغ: {data.get('advance_amount')} ریال"
        col2 = f"دلیل: {data.get('advance_reason')}"
        col3 = "کارت/شبا: [محفوظ و مختص واحد مالی]"
        if not service.valid_card(data.get("advance_card") or ""):
            raise service.FinanceError("شماره کارت یا شبا نامعتبر است.")
        sensitive_data = encrypt_data(f"کارت/شبا: {data.get('advance_card')}")
        amount = data.get('advance_amount_int', 0)
    
        await submit_request(callback, user_id, staff_name, "مساعده", col1, col2, col3, "-", amount=amount, sensitive_data=sensitive_data)
        await state.clear()
        await callback.answer()

    @router.callback_query(F.data == "req_petty")
    async def process_petty_start(callback: CallbackQuery, state: FSMContext):
        await state.set_state(Form.waiting_for_petty_photo)
        kb = cancel_kb("menu_assets_purchase")
        await callback.message.edit_text("🟩⬜⬜ <b>مرحله ۱ از ۳:</b> عکس واضح فاکتور خرید را ارسال نمایید:", reply_markup=kb, parse_mode="HTML")
        await callback.answer()


    @router.message(Form.waiting_for_petty_photo, F.photo)
    async def receive_petty_photo(message: Message, state: FSMContext):
        photo_id = message.photo[-1].file_id
        await state.update_data(petty_photo=photo_id)
        await state.set_state(Form.waiting_for_petty_amount)
        await message.answer("🟩🟩⬜ <b>مرحله ۲ از ۳:</b> مبلغ فاکتور (به ریال) را به عدد وارد کنید:", parse_mode="HTML")


    @router.message(Form.waiting_for_petty_amount)
    async def receive_petty_amount(message: Message, state: FSMContext):
        if not message.text:
            await message.answer("❌ مبلغ معتبر وارد کنید.")
            return
        amount_int = service.amount_value(message.text)
        await state.update_data(petty_amount_int=amount_int, petty_amount=f"{amount_int:,} ریال")
        await state.set_state(Form.waiting_for_petty_desc)
        await message.answer("🟩🟩🟩 <b>مرحله ۳ از ۳:</b> شرح هزینه را بنویسید:", parse_mode="HTML")


    @router.message(Form.waiting_for_petty_desc)
    async def receive_petty_desc(message: Message, state: FSMContext):
        if not message.text:
            await message.answer("❌ شرح هزینه معتبر وارد کنید.")
            return
        desc = message.text.strip()
        await state.update_data(petty_desc=desc)
        data = await state.get_data()

        preview_text = f"📋 <b>پیش‌نمایش کامل فاکتور تنخواه</b>\n\n💵 مبلغ: {html.escape(data.get('petty_amount'))}\n📝 شرح هزینه: {html.escape(desc)}\n🖼 تصویر فاکتور ضمیمه شده است.\n\nتأیید و ارسال نهایی می‌شود?"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚀 تأیید و ارسال نهایی", callback_data="petty_submit_final"),
             InlineKeyboardButton(text="❌ لغو و انصراف", callback_data="back_to_main")]
        ])
        await state.set_state(Form.waiting_for_petty_preview)
        await message.answer_photo(photo=data.get('petty_photo'), caption=preview_text, reply_markup=kb, parse_mode="HTML")


    @router.callback_query(Form.waiting_for_petty_preview, F.data == "petty_submit_final")
    async def submit_petty_final(callback: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        user_id = callback.from_user.id
        _, staff_name, _ = staff_info(user_id)
    
        col1 = f"مبلغ: {data.get('petty_amount')}"
        col2 = f"بابت: {data.get('petty_desc')}"
        col3 = "-"
        amount = data.get('petty_amount_int', 0)
        await submit_request(callback, user_id, staff_name, "تنخواه", col1, col2, col3, "-", amount=amount, photo_id=data.get("petty_photo"))
        await state.clear()
        await callback.answer()

    @router.callback_query(F.data == "req_purchase")
    async def process_purchase_start(callback: CallbackQuery, state: FSMContext):
        await state.set_state(Form.purch_item_name)
        kb = cancel_kb("menu_assets_purchase")
        await callback.message.edit_text("🟩⬜⬜ <b>مرحله ۱ از ۳:</b> نام کالا یا ملزومات مورد نیاز را بنویسید:", reply_markup=kb, parse_mode="HTML")
        await callback.answer()


    @router.message(Form.purch_item_name)
    async def receive_purch_item(message: Message, state: FSMContext):
        if not message.text:
            await message.answer("❌ نام کالا معتبر وارد کنید.")
            return
        await state.update_data(purch_item=message.text.strip())
        await state.set_state(Form.purch_qty)
        await message.answer("🟩🟩⬜ <b>مرحله ۲ از ۳:</b> تعداد یا مقدار مورد نیاز را وارد کنید:", parse_mode="HTML")


    @router.message(Form.purch_qty)
    async def receive_purch_qty(message: Message, state: FSMContext):
        if not message.text:
            await message.answer("❌ تعداد معتبر وارد کنید.")
            return
        await state.update_data(purch_qty=message.text.strip())
        await state.set_state(Form.purch_desc)
        await message.answer("🟩🟩🟩 <b>مرحله ۳ از ۳:</b> توضیحات یا دلیل نیاز به خرید را بنویسید:", parse_mode="HTML")


    @router.message(Form.purch_desc)
    async def receive_purch_desc(message: Message, state: FSMContext):
        if not message.text:
            await message.answer("❌ توضیحات معتبر وارد کنید.")
            return
        desc = message.text.strip()
        await state.update_data(purch_desc=desc)
        data = await state.get_data()

        preview_text = f"📋 <b>پیش‌نمایش کامل درخواست خرید انبار</b>\n\n🛒 کالا: {html.escape(data.get('purch_item'))}\n🔢 تعداد: {html.escape(data.get('purch_qty'))}\n📝 توضیحات: {html.escape(desc)}\n\nتأیید و ارسال نهایی می‌شود?"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚀 تأیید و ارسال نهایی", callback_data="purch_submit_final"),
             InlineKeyboardButton(text="❌ لغو و انصراف", callback_data="back_to_main")]
        ])
        await state.set_state(Form.purch_preview)
        await message.answer(preview_text, reply_markup=kb, parse_mode="HTML")


    @router.callback_query(Form.purch_preview, F.data == "purch_submit_final")
    async def submit_purch_final(callback: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        user_id = callback.from_user.id
        _, staff_name, _ = staff_info(user_id)
    
        col1 = f"کالا: {data.get('purch_item')}"
        col2 = f"تعداد: {data.get('purch_qty')}"
        col3 = f"توضیحات: {data.get('purch_desc')}"
        await submit_request(callback, user_id, staff_name, "خرید ملزومات", col1, col2, col3, "-")
        await state.clear()
        await callback.answer()

    return router
