"""Independent organization Router with explicit application dependencies."""
import logging
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from ..services.organization_admin import admin_staff_id
from ..services import organization_memberships as membership_service
from .organization_callbacks import AdminErrorResponder, valid_callback_number
from ..services.organization_memberships import add_membership, deactivate_membership, active_memberships_for_staff, active_members_of_unit, MembershipError


def create_router(connection_factory):
    router = Router(name='organization_memberships')
    router.callback_query.middleware(AdminErrorResponder())
    get_connection = connection_factory

    def _orgmem_admin_id(telegram_id):
        with connection_factory() as conn:
            return admin_staff_id(conn, telegram_id)

    @router.callback_query(F.data.startswith('orgmem_staff_'))
    async def orgmem_staff_list(callback: CallbackQuery):
        if _orgmem_admin_id(callback.from_user.id) is None:
            await callback.answer('فقط مدیر اصلی مجاز است.', show_alert=True)
            return
        raw = (callback.data or '').removeprefix('orgmem_staff_')
        if not valid_callback_number(raw):
            await callback.answer('صفحه نامعتبر است.', show_alert=True)
            return
        page = int(raw)
        with get_connection() as conn:
            staff = membership_service.staff_for_admin(conn, callback.from_user.id)
        per_page = 8
        if page > max(0, (len(staff) - 1) // per_page):
            await callback.answer('صفحه نامعتبر است.', show_alert=True)
            return
        buttons = [[InlineKeyboardButton(text=name, callback_data=f'orgmem_person_{staff_id}')] for staff_id, name in staff[page * per_page:(page + 1) * per_page]]
        if page > 0:
            buttons.append([InlineKeyboardButton(text='◀️ قبلی', callback_data=f'orgmem_staff_{page - 1}')])
        if (page + 1) * per_page < len(staff):
            buttons.append([InlineKeyboardButton(text='بعدی ▶️', callback_data=f'orgmem_staff_{page + 1}')])
        buttons.append([InlineKeyboardButton(text='🔙 بازگشت', callback_data='orgunits_menu')])
        await callback.message.edit_text('👥 پرسنل را انتخاب کنید:', reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        await callback.answer()

    @router.callback_query(F.data.startswith('orgmem_person_'))
    async def orgmem_person(callback: CallbackQuery):
        if _orgmem_admin_id(callback.from_user.id) is None:
            await callback.answer('فقط مدیر اصلی مجاز است.', show_alert=True)
            return
        raw = (callback.data or '').removeprefix('orgmem_person_')
        if not valid_callback_number(raw):
            await callback.answer('شناسه نامعتبر است.', show_alert=True)
            return
        staff_id = int(raw)
        with get_connection() as conn:
            person = membership_service.person_for_admin(conn, callback.from_user.id, staff_id)
            memberships = active_memberships_for_staff(conn, staff_id) if person else []
        if person is None:
            await callback.answer('پرسنل فعال یافت نشد.', show_alert=True)
            return
        buttons = [[InlineKeyboardButton(text='➕ عضویت در واحد جدید', callback_data=f'orgmem_addunits_{staff_id}_0')]]
        buttons += [[InlineKeyboardButton(text=f'🚫 لغو عضویت: {name}', callback_data=f'orgmem_confirm_{staff_id}_{unit_id}')] for unit_id, name in memberships]
        buttons.append([InlineKeyboardButton(text='🔙 فهرست پرسنل', callback_data='orgmem_staff_0')])
        info = '، '.join((name for _, name in memberships)) or 'بدون عضویت'
        await callback.message.edit_text(f'👤 {person[0]}\nواحدهای فعلی: {info}', reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        await callback.answer()

    @router.callback_query(F.data.startswith('orgmem_addunits_'))
    async def orgmem_choose_unit(callback: CallbackQuery):
        if _orgmem_admin_id(callback.from_user.id) is None:
            await callback.answer('فقط مدیر اصلی مجاز است.', show_alert=True)
            return
        raw = (callback.data or '').removeprefix('orgmem_addunits_').split('_')
        if len(raw) != 2 or not all((valid_callback_number(x) for x in raw)):
            await callback.answer('شناسه نامعتبر است.', show_alert=True)
            return
        staff_id, page = map(int, raw)
        with get_connection() as conn:
            staff = membership_service.staff_exists_for_admin(conn, callback.from_user.id, staff_id)
            rows = membership_service.units_for_admin(conn, callback.from_user.id)
            existing = {r[0] for r in active_memberships_for_staff(conn, staff_id)}
        if not staff:
            await callback.answer('پرسنل فعال یافت نشد.', show_alert=True)
            return
        rows = [r for r in rows if r[0] not in existing]
        per_page = 8
        if page > max(0, (len(rows) - 1) // per_page):
            await callback.answer('صفحه نامعتبر است.', show_alert=True)
            return
        buttons = [[InlineKeyboardButton(text=name, callback_data=f'orgmem_join_{staff_id}_{unit_id}')] for unit_id, name, _ in rows[page * per_page:(page + 1) * per_page]]
        if page > 0:
            buttons.append([InlineKeyboardButton(text='◀️ قبلی', callback_data=f'orgmem_addunits_{staff_id}_{page - 1}')])
        if (page + 1) * per_page < len(rows):
            buttons.append([InlineKeyboardButton(text='بعدی ▶️', callback_data=f'orgmem_addunits_{staff_id}_{page + 1}')])
        buttons.append([InlineKeyboardButton(text='🔙 بازگشت', callback_data=f'orgmem_person_{staff_id}')])
        await callback.message.edit_text('واحد جدید را انتخاب کنید (عضویت\u200cهای قبلی حفظ می\u200cشوند):', reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        await callback.answer()

    @router.callback_query(F.data.startswith('orgmem_join_'))
    async def orgmem_join(callback: CallbackQuery):
        actor_id = _orgmem_admin_id(callback.from_user.id)
        if actor_id is None:
            await callback.answer('فقط مدیر اصلی مجاز است.', show_alert=True)
            return
        raw = (callback.data or '').removeprefix('orgmem_join_').split('_')
        if len(raw) != 2 or not all((valid_callback_number(x) for x in raw)):
            await callback.answer('شناسه نامعتبر است.', show_alert=True)
            return
        staff_id, unit_id = map(int, raw)
        try:
            with get_connection() as conn:
                add_membership(conn, staff_id, unit_id, actor_staff_id=actor_id)
        except MembershipError as exc:
            await callback.answer(str(exc), show_alert=True)
            return
        except Exception:
            logging.exception('Membership add failed')
            await callback.answer('خطا در ثبت عضویت.', show_alert=True)
            return
        await callback.answer('عضویت ثبت شد.')
        await callback.message.edit_text('✅ عضویت ثبت شد. برای مشاهده واحدهای فرد، بازگشت را بزنید.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='🔙 مشاهده پرسنل', callback_data=f'orgmem_person_{staff_id}')]]))

    @router.callback_query(F.data.startswith('orgmem_confirm_'))
    async def orgmem_confirm_remove(callback: CallbackQuery):
        if _orgmem_admin_id(callback.from_user.id) is None:
            await callback.answer('فقط مدیر اصلی مجاز است.', show_alert=True)
            return
        raw = (callback.data or '').removeprefix('orgmem_confirm_').split('_')
        if len(raw) != 2 or not all((valid_callback_number(x) for x in raw)):
            await callback.answer('شناسه نامعتبر است.', show_alert=True)
            return
        staff_id, unit_id = map(int, raw)
        with get_connection() as conn:
            person = membership_service.removal_person_for_admin(conn, callback.from_user.id, staff_id)
            unit = membership_service.removal_unit_for_admin(conn, callback.from_user.id, unit_id)
            active = membership_service.removal_membership_for_admin(conn, callback.from_user.id, staff_id, unit_id)
        if not person or not unit or (not active):
            await callback.answer('عضویت فعال یافت نشد.', show_alert=True)
            return
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='✅ بله، لغو عضویت', callback_data=f'orgmem_remove_{staff_id}_{unit_id}')], [InlineKeyboardButton(text='❌ انصراف', callback_data=f'orgmem_person_{staff_id}')]])
        await callback.message.edit_text(f'لغو عضویت «{person[0]}» از «{unit[0]}»؟\nنقش\u200cهای محدوده همین واحد نیز غیرفعال خواهند شد.', reply_markup=kb)
        await callback.answer()

    @router.callback_query(F.data.startswith('orgmem_remove_'))
    async def orgmem_remove(callback: CallbackQuery):
        actor_id = _orgmem_admin_id(callback.from_user.id)
        if actor_id is None:
            await callback.answer('فقط مدیر اصلی مجاز است.', show_alert=True)
            return
        raw = (callback.data or '').removeprefix('orgmem_remove_').split('_')
        if len(raw) != 2 or not all((valid_callback_number(x) for x in raw)):
            await callback.answer('شناسه نامعتبر است.', show_alert=True)
            return
        staff_id, unit_id = map(int, raw)
        try:
            with get_connection() as conn:
                deactivate_membership(conn, staff_id, unit_id, actor_staff_id=actor_id)
        except MembershipError as exc:
            await callback.answer(str(exc), show_alert=True)
            return
        except Exception:
            logging.exception('Membership remove failed')
            await callback.answer('خطا در لغو عضویت.', show_alert=True)
            return
        await callback.answer('عضویت غیرفعال شد.')
        await callback.message.edit_text('✅ عضویت غیرفعال شد؛ سابقه حفظ شده است.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='🔙 مشاهده پرسنل', callback_data=f'orgmem_person_{staff_id}')]]))

    @router.callback_query(F.data.startswith('orgmem_units_'))
    async def orgmem_unit_list(callback: CallbackQuery):
        if _orgmem_admin_id(callback.from_user.id) is None:
            await callback.answer('فقط مدیر اصلی مجاز است.', show_alert=True)
            return
        raw = (callback.data or '').removeprefix('orgmem_units_')
        if not valid_callback_number(raw):
            await callback.answer('صفحه نامعتبر است.', show_alert=True)
            return
        page = int(raw)
        with get_connection() as conn:
            units = membership_service.units_for_admin(conn, callback.from_user.id)
        per_page = 8
        if page > max(0, (len(units) - 1) // per_page):
            await callback.answer('صفحه نامعتبر است.', show_alert=True)
            return
        buttons = [[InlineKeyboardButton(text=name, callback_data=f'orgmem_unit_{unit_id}')] for unit_id, name, _ in units[page * per_page:(page + 1) * per_page]]
        if page > 0:
            buttons.append([InlineKeyboardButton(text='◀️ قبلی', callback_data=f'orgmem_units_{page - 1}')])
        if (page + 1) * per_page < len(units):
            buttons.append([InlineKeyboardButton(text='بعدی ▶️', callback_data=f'orgmem_units_{page + 1}')])
        buttons.append([InlineKeyboardButton(text='🔙 بازگشت', callback_data='orgunits_menu')])
        await callback.message.edit_text('📋 واحد را برای مشاهده اعضا انتخاب کنید:', reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        await callback.answer()

    @router.callback_query(F.data.startswith('orgmem_unit_'))
    async def orgmem_unit_members(callback: CallbackQuery):
        if _orgmem_admin_id(callback.from_user.id) is None:
            await callback.answer('فقط مدیر اصلی مجاز است.', show_alert=True)
            return
        raw = (callback.data or '').removeprefix('orgmem_unit_')
        if not valid_callback_number(raw):
            await callback.answer('شناسه نامعتبر است.', show_alert=True)
            return
        unit_id = int(raw)
        with get_connection() as conn:
            unit = membership_service.active_unit_for_admin(conn, callback.from_user.id, unit_id)
            members = active_members_of_unit(conn, unit_id) if unit else []
        if unit is None:
            await callback.answer('واحد فعال پیدا نشد.', show_alert=True)
            return
        text = '📋 اعضای «' + unit[0] + '»:\n' + ('\n'.join(('• ' + name for _, name in members)) if members else 'هنوز عضوی ندارد.')
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='🔙 بازگشت', callback_data='orgmem_units_0')]]))
        await callback.answer()

    @router.message(Command('myunits'))
    async def my_organization_units(message: Message):
        if message.chat.type != 'private':
            return
        with get_connection() as conn:
            memberships = membership_service.memberships_for_user(conn, message.from_user.id)
        if memberships is None:
            await message.answer('حساب پرسنلی فعال یافت نشد.')
            return
        text = '🏢 واحدهای سازمانی من:\n' + ('\n'.join(('• ' + name for _, name in memberships)) if memberships else 'هنوز عضو واحدی نیستید.')
        await message.answer(text)

    return router
