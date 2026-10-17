"""Organization management transport with explicitly supplied connections."""
import html
import logging
import sqlite3

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from ..services import organization_units as units
from .organization_callbacks import callback_number as _callback_number


class OrganizationUnitForm(StatesGroup):
    # Preserve the existing state name, including sessions already in progress.
    waiting_for_name = State()


def create_router(connection_factory):
    router = Router(name="organization_units")

    def is_admin(telegram_id):
        with connection_factory() as conn:
            return units.can_manage_units(conn, telegram_id)

    async def check_callback(callback):
        if not is_admin(callback.from_user.id):
            await callback.answer("فقط مدیر اصلی مجاز است.", show_alert=True)
            return False
        return True

    @router.callback_query(F.data == "orgunits_menu")
    async def orgunits_menu(callback: CallbackQuery, state: FSMContext):
        if not await check_callback(callback):
            return
        await state.clear()
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🗂️ مشاهده چارت سازمانی", callback_data="orgunits_chart")],
            [InlineKeyboardButton(text="👥 مدیریت عضویت پرسنل", callback_data="orgmem_staff_0")],
            [InlineKeyboardButton(text="🛡️ نقش‌ها و مجوزهای واحدی", callback_data="orgr_menu")],
            [InlineKeyboardButton(text="📋 اعضای هر واحد", callback_data="orgmem_units_0")],
            [InlineKeyboardButton(text="➕ ایجاد واحد یا زیرمجموعه", callback_data="orgunits_choose_0")],
            [InlineKeyboardButton(text="🔙 بازگشت به مدیریت پرسنل", callback_data="adm_cat_staff")],
        ])
        await callback.message.edit_text("🏢 مدیریت واحدها و زیرمجموعه‌های سازمانی", reply_markup=kb)
        await callback.answer()

    @router.callback_query(F.data == "orgunits_chart")
    async def orgunits_chart(callback: CallbackQuery):
        if not await check_callback(callback):
            return
        try:
            with connection_factory() as conn:
                content = units.chart_for_admin(conn, callback.from_user.id)
        except units.OrganizationUnitPermissionError:
            await callback.answer("فقط مدیر اصلی مجاز است.", show_alert=True)
            return
        messages, current = [], "🏢 چارت سازمانی:\n\n"
        for line in content.splitlines():
            if len(current) + len(line) + 1 > 3500:
                messages.append(current)
                current = ""
            current += line + "\n"
        if current:
            messages.append(current)
        for message_text in messages:
            await callback.message.answer(message_text)
        await callback.answer()

    @router.callback_query(F.data.startswith("orgunits_choose_"))
    async def orgunits_choose_parent(callback: CallbackQuery):
        if not await check_callback(callback):
            return
        page = _callback_number((callback.data or "").removeprefix("orgunits_choose_"))
        if page is None:
            await callback.answer("صفحه نامعتبر است.", show_alert=True)
            return
        try:
            with connection_factory() as conn:
                rows = units.active_units_for_admin(conn, callback.from_user.id)
        except units.OrganizationUnitPermissionError:
            await callback.answer("فقط مدیر اصلی مجاز است.", show_alert=True)
            return
        per_page = 8
        if page > max(0, (len(rows) - 1) // per_page):
            await callback.answer("صفحه نامعتبر است.", show_alert=True)
            return
        selected = rows[page * per_page:(page + 1) * per_page]
        buttons = [[InlineKeyboardButton(text="🏢 واحد اصلی (بدون بالادست)", callback_data="orgunits_pick_root")]]
        buttons += [[InlineKeyboardButton(text=f"↳ {row[1]}", callback_data=f"orgunits_pick_{row[0]}")]
                    for row in selected]
        pagination = []
        if page > 0:
            pagination.append(InlineKeyboardButton(text="◀️ قبلی", callback_data=f"orgunits_choose_{page-1}"))
        if (page + 1) * per_page < len(rows):
            pagination.append(InlineKeyboardButton(text="بعدی ▶️", callback_data=f"orgunits_choose_{page+1}"))
        if pagination:
            buttons.append(pagination)
        buttons.append([InlineKeyboardButton(text="🔙 بازگشت", callback_data="orgunits_menu")])
        await callback.message.edit_text(
            "واحد بالادستی را انتخاب کنید. برای واحد مستقل، «واحد اصلی» را بزنید.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("orgunits_pick_"))
    async def orgunits_pick_parent(callback: CallbackQuery, state: FSMContext):
        if not await check_callback(callback):
            return
        raw = (callback.data or "").removeprefix("orgunits_pick_")
        if raw == "root":
            parent_id, parent_label = None, "واحد اصلی"
        else:
            parent_id = _callback_number(raw)
            if parent_id is None:
                await callback.answer("شناسه نامعتبر است.", show_alert=True)
                return
            try:
                with connection_factory() as conn:
                    parent_label = units.parent_name_for_admin(conn, callback.from_user.id, parent_id)
            except units.OrganizationUnitPermissionError:
                await callback.answer("فقط مدیر اصلی مجاز است.", show_alert=True)
                return
            if parent_label is None:
                await callback.answer("واحد بالادستی غیرفعال یا حذف شده است.", show_alert=True)
                return
        await state.update_data(orgunits_parent_id=parent_id, orgunits_admin_id=callback.from_user.id)
        await state.set_state(OrganizationUnitForm.waiting_for_name)
        await callback.message.edit_text(
            f"✍️ نام واحد جدید را ارسال کنید.\nبالادست: {html.escape(parent_label)}\n\nبرای انصراف /start را بزنید.",
            parse_mode="HTML",
        )
        await callback.answer()

    @router.message(OrganizationUnitForm.waiting_for_name)
    async def orgunits_save_name(message: Message, state: FSMContext):
        if not is_admin(message.from_user.id):
            await state.clear()
            await message.answer("فقط مدیر اصلی مجاز به ایجاد واحد است.")
            return
        saved = await state.get_data()
        if saved.get("orgunits_admin_id") != message.from_user.id:
            await state.clear()
            await message.answer("نشست مدیریتی نامعتبر است.")
            return
        name = message.text.strip() if message.text else ""
        if not name:
            await message.answer("نام واحد را به‌صورت متن ارسال کنید.")
            return
        try:
            with connection_factory() as conn:
                new_id = units.create_unit_for_admin(
                    conn, message.from_user.id, name, saved.get("orgunits_parent_id")
                )
        except units.OrganizationUnitError as exc:
            await message.answer(f"❌ {html.escape(str(exc))}", parse_mode="HTML")
            return
        except sqlite3.IntegrityError:
            logging.exception("Organization unit unique/foreign key constraint")
            await message.answer("❌ این واحد یا کد آن قبلاً ثبت شده است.")
            return
        except Exception:
            logging.exception("Organization unit creation failed")
            await message.answer("❌ خطا در ثبت واحد؛ دوباره تلاش کنید.")
            return
        await state.clear()
        await message.answer(f"✅ واحد «{html.escape(name)}» با شناسه {new_id} ثبت شد.", parse_mode="HTML")

    return router
