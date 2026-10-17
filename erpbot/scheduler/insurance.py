"""One daily insurance alert pass; database connections close before Telegram I/O."""
import html
import logging
from ..services import insurance as service


async def deliver_alerts(get_connection, bot, now):
    with get_connection() as conn:
        alerts=service.due_alerts(conn,now.date())
    for alert in alerts:
        text=(f'⚠️ <b>هشدار بیمه خودرو</b>\nکد: {html.escape(alert.code)} - {html.escape(alert.car)} ({html.escape(alert.plate)})\n'
              f'بیمه {html.escape(alert.company)} تا <b>۷ روز دیگر</b> ({html.escape(alert.due)}) مهلت دارد.')
        with get_connection() as conn:
            recipients=service.main_admins(conn)
        for recipient in recipients:
            with get_connection() as conn:
                still_authorized=recipient in service.main_admins(conn)
            if not still_authorized: continue
            try:
                await bot.send_message(chat_id=recipient,text=text,parse_mode='HTML')
            except Exception as exc:
                logging.error('Insurance alert failed: %s',type(exc).__name__)
