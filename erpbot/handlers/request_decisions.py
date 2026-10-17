"""Shared request callbacks; commit decisions before Telegram notifications."""
import html
import logging
import re
import sqlite3
from aiogram import Router, F, BaseMiddleware
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from ..services import request_decisions as service
from .organization_callbacks import callback_number
from .leave_filters import LeaveDecisionFilter, LeaveRejectionFilter, LeaveCancellationFilter
from .asset_filters import AssetApprovalFilter
from .finance_filters import FinanceDecisionFilter
from .mission_filters import MissionApprovalFilter

MESSAGES={'not_found':'❌ درخواست پیدا نشد.',
          'invalid_type':'برای این درخواست از دکمه درخواست اصلی استفاده کنید.',
          'already_processed':'این درخواست قبلاً تعیین تکلیف شده است.',
          'replacement_pending':'جانشین هنوز درخواست را تأیید نکرده است.',
          'cannot_cancel':'امکان لغو این درخواست وجود ندارد.'}


class AdminForm(StatesGroup):
    rejection_reason=State()


class DecisionErrors(BaseMiddleware):
    async def __call__(self,handler,event,data):
        try:
            return await handler(event,data)
        except (service.DecisionError,service.PersonnelError) as exc:
            text=str(exc)
        except sqlite3.Error as exc:
            logging.error('Shared request decision failed: %s',type(exc).__name__)
            text='خطا در پردازش درخواست؛ دوباره بررسی کنید.'
        if isinstance(event,CallbackQuery):
            await event.answer(text,show_alert=True)
        else:
            await event.answer(text)


async def attempt(operation):
    try:
        await operation
    except Exception as exc:
        logging.error('Request notification failed: %s',type(exc).__name__)


async def edit_result(message, suffix):
    if message is None:
        return
    if message.photo:
        await attempt(message.edit_caption(caption=html.escape(message.caption or '')+'\n\n'+suffix,
                                           reply_markup=None,parse_mode='HTML'))
    else:
        await attempt(message.edit_text(html.escape(message.text or '')+'\n\n'+suffix,
                                        reply_markup=None,parse_mode='HTML'))


def create_router(get_connection,bot):
    router=Router(name='request_decisions')
    errors=DecisionErrors()
    router.callback_query.middleware(errors)
    router.message.middleware(errors)

    @router.callback_query(F.data.startswith('cancel_'), LeaveCancellationFilter(get_connection,include_leave=False))
    async def cancel_request_cb(callback: CallbackQuery):
        code=(callback.data or '').partition('_')[2]
        with get_connection() as conn:
            result=service.cancel(conn,callback.from_user.id,code)
        if result.outcome!='cancelled':
            await callback.answer(MESSAGES['cannot_cancel'],show_alert=True)
            return
        row=result.request
        if row.admin_chat and row.admin_message:
            await attempt(bot.edit_message_text(chat_id=row.admin_chat,message_id=row.admin_message,
                text=f'📩 <b>درخواست ({html.escape(row.code)})</b>\n\n❌ <b>وضعیت: لغو شده توسط پرسنل</b>',
                reply_markup=None,parse_mode='HTML'))
        await edit_result(callback.message,'<b>[این درخواست توسط شما لغو شد]</b>')
        await callback.answer('درخواست لغو شد.')

    @router.callback_query(F.data.startswith('approve_') | F.data.startswith('reject_'),
        LeaveDecisionFilter(get_connection,include_leave=False), AssetApprovalFilter(get_connection,include_assets=False),
        FinanceDecisionFilter(get_connection,include_finance=False), MissionApprovalFilter(get_connection,include_missions=False))
    async def handle_request_decision(callback: CallbackQuery,state: FSMContext):
        action,_,raw=(callback.data or '').partition('_')
        number=callback_number(raw)
        content=(callback.message.text or callback.message.caption or '') if callback.message else ''
        match=re.search(r'(REQ-\d{4}-\d{5})',content)
        fallback=match.group(1) if match else None
        with get_connection() as conn:
            result=(service.approve(conn,callback.from_user.id,number,fallback) if action=='approve'
                    else service.inspect_decision(conn,callback.from_user.id,number,'reject',fallback))
        if result.outcome not in ('approved','ready'):
            await callback.answer(MESSAGES[result.outcome],show_alert=True)
            return
        row=result.request
        if action=='reject':
            await state.update_data(rejecting_req_id=row.id)
            await state.set_state(AdminForm.rejection_reason)
            await callback.message.answer('❌ لطفاً <b>دلیل رد درخواست</b> را بنویسید:',parse_mode='HTML')
            await callback.answer()
            return
        await edit_result(callback.message,'✅ تأیید شده قطعی (توسط مدیر اصلی)')
        await attempt(bot.send_message(chat_id=row.owner,
            text=f'📄 وضعیت درخواست ({html.escape(row.code)}): <b>✅ تأیید شده قطعی</b>',parse_mode='HTML'))
        await callback.answer('تایید نهایی با موفقیت ثبت شد.')

    @router.message(AdminForm.rejection_reason, LeaveRejectionFilter(get_connection,include_leave=False))
    async def save_rejection_reason(message: Message,state: FSMContext):
        data=await state.get_data()
        with get_connection() as conn:
            result=service.reject(conn,message.from_user.id,data.get('rejecting_req_id'),message.text)
        if result.outcome!='rejected':
            await state.clear()
            await message.answer(MESSAGES[result.outcome])
            return
        row=result.request
        await state.clear()
        await message.answer('✅ درخواست رد شد و دلیل آن برای کاربر ارسال می‌شود.')
        reason=html.escape(message.text.strip())
        code=html.escape(row.code)
        await attempt(bot.send_message(chat_id=row.owner,
            text=f'❌ <b>درخواست شما ({code}) رد شد.</b>\n\n📝 <b>دلیل رد توسط مدیر اصلی:</b>\n{reason}',parse_mode='HTML'))
        if row.admin_chat and row.admin_message:
            await attempt(bot.edit_message_text(chat_id=row.admin_chat,message_id=row.admin_message,
                text=f'📩 <b>درخواست ({code})</b>\n\n❌ <b>وضعیت: رد شده</b>\n📝 دلیل: {reason}',
                reply_markup=None,parse_mode='HTML'))

    return router
