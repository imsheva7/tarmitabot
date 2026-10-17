"""Staff directory transport. Construct a router with an explicit connection factory."""
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from ..services.staff_directory import directory_for_user, visible_units_for_user


def create_router(connection_factory):
    router = Router(name="unit_staff")

    def units_keyboard(allowed):
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=name[:60], callback_data=f"unitstaff_view_{unit_id}")]
            for unit_id, name in allowed
        ])

    @router.message(Command("unitstaff"))
    async def scoped_unit_staff_command(message: Message):
        if message.chat.type != "private":
            return
        with connection_factory() as conn:
            allowed = visible_units_for_user(conn, message.from_user.id)
        if allowed is None:
            await message.answer("حساب پرسنلی فعال یافت نشد.")
            return
        if not allowed:
            await message.answer("مجوز مشاهده پرسنل هیچ واحدی به شما اختصاص داده نشده است.")
            return
        await message.answer("واحد مجاز برای مشاهده پرسنل را انتخاب کنید:",
                             reply_markup=units_keyboard(allowed))

    @router.callback_query(F.data.startswith("unitstaff_view_"))
    async def scoped_unit_staff_view(callback: CallbackQuery):
        if callback.message.chat.type != "private":
            await callback.answer("فقط گفت‌وگوی خصوصی مجاز است.", show_alert=True)
            return
        raw = callback.data.removeprefix("unitstaff_view_")
        if not raw.isascii() or not raw.isdecimal() or len(raw) > 10 or int(raw) == 0:
            await callback.answer("شناسه نامعتبر است.", show_alert=True)
            return
        with connection_factory() as conn:
            result = directory_for_user(conn, callback.from_user.id, int(raw))
        if result.outcome == "denied":
            await callback.answer("مجوز مشاهده پرسنل این واحد را ندارید.", show_alert=True)
            return
        if result.outcome == "unit_not_found":
            await callback.answer("واحد فعال پیدا نشد.", show_alert=True)
            return
        lines = ["👥 پرسنل واحد «" + result.unit_name + "»: "]
        lines.extend("• " + name for name in result.member_names)
        if not result.member_names:
            lines.append("هنوز عضو فعالی ندارد.")
        content = "\n".join(lines)
        if len(content) > 3800:
            content = content[:3750] + "\n… فهرست طولانی است."
        await callback.message.edit_text(content, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 بازگشت", callback_data="unitstaff_back")]
        ]))
        await callback.answer()

    @router.callback_query(F.data == "unitstaff_back")
    async def scoped_unit_staff_back(callback: CallbackQuery):
        if callback.message.chat.type != "private":
            await callback.answer("فقط گفت‌وگوی خصوصی مجاز است.", show_alert=True)
            return
        with connection_factory() as conn:
            allowed = visible_units_for_user(conn, callback.from_user.id)
        if not allowed:
            await callback.message.edit_text("مجوز مشاهده پرسنل هیچ واحدی به شما اختصاص داده نشده است.")
        else:
            await callback.message.edit_text("واحد مجاز برای مشاهده پرسنل را انتخاب کنید:",
                                            reply_markup=units_keyboard(allowed))
        await callback.answer()

    return router
