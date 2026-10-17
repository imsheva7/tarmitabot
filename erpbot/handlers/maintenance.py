"""Private administrative maintenance with one-use, expiring confirmation."""
import asyncio
import logging
import secrets
import sqlite3
import time
from aiogram import Router,F,BaseMiddleware
from aiogram.types import CallbackQuery,InlineKeyboardButton,InlineKeyboardMarkup,FSInputFile
from aiogram.fsm.context import FSMContext
from ..services import maintenance as service


class MaintenanceAccess(BaseMiddleware):
    def __init__(self,get_connection):
        self.get_connection=get_connection

    async def __call__(self,handler,event,data):
        try:
            if event.message is None or event.message.chat.type!='private':
                raise service.MaintenanceError('پاکسازی را فقط در چت خصوصی ربات انجام دهید.')
            with self.get_connection() as conn:
                service.require_admin(conn,event.from_user.id)
            return await handler(event,data)
        except (service.MaintenanceError,service.PersonnelError) as exc:
            await event.answer(str(exc),show_alert=True)
        except sqlite3.Error as exc:
            logging.error('Maintenance access or preview failed: %s',type(exc).__name__)
            await event.answer('خطا در بررسی پاکسازی؛ دوباره تلاش کنید.',show_alert=True)


def back_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text='🔙 بازگشت به پنل مدیریت',callback_data='admin_panel')]])


def create_router(get_connection,database_path,clock,*,monotonic=time.monotonic):
    router=Router(name='maintenance')
    router.callback_query.middleware(MaintenanceAccess(get_connection))
    lock=asyncio.Lock()

    @router.callback_query(F.data=='admin_selective_reset_menu')
    async def admin_selective_reset_menu(callback: CallbackQuery,state: FSMContext):
        await state.clear()
        buttons=[[InlineKeyboardButton(text=title,callback_data=f'confreset_{target}')]
                 for target,title in service.TITLES.items()]
        buttons.extend(back_keyboard().inline_keyboard)
        await callback.message.edit_text('⚙️ پاکسازی انتخابی دیتابیس\nبخش مورد نظر را انتخاب کنید. ارسال موفق پشتیبان پیش از پاکسازی الزامی است.',
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        await callback.answer()

    @router.callback_query(F.data.startswith('confreset_'))
    async def admin_confirm_reset_prompt(callback: CallbackQuery,state: FSMContext):
        target=(callback.data or '').partition('_')[2]
        with get_connection() as conn:
            counts=service.preview(conn,callback.from_user.id,target)
        nonce=secrets.token_urlsafe(12)
        await state.clear()
        await state.update_data(maintenance_target=target,maintenance_nonce=nonce,
            maintenance_actor=callback.from_user.id,maintenance_expires=monotonic()+300)
        keyboard=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text='✅ تأیید نهایی و تهیه پشتیبان',callback_data=f'doreset_{target}:{nonce}'),
            InlineKeyboardButton(text='❌ انصراف',callback_data='admin_selective_reset_menu')]])
        detail='\n'.join(f'{table}: {count}' for table,count in counts.items())
        text=f'⚠️ {service.TITLES[target]}\n\n{detail}\n\nاین تأیید فقط یک بار و تا ۵ دقیقه معتبر است.'
        if target=='all_except_staff':
            text+='\nپرسنل، مانده فعلی، واحدها، مجوزها و یادآورها حفظ می‌شوند؛ برای مانده‌های غیرصفر سند افتتاحیه ثبت می‌شود.'
        await callback.message.edit_text(text,reply_markup=keyboard)
        await callback.answer()

    @router.callback_query(F.data.startswith('doreset_'))
    async def admin_execute_selective_reset(callback: CallbackQuery,state: FSMContext):
        async with lock:
            target,separator,nonce=(callback.data or '').partition('_')[2].partition(':')
            data=await state.get_data()
            valid=(separator and nonce and target==data.get('maintenance_target')
                   and callback.from_user.id==data.get('maintenance_actor')
                   and isinstance(data.get('maintenance_nonce'),str)
                   and secrets.compare_digest(nonce.encode(),data['maintenance_nonce'].encode())
                   and isinstance(data.get('maintenance_expires'),(int,float))
                   and monotonic()<data['maintenance_expires'])
            if not valid:
                await callback.answer('تأیید قدیمی، منقضی یا نامعتبر است؛ دوباره بخش پاکسازی را انتخاب کنید.',show_alert=True)
                return
            service.validate_target(target)
            await state.clear()
            await state.update_data(maintenance_running=nonce)
            committed=False
            try:
                await callback.answer('در حال تهیه و ارسال پشتیبان…')
                with service.prepared_backup(get_connection,database_path,callback.from_user.id) as (path,digest):
                    await callback.message.answer_document(FSInputFile(path,filename='erpbot_before_reset.sqlite3'),
                        caption='📦 پشتیبان پیش از پاکسازی؛ آن را برای بازیابی نگه دارید.')
                    if (await state.get_data()).get('maintenance_running')!=nonce:
                        raise service.MaintenanceError('عملیات لغو شده یا فرم تغییر کرده است؛ پاکسازی انجام نشد.')
                    with get_connection() as conn:
                        service.execute(conn,callback.from_user.id,target,digest,clock().strftime('%Y/%m/%d %H:%M'))
                    committed=True
            except (service.MaintenanceError,service.PersonnelError) as exc:
                await callback.message.answer(str(exc),reply_markup=back_keyboard())
                return
            except Exception as exc:
                logging.error('Maintenance failed (%s): %s','after commit' if committed else 'before commit',type(exc).__name__)
                if not committed:
                    await callback.message.answer('❌ تهیه/ارسال پشتیبان یا پاکسازی ناموفق بود؛ عملیات را دوباره از منو شروع کنید.',reply_markup=back_keyboard())
                    return
            finally:
                if (await state.get_data()).get('maintenance_running')==nonce:
                    await state.clear()
            try:
                await callback.message.edit_text('✅ پاکسازی انتخاب‌شده ثبت شد.',reply_markup=back_keyboard())
            except Exception as exc:
                logging.error('Maintenance committed; UI update failed: %s',type(exc).__name__)
                await callback.message.answer('✅ پاکسازی ثبت شد؛ به‌روزرسانی پیام قبلی ناموفق بود.',reply_markup=back_keyboard())

    return router
