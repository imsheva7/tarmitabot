"""Personnel management Router; main-admin permission is checked on every step."""
import html
from aiogram import Router,F,BaseMiddleware
from aiogram.types import Message,CallbackQuery,InlineKeyboardMarkup,InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State,StatesGroup
from ..core.dates import normalize_persian_numbers,normalize_jalali_date,validate_custom_date
from ..services import personnel as service
from .organization_callbacks import callback_number


def staff_number(raw):
    value=callback_number(raw)
    if value is None or value<=0: raise service.PersonnelError("شناسه پرسنلی نامعتبر است.")
    return value


def cancel_kb(back_callback):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="❌ انصراف و لغو فرم",callback_data=back_callback)
    ]])


class Access(BaseMiddleware):
    def __init__(self,connection_factory): self.connection_factory=connection_factory

    async def __call__(self,handler,event,data):
        try:
            with self.connection_factory() as conn:
                category=isinstance(event,CallbackQuery) and event.data=='adm_cat_staff'
                service.require_admin(conn,event.from_user.id,main_only=not category)
            return await handler(event,data)
        except service.PersonnelError as exc:
            if isinstance(event,CallbackQuery): await event.answer(str(exc),show_alert=True)
            else: await event.answer(str(exc))


class AdminForm(StatesGroup):
    add_staff_balance=State()
    add_staff_date=State()
    add_staff_name=State()
    add_staff_phone=State()
    add_staff_role=State()
    edit_staff_value=State()


