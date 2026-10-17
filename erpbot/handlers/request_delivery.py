"""Telegram delivery adapter; persistence is delegated to request services."""
import html
import logging
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup
from ..services import requests
from ..core.database import transaction


def create_submitter(get_connection, bot, group_id, topics, clock):
    async def send_request_to_admin(message_obj, telegram_user_id, user_name, req_type, col1, col2, col3, location_val, amount=0, sensitive_data=None, start_date=None, end_date=None, photo_id=None, replacement_staff_id=None):
        now_j = clock()
        created_at = now_j.strftime("%Y/%m/%d %H:%M")
        month_tag = now_j.strftime("%Y/%m")
    
        with get_connection() as conn:
            with transaction(conn):
                req_id, req_code = requests.create_request(
                    conn, telegram_user_id, user_name, message_obj.from_user.full_name,
                    req_type, col1, col2, col3, location_val, year=now_j.year,
                    created_at=created_at, month_tag=month_tag, amount=amount,
                    sensitive_data=sensitive_data, start_date=start_date, end_date=end_date,
                    replacement_staff_id=replacement_staff_id,
                )

        admin_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ تأیید نهایی", callback_data=f"approve_{req_id}"),
             InlineKeyboardButton(text="❌ رد (با دلیل)", callback_data=f"reject_{req_id}")]
        ])

        text = f"📩 <b>درخواست {html.escape(req_type)} ({req_code})</b>\n\n👤 پرسنل: {html.escape(user_name)}\n📌 {html.escape(col1)}\n📌 {html.escape(col2)}\n📌 {html.escape(col3)}\n📅 ثبت: {created_at}\nوضعیت: ⏳ در انتظار تأیید نهایی مدیریت"
    
        try:
            if photo_id:
                sent_msg = await bot.send_photo(chat_id=group_id, message_thread_id=topics["تنخواه"], photo=photo_id, caption=text, reply_markup=admin_kb, parse_mode="HTML")
            else:
                thread_map = {
                    "مرخصی": topics["مرخصی"],
                    "مساعده": topics["مساعده"],
                    "ماموریت": topics["ماموریت"],
                    "تنخواه": topics["تنخواه"],
                    "خرید ملزومات": topics["خرید ملزومات"],
                    "تحویل اموال": topics["تحویل اموال"],
                    "عودت اموال": topics["تحویل اموال"]
                }
                t_id = thread_map.get(req_type, group_id)
                sent_msg = await bot.send_message(chat_id=group_id, message_thread_id=t_id, text=text, reply_markup=admin_kb, parse_mode="HTML")
        
            if sent_msg:
                with get_connection() as conn:
                    requests.record_admin_message(conn, req_id, sent_msg.message_id, sent_msg.chat.id)

            target_msg = message_obj if isinstance(message_obj, Message) else message_obj.message
            await target_msg.answer(f"✅ درخواست {req_type} شما ({req_code}) ثبت و برای تأیید مدیریت ارسال شد.")
        except Exception as e:
            logging.error(f"Send to admin error: {e}")
            target_msg = message_obj if isinstance(message_obj, Message) else message_obj.message
            await target_msg.answer(f"✅ درخواست شما ثبت شد اما در ارسال به کانال گروه خطایی رخ داد.")

        if replacement_staff_id:
            with get_connection() as conn:
                repl_row = requests.replacement_recipient(conn, replacement_staff_id)
            if repl_row and repl_row[0]:
                repl_uid, repl_name = repl_row[0], repl_row[1]
                repl_kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✅ تأیید جانشینی", callback_data=f"replapp_{req_id}"),
                     InlineKeyboardButton(text="❌ عدم تأیید جانشینی", callback_data=f"replrej_{req_id}")]
                ])
                repl_text = f"🔄 <b>درخواست جانشینی در مرخصی</b>\n\nهمکار گرامی <b>{html.escape(repl_name)}</b>،\nهمکار شما <b>{html.escape(user_name)}</b> در درخواست مرخصی خود ({req_code}) شما را به عنوان <b>فرد جایگزین</b> معرفی نموده است.\n\n📌 <b>مشخصات مرخصی:</b>\n{html.escape(col1)}\n{html.escape(col2)}\n\nآیا جانشینی ایشان را تأیید می‌کنید؟"
                try:
                    await bot.send_message(chat_id=repl_uid, text=repl_text, reply_markup=repl_kb, parse_mode="HTML")
                except Exception as e:
                    logging.error(f"Replacement msg error: {e}")

    return send_request_to_admin
