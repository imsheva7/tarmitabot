"""Financial approval and completion notifications after committed server decisions."""
import html
import logging
from aiogram import Router,F
from aiogram.types import CallbackQuery,InlineKeyboardButton,InlineKeyboardMarkup
from ..services import finance as service
from .finance_forms import FinanceAccess
from .finance_filters import FinanceDecisionFilter
from .organization_callbacks import callback_number


def create_router(get_connection, bot, group_id, decrypt_data):
    router=Router(name='finance_decisions')
    router.callback_query.middleware(FinanceAccess(get_connection))

    async def notify(**kwargs):
        try:
            await bot.send_message(**kwargs)
            return True
        except Exception as exc:
            logging.error('Financial notification failed: %s',type(exc).__name__)
            return False

    @router.callback_query(F.data.startswith('approve_') | F.data.startswith('paid_') | F.data.startswith('bought_'), FinanceDecisionFilter(get_connection))
    async def financial_decision(callback: CallbackQuery):
        action,_,raw=(callback.data or '').partition('_')
        request_id=callback_number(raw)
        if request_id is None or request_id<=0:
            raise service.FinanceError('شناسه درخواست نامعتبر است.')
        try:
            with get_connection() as conn:
                result=service.decide(conn,callback.from_user.id,request_id,action)
        except service.FinanceError:
            raise
        except Exception as exc:
            logging.error('Financial decision failed: %s',type(exc).__name__)
            await callback.answer('خطا در پردازش درخواست؛ تغییری ثبت نشد.',show_alert=True)
            return
        if result.outcome not in ('approve','paid','bought'):
            messages={'not_found':'درخواست پیدا نشد.','invalid_type':'نوع درخواست با این عملیات سازگار نیست.',
                'already_processed':'درخواست در وضعیت مجاز این عملیات نیست یا قبلاً پردازش شده است.',
                'replacement_pending':'جانشین هنوز درخواست را تأیید نکرده است.'}
            await callback.answer(messages[result.outcome],show_alert=True)
            return
        user_id,name,kind,code,col1,col2,col3,secret,_=result.row
        suffix={'approve':'✅ تأیید شده قطعی (توسط مدیر اصلی)',
                'paid':'✅ وجه پرداخت و تسویه گردید.','bought':'✅ وضعیت به خریداری شده تغییر یافت.'}[action]
        try:
            if callback.message.photo:
                await callback.message.edit_caption(caption=(callback.message.caption or '')+'\n\n'+suffix,reply_markup=None)
            else:
                await callback.message.edit_text((callback.message.text or '')+'\n\n'+suffix,reply_markup=None)
        except Exception as exc:
            logging.error('Could not edit financial decision: %s',type(exc).__name__)
        if action=='paid':
            await notify(chat_id=user_id,text=f'🎉 درخواست {kind} شما پرداخت و تسویه گردید.',parse_mode='HTML')
            await callback.answer('وضعیت پرداخت ثبت شد.')
            return
        if action=='bought':
            await callback.answer('تایید خرید ثبت شد.')
            return
        await notify(chat_id=user_id,text=f'📄 وضعیت درخواست ({code}): <b>✅ تأیید شده قطعی</b>',parse_mode='HTML')
        with get_connection() as conn:
            target=service.recipient(conn,'purchase' if kind=='خرید ملزومات' else 'finance')
        if kind=='خرید ملزومات':
            text=(f'🛒 <b>دستور خرید جدید (ملزومات / انباردیگر)</b>\n\n🔹 <b>کد:</b> {code}\n'
                  f'👤 <b>پرسنل:</b> {html.escape(name)}\n📦 {html.escape(col1)}\n🔢 {html.escape(col2)}\n📝 {html.escape(col3)}')
            keyboard=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text='خریدم 🛒',callback_data=f'bought_{request_id}')]])
            delivered=await notify(chat_id=target or group_id,text=text,reply_markup=keyboard,parse_mode='HTML')
        else:
            if not target:
                await callback.answer('تأیید ثبت شد؛ حساب فعال مالی برای ارسال خصوصی یافت نشد.',show_alert=True)
                return
            try:
                decoded=decrypt_data(secret) if secret else 'ندارد'
                text=(f'💳 <b>دستور پرداخت جدید (واحد مالی)</b>\n\n🔹 <b>کد:</b> {code}\n'
                      f'👤 <b>پرسنل:</b> {html.escape(name)}\n📌 نوع: {kind}\n💵 {html.escape(col1)}\n'
                      f'📝 {html.escape(col2)}\n🔑 <b>اطلاعات مالی/محفوظ:</b> <code>{html.escape(str(decoded))}</code>')
            except Exception as exc:
                logging.error('Could not decode payment details: %s',type(exc).__name__)
                await callback.answer('تأیید ثبت شد؛ خواندن اطلاعات مالی ناموفق بود.',show_alert=True)
                return
            keyboard=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text='پرداخت شد 💳',callback_data=f'paid_{request_id}')]])
            delivered=await notify(chat_id=target,text=text,reply_markup=keyboard,parse_mode='HTML')
        await callback.answer('تایید نهایی با موفقیت ثبت شد.' if delivered else 'تأیید ثبت شد؛ ارسال دستور به مسئول مربوط ناموفق بود.',show_alert=not delivered)

    return router