def create_router(get_connection,clock):
    router=Router(name="personnel")
    access=Access(get_connection)
    router.message.middleware(access)
    router.callback_query.middleware(access)

    @router.callback_query(F.data == "adm_cat_staff")
    async def admin_category_staff(callback: CallbackQuery):
        with get_connection() as conn:
            service.require_admin(conn,callback.from_user.id,main_only=False)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ افزودن پرسنل جدید", callback_data="admin_add_staff")],
            [InlineKeyboardButton(text="✏️ ویرایش مشخصات پرسنل", callback_data="admin_edit_staff_list")],
            [InlineKeyboardButton(text="🚫 غیرفعال کردن پرسنل (ثبت تسویه)", callback_data="admin_deactivate_staff_list")],
            [InlineKeyboardButton(text="📋 لیست کامل پرسنل و جزئیات", callback_data="admin_list_staff")],
            [InlineKeyboardButton(text="🏢 مدیریت واحدهای سازمانی", callback_data="orgunits_menu")],
            [InlineKeyboardButton(text="🔙 بازگشت به پنل", callback_data="admin_panel")]
        ])
        await callback.message.edit_text("👥 <b>مدیریت پرسنل و ویرایش:</b>", reply_markup=kb, parse_mode="HTML")
        await callback.answer()


    @router.callback_query(F.data == "admin_add_staff")
    async def adm_add_staff_start(callback: CallbackQuery, state: FSMContext):
        await state.set_state(AdminForm.add_staff_name)
        kb = cancel_kb("adm_cat_staff")
        await callback.message.edit_text("➕ نام پرسنل جدید را وارد کنید:", reply_markup=kb)
        await callback.answer()


    @router.message(AdminForm.add_staff_name)
    async def adm_add_staff_name(message: Message, state: FSMContext):
        if not message.text:
            await message.answer("❌ نام معتبر وارد کنید.")
            return
        await state.update_data(new_sname=message.text.strip())
        await state.set_state(AdminForm.add_staff_phone)
        await message.answer("شماره تماس پرسنل را وارد کنید:")


    @router.message(AdminForm.add_staff_phone)
    async def adm_add_staff_phone(message: Message, state: FSMContext):
        if not message.text:
            await message.answer("❌ شماره معتبر وارد کنید.")
            return
        await state.update_data(new_sphone=normalize_persian_numbers(message.text).strip())
        await state.set_state(AdminForm.add_staff_role)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👑 مدیر اصلی (main_admin)", callback_data="role_main_admin")],
            [InlineKeyboardButton(text="💳 واحد مالی (finance)", callback_data="role_finance")],
            [InlineKeyboardButton(text="🛒 مسئول خرید (purchase)", callback_data="role_purchase")],
            [InlineKeyboardButton(text="👤 پرسنل عادی (staff)", callback_data="role_staff")]
        ])
        await message.answer("نقش سازمانی پرسنل را انتخاب کنید:", reply_markup=kb)


    @router.callback_query(AdminForm.add_staff_role, F.data.startswith("role_"))
    async def adm_add_staff_role_selected(callback: CallbackQuery, state: FSMContext):
        role = callback.data.split("_", 1)[1]
        if role not in service.ROLES:
            raise service.PersonnelError("نقش غیرمجاز است.")
        await state.update_data(new_srole=role)
        await state.set_state(AdminForm.add_staff_balance)
        await callback.message.edit_text("مانده مرخصی اولیه (روز):")
        await callback.answer()


    @router.message(AdminForm.add_staff_balance)
    async def adm_add_staff_balance(message: Message, state: FSMContext):
        bal = service.balance_value(message.text)
        await state.update_data(new_sbal=bal)
        await state.set_state(AdminForm.add_staff_date)
        await message.answer("📅 تاریخ استخدام را با فرمت <code>YYYY/MM/DD</code> وارد کنید (یا <code>-</code> برای تاریخ امروز):", parse_mode="HTML")


    @router.message(AdminForm.add_staff_date)
    async def adm_add_staff_save(message: Message, state: FSMContext):
        text_date = message.text.strip() if message.text else "-"
        if text_date in ("امروز", "-"):
            emp_date = clock().strftime("%Y/%m/%d")
        else:
            emp_date = service.date_value(text_date)

        data = await state.get_data()
        name, phone, role, bal = data.get("new_sname"), data.get("new_sphone"), data.get("new_srole"), data.get("new_sbal")
    
        with get_connection() as conn:
            service.add(conn,message.from_user.id,name,phone,role,bal,emp_date,clock().strftime("%Y/%m/%d %H:%M"))
        await message.answer(f"✅ پرسنل <b>{html.escape(name)}</b> با موفقیت اضافه شد.",parse_mode="HTML")
        await state.clear()


    @router.callback_query(F.data == "admin_edit_staff_list")
    async def admin_edit_staff_list(callback: CallbackQuery):
        with get_connection() as conn:
            rows = service.active_list(conn,callback.from_user.id)

        if not rows:
            await callback.answer("پرسنل فعالی یافت نشد.", show_alert=True)
            return

        buttons = [[InlineKeyboardButton(text=f"✏️ ویرایش {r[1]}", callback_data=f"editstaff_{r[0]}")] for r in rows]
        buttons.append([InlineKeyboardButton(text="🔙 بازگشت", callback_data="adm_cat_staff")])
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        await callback.message.edit_text("👤 پرسنل مورد نظر جهت ویرایش را انتخاب کنید:", reply_markup=kb)
        await callback.answer()


    @router.callback_query(F.data.startswith("editstaff_"))
    async def admin_edit_staff_options(callback: CallbackQuery, state: FSMContext):
        staff_id = staff_number(callback.data.partition("_")[2])
        with get_connection() as conn:
            service.target(conn,callback.from_user.id,staff_id)
        await state.update_data(edit_staff_id=staff_id)
    
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ ویرایش نام", callback_data="edfield_staff_name")],
            [InlineKeyboardButton(text="📱 ویرایش شماره تماس", callback_data="edfield_phone_number")],
            [InlineKeyboardButton(text="🌿 ویرایش مانده مرخصی", callback_data="edfield_leave_balance")],
            [InlineKeyboardButton(text="📅 ویرایش تاریخ استخدام", callback_data="edfield_employment_date")],
            [InlineKeyboardButton(text="🔙 بازگشت", callback_data="admin_edit_staff_list")]
        ])
        await callback.message.edit_text("⚙️ کدام بخش از اطلاعات این پرسنل را می‌خواهید ویرایش کنید؟", reply_markup=kb)
        await callback.answer()


    @router.callback_query(F.data.startswith("edfield_"))
    async def admin_edit_staff_field_chosen(callback: CallbackQuery, state: FSMContext):
        field = callback.data.split("edfield_")[1]
    
        ALLOWED_FIELDS = {"staff_name", "phone_number", "leave_balance", "employment_date"}
        if field not in ALLOWED_FIELDS:
            await callback.answer("فیلد غیرمجاز است.", show_alert=True)
            return

        await state.update_data(edit_field=field)
        await state.set_state(AdminForm.edit_staff_value)
        await callback.message.edit_text(f"✍️ مقدار جدید برای فیلد <code>{field}</code> را ارسال کنید:", parse_mode="HTML")
        await callback.answer()


    @router.message(AdminForm.edit_staff_value)
    async def admin_edit_staff_save_value(message: Message, state: FSMContext):
        if not message.text:
            await message.answer("❌ مقدار معتبر وارد کنید.")
            return
        new_val = message.text.strip()
        data = await state.get_data()
        staff_id = data.get("edit_staff_id")
        field = data.get("edit_field")

        ALLOWED_FIELDS = {"staff_name", "phone_number", "leave_balance", "employment_date"}
        if field not in ALLOWED_FIELDS:
            await message.answer("❌ فیلد غیرمجاز است.")
            await state.clear()
            return

        with get_connection() as conn:
            service.edit(conn,message.from_user.id,staff_id,field,new_val,clock().strftime("%Y/%m/%d %H:%M"))
        await message.answer("✅ اطلاعات پرسنل با موفقیت ویرایش شد.")
        await state.clear()


    @router.callback_query(F.data == "admin_deactivate_staff_list")
    async def admin_deactivate_list(callback: CallbackQuery):
        with get_connection() as conn:
            rows = service.active_list(conn,callback.from_user.id)

        if not rows:
            await callback.answer("پرسنل فعالی یافت نشد.", show_alert=True)
            return

        buttons = [[InlineKeyboardButton(text=f"🚫 غیرفعال کردن {r[1]}", callback_data=f"deact_{r[0]}")] for r in rows]
        buttons.append([InlineKeyboardButton(text="🔙 بازگشت", callback_data="adm_cat_staff")])
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        await callback.message.edit_text("انتخاب پرسنل جهت غیرفعال‌سازی:", reply_markup=kb)
        await callback.answer()


    @router.callback_query(F.data.startswith("deact_"))
    async def admin_deactivate_execute(callback: CallbackQuery):
        staff_id = staff_number(callback.data.partition("_")[2])
        now_str = clock().strftime("%Y/%m/%d")
        with get_connection() as conn:
            service.deactivate(conn,callback.from_user.id,staff_id,now_str)
        await callback.message.edit_text(f"✅ پرسنل غیرفعال شد. تاریخ تسویه ثبت گردید: <code>{now_str}</code>", reply_markup=None, parse_mode="HTML")
        await callback.answer()

    return router
