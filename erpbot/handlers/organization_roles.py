"""Independent organization Router with explicit application dependencies."""
import html
import logging
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from ..services.organization_admin import admin_staff_id
from ..services import organization_memberships as membership_service
from ..services import organization_roles as role_service
from .organization_callbacks import AdminErrorResponder, valid_callback_number
from ..services.organization_memberships import active_memberships_for_staff
from ..services.organization_roles import RoleError, create_role, set_role_permission, set_role_active, assign_role, revoke_role, staff_unit_roles


class OrganizationRoleForm(StatesGroup):
    waiting_for_role_name = State()


def create_router(connection_factory):
    router = Router(name='organization_roles')
    router.callback_query.middleware(AdminErrorResponder())
    get_connection = connection_factory

    def _orgmem_admin_id(telegram_id):
        with connection_factory() as conn:
            return admin_staff_id(conn, telegram_id)

    @router.callback_query(F.data == 'orgr_menu')
    async def orgr_menu(callback: CallbackQuery, state: FSMContext):
        if _orgmem_admin_id(callback.from_user.id) is None:
            await callback.answer('فقط مدیر اصلی مجاز است.', show_alert=True)
            return
        await state.clear()
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='➕ نقش جدید', callback_data='orgr_new')], [InlineKeyboardButton(text='📋 نقش\u200cها و مجوزها', callback_data='orgr_list')], [InlineKeyboardButton(text='👥 تخصیص نقش واحدی', callback_data='orgr_staff_0')], [InlineKeyboardButton(text='🔙 بازگشت', callback_data='orgunits_menu')]])
        await callback.message.edit_text('🛡️ مدیریت نقش\u200cها و مجوزهای واحدی', reply_markup=kb)
        await callback.answer()

    @router.callback_query(F.data == 'orgr_new')
    async def orgr_new(callback: CallbackQuery, state: FSMContext):
        actor = _orgmem_admin_id(callback.from_user.id)
        if actor is None:
            await callback.answer('فقط مدیر اصلی مجاز است.', show_alert=True)
            return
        await state.update_data(orgr_actor=callback.from_user.id)
        await state.set_state(OrganizationRoleForm.waiting_for_role_name)
        await callback.message.edit_text('نام نقش جدید را بنویسید (مثلاً سرپرست پخش). برای لغو /start را بزنید.')
        await callback.answer()

    @router.message(OrganizationRoleForm.waiting_for_role_name)
    async def orgr_new_save(message: Message, state: FSMContext):
        actor = _orgmem_admin_id(message.from_user.id)
        saved = await state.get_data()
        if actor is None or saved.get('orgr_actor') != message.from_user.id:
            await state.clear()
            await message.answer('نشست مدیریتی معتبر نیست.')
            return
        try:
            with get_connection() as conn:
                role_id = create_role(conn, (message.text or '').strip(), actor_staff_id=actor)
        except RoleError as exc:
            await message.answer(html.escape(str(exc)))
            return
        except Exception:
            logging.exception('Role creation failed')
            await message.answer('خطا در ایجاد نقش.')
            return
        await state.clear()
        await message.answer(f'✅ نقش جدید با شناسه {role_id} ساخته شد. این نقش هنوز هیچ مجوزی ندارد.')

    @router.callback_query(F.data == 'orgr_list')
    async def orgr_list(callback: CallbackQuery):
        if _orgmem_admin_id(callback.from_user.id) is None:
            await callback.answer('فقط مدیر اصلی مجاز است.', show_alert=True)
            return
        with get_connection() as conn:
            rows = role_service.roles_for_admin(conn, callback.from_user.id)
        buttons = [[InlineKeyboardButton(text=('🔒 ' if system else '🛡️ ') + name + (' (غیرفعال)' if not active else ''), callback_data=f'orgr_view_{rid}')] for rid, name, system, active in rows]
        buttons.append([InlineKeyboardButton(text='🔙 بازگشت', callback_data='orgr_menu')])
        await callback.message.edit_text('نقش را انتخاب کنید:', reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        await callback.answer()

    @router.callback_query(F.data.startswith('orgr_view_'))
    async def orgr_view(callback: CallbackQuery):
        if _orgmem_admin_id(callback.from_user.id) is None:
            await callback.answer('فقط مدیر اصلی مجاز است.', show_alert=True)
            return
        raw = (callback.data or '').removeprefix('orgr_view_')
        if not valid_callback_number(raw):
            await callback.answer('شناسه نامعتبر است.', show_alert=True)
            return
        rid = int(raw)
        with get_connection() as conn:
            role = role_service.role_for_admin(conn, callback.from_user.id, rid)
            perms = role_service.descriptions_for_admin(conn, callback.from_user.id, rid)
        if role is None:
            await callback.answer('نقش پیدا نشد.', show_alert=True)
            return
        buttons = []
        if not role[1] and (not role[2]):
            if role[3]:
                buttons.append([InlineKeyboardButton(text='🔑 مدیریت مجوزها', callback_data=f'orgr_perms_{rid}')])
            buttons.append([InlineKeyboardButton(text='🚫 غیرفعال\u200cسازی' if role[3] else '✅ فعال\u200cسازی', callback_data=f'orgr_active_{rid}_{(0 if role[3] else 1)}')])
        buttons.append([InlineKeyboardButton(text='🔙 فهرست نقش\u200cها', callback_data='orgr_list')])
        message = '🛡️ ' + role[0] + (' (سیستمی، فقط مشاهده)' if role[1] or role[2] else '') + '\nمجوزها:\n' + ('\n'.join(('• ' + p[0] for p in perms)) if perms else 'بدون مجوز')
        await callback.message.edit_text(message, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        await callback.answer()

    @router.callback_query(F.data.startswith('orgr_perms_'))
    async def orgr_perms(callback: CallbackQuery):
        if _orgmem_admin_id(callback.from_user.id) is None:
            await callback.answer('فقط مدیر اصلی مجاز است.', show_alert=True)
            return
        raw = (callback.data or '').removeprefix('orgr_perms_')
        if not valid_callback_number(raw):
            await callback.answer('شناسه نامعتبر است.', show_alert=True)
            return
        rid = int(raw)
        with get_connection() as conn:
            role = role_service.flags_for_admin(conn, callback.from_user.id, rid)
            permissions = role_service.permissions_for_admin(conn, callback.from_user.id)
            owned = role_service.owned_for_admin(conn, callback.from_user.id, rid)
        if not role or role[0] or role[1] or (not role[2]):
            await callback.answer('نقش قابل ویرایش نیست.', show_alert=True)
            return
        buttons = [[InlineKeyboardButton(text=('✅ ' if pid in owned else '▫️ ') + desc, callback_data=f'orgr_toggle_{rid}_{pid}_{(0 if pid in owned else 1)}')] for pid, code, desc in permissions]
        buttons.append([InlineKeyboardButton(text='🔙 نقش', callback_data=f'orgr_view_{rid}')])
        await callback.message.edit_text('مجوز را برای فعال/غیرفعال\u200cسازی انتخاب کنید. فقط مجوزهای پیاده\u200cسازی\u200cشده در آینده اثر عملیاتی خواهند داشت:', reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        await callback.answer()

    @router.callback_query(F.data.startswith('orgr_toggle_'))
    async def orgr_toggle(callback: CallbackQuery):
        actor = _orgmem_admin_id(callback.from_user.id)
        if actor is None:
            await callback.answer('فقط مدیر اصلی مجاز است.', show_alert=True)
            return
        args = (callback.data or '').removeprefix('orgr_toggle_').split('_')
        if len(args) != 3 or not all((valid_callback_number(a) for a in args)) or args[2] not in ('0', '1'):
            await callback.answer('شناسه نامعتبر است.', show_alert=True)
            return
        rid, pid, enabled = map(int, args)
        try:
            with get_connection() as conn:
                set_role_permission(conn, rid, pid, bool(enabled), actor_staff_id=actor)
        except RoleError as exc:
            await callback.answer(str(exc), show_alert=True)
            return
        except Exception:
            logging.exception('Role permission failed')
            await callback.answer('خطا در ثبت مجوز.', show_alert=True)
            return
        await callback.answer('مجوز به\u200cروز شد.')
        await callback.message.edit_text('✅ مجوز به\u200cروز شد.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='🔙 مجوزهای نقش', callback_data=f'orgr_perms_{rid}')]]))

    @router.callback_query(F.data.startswith('orgr_active_'))
    async def orgr_active(callback: CallbackQuery):
        actor = _orgmem_admin_id(callback.from_user.id)
        if actor is None:
            await callback.answer('فقط مدیر اصلی مجاز است.', show_alert=True)
            return
        args = (callback.data or '').removeprefix('orgr_active_').split('_')
        if len(args) != 2 or not all((valid_callback_number(x) for x in args)) or args[1] not in ('0', '1'):
            await callback.answer('شناسه نامعتبر است.', show_alert=True)
            return
        rid, active = map(int, args)
        try:
            with get_connection() as conn:
                set_role_active(conn, rid, bool(active), actor_staff_id=actor)
        except RoleError as exc:
            await callback.answer(str(exc), show_alert=True)
            return
        except Exception:
            logging.exception('Role active failed')
            await callback.answer('خطا در تغییر وضعیت.', show_alert=True)
            return
        await callback.answer('وضعیت نقش تغییر کرد.')
        await callback.message.edit_text('✅ وضعیت نقش ثبت شد.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='🔙 فهرست نقش\u200cها', callback_data='orgr_list')]]))

    @router.callback_query(F.data.startswith('orgr_staff_'))
    async def orgr_staff(callback: CallbackQuery):
        if _orgmem_admin_id(callback.from_user.id) is None:
            await callback.answer('فقط مدیر اصلی مجاز است.', show_alert=True)
            return
        raw = (callback.data or '').removeprefix('orgr_staff_')
        if not valid_callback_number(raw):
            await callback.answer('صفحه نامعتبر است.', show_alert=True)
            return
        page = int(raw)
        with get_connection() as conn:
            staff = membership_service.staff_for_admin(conn, callback.from_user.id)
        if page > max(0, (len(staff) - 1) // 8):
            await callback.answer('صفحه نامعتبر است.', show_alert=True)
            return
        buttons = [[InlineKeyboardButton(text=name, callback_data=f'orgr_person_{sid}')] for sid, name in staff[page * 8:(page + 1) * 8]]
        if page:
            buttons.append([InlineKeyboardButton(text='◀️ قبلی', callback_data=f'orgr_staff_{page - 1}')])
        if (page + 1) * 8 < len(staff):
            buttons.append([InlineKeyboardButton(text='بعدی ▶️', callback_data=f'orgr_staff_{page + 1}')])
        buttons.append([InlineKeyboardButton(text='🔙', callback_data='orgr_menu')])
        await callback.message.edit_text('پرسنل را انتخاب کنید:', reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        await callback.answer()

    @router.callback_query(F.data.startswith('orgr_person_'))
    async def orgr_person(callback: CallbackQuery):
        if _orgmem_admin_id(callback.from_user.id) is None:
            await callback.answer('فقط مدیر اصلی مجاز است.', show_alert=True)
            return
        raw = (callback.data or '').removeprefix('orgr_person_')
        if not valid_callback_number(raw):
            await callback.answer('شناسه نامعتبر است.', show_alert=True)
            return
        sid = int(raw)
        with get_connection() as conn:
            name = membership_service.person_for_admin(conn, callback.from_user.id, sid)
            memberships = active_memberships_for_staff(conn, sid) if name else []
        if not name:
            await callback.answer('پرسنل پیدا نشد.', show_alert=True)
            return
        buttons = [[InlineKeyboardButton(text=unit_name, callback_data=f'orgr_unit_{sid}_{uid}')] for uid, unit_name in memberships]
        buttons.append([InlineKeyboardButton(text='🔙', callback_data='orgr_staff_0')])
        await callback.message.edit_text('واحد فعال پرسنل «' + name[0] + '» را انتخاب کنید:', reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        await callback.answer()

    @router.callback_query(F.data.startswith('orgr_unit_'))
    async def orgr_unit(callback: CallbackQuery):
        if _orgmem_admin_id(callback.from_user.id) is None:
            await callback.answer('فقط مدیر اصلی مجاز است.', show_alert=True)
            return
        raw = (callback.data or '').removeprefix('orgr_unit_').split('_')
        if len(raw) != 2 or not all((valid_callback_number(x) for x in raw)):
            await callback.answer('شناسه نامعتبر است.', show_alert=True)
            return
        sid, uid = map(int, raw)
        with get_connection() as conn:
            member = role_service.membership_for_admin(conn, callback.from_user.id, sid, uid)
            assigned = staff_unit_roles(conn, sid, uid)
            roles = role_service.assignable_for_admin(conn, callback.from_user.id)
        if not member:
            await callback.answer('عضویت فعال یافت نشد.', show_alert=True)
            return
        assigned_ids = {r[0] for r in assigned}
        buttons = [[InlineKeyboardButton(text=('🚫 لغو نقش: ' if rid in assigned_ids else '➕ افزودن نقش: ') + name, callback_data=f'orgr_set_{sid}_{uid}_{rid}_{(0 if rid in assigned_ids else 1)}')] for rid, name in roles]
        buttons.append([InlineKeyboardButton(text='🔙', callback_data=f'orgr_person_{sid}')])
        await callback.message.edit_text('نقش\u200cهای محدوده این واحد:\n' + (', '.join((name for _, name in assigned)) or 'بدون نقش') + '\n\nهر تغییر فوراً ثبت می\u200cشود.', reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        await callback.answer()

    @router.callback_query(F.data.startswith('orgr_set_'))
    async def orgr_set(callback: CallbackQuery):
        actor = _orgmem_admin_id(callback.from_user.id)
        if actor is None:
            await callback.answer('فقط مدیر اصلی مجاز است.', show_alert=True)
            return
        raw = (callback.data or '').removeprefix('orgr_set_').split('_')
        if len(raw) != 4 or not all((valid_callback_number(x) for x in raw)) or raw[3] not in ('0', '1'):
            await callback.answer('شناسه نامعتبر است.', show_alert=True)
            return
        sid, uid, rid, enable = map(int, raw)
        try:
            with get_connection() as conn:
                if enable:
                    assign_role(conn, sid, uid, rid, actor_staff_id=actor)
                else:
                    revoke_role(conn, sid, uid, rid, actor_staff_id=actor)
        except RoleError as exc:
            await callback.answer(str(exc), show_alert=True)
            return
        except Exception:
            logging.exception('Scoped role assignment failed')
            await callback.answer('خطا در ثبت نقش.', show_alert=True)
            return
        await callback.answer('تغییر نقش ثبت شد.')
        await callback.message.edit_text('✅ تغییر نقش ثبت شد.', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='🔙 نقش\u200cهای همین واحد', callback_data=f'orgr_unit_{sid}_{uid}')]]))

    return router
