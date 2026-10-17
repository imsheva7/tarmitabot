"""Background jobs with explicit dependencies; importing starts no resources.

Daily markers are process-local, preserving the existing single-worker schedule.
"""
import asyncio
import logging
from pathlib import Path
from aiogram.types import FSInputFile
from ..core.backup import database_snapshot
from ..services import scheduled_reports as reports
from .insurance import deliver_alerts


async def send_to_admins(get_connection, send):
    with get_connection() as conn:
        recipients = reports.main_admins(conn)
    for recipient in recipients:
        with get_connection() as conn:
            authorized = recipient in reports.main_admins(conn)
        if not authorized:
            continue
        try:
            await send(recipient)
        except Exception:
            logging.exception('Scheduled delivery failed for admin %s', recipient)


async def deliver_salary_notice(get_connection, bot):
    await send_to_admins(get_connection, lambda recipient: bot.send_message(
        chat_id=recipient,
        text='🚨 <b>یادآور مالی:</b> امروز <b>۲۵ام ماه</b> است؛ لطفاً بیمه تأمین اجتماعی پرسنل را پرداخت کنید.',
        parse_mode='HTML'))


async def deliver_tomorrow_report(get_connection, bot, now):
    with get_connection() as conn:
        text = reports.tomorrow_report(conn, now)
    if text:
        await send_to_admins(get_connection, lambda recipient: bot.send_message(
            chat_id=recipient, text=text, parse_mode='HTML'))


async def deliver_backup(get_connection, bot, database_path, now):
    if not Path(database_path).is_file():
        return
    with get_connection() as conn:
        if not reports.main_admins(conn):
            return
    with database_snapshot(database_path) as path:
        filename = f"erpbot_backup_{now.strftime('%Y/%m/%d').replace('/', '-')}.sqlite3"
        await send_to_admins(get_connection, lambda recipient: bot.send_document(
            chat_id=recipient, document=FSInputFile(path, filename=filename),
            caption='📦 پشتیبان خودکار هفتگی دیتابیس سامانه'))


async def background_schedulers(get_connection, bot, clock, database_path, *, sleep=asyncio.sleep):
    last_run = {}
    while True:
        await sleep(60)
        try:
            now = clock()
            date = now.strftime('%Y/%m/%d')
            hour = now.strftime('%H:%M')
            jobs = [('insurance', True, lambda: deliver_alerts(get_connection, bot, now)),
                    ('salary', now.day == 25, lambda: deliver_salary_notice(get_connection, bot)),
                    ('tomorrow', hour == '19:00', lambda: deliver_tomorrow_report(get_connection, bot, now)),
                    ('backup', now.togregorian().strftime('%A') == 'Monday' and hour == '08:00',
                     lambda: deliver_backup(get_connection, bot, database_path, now))]
            for name, due, run in jobs:
                if not due or last_run.get(name) == date:
                    continue
                last_run[name] = date
                try:
                    await run()
                except Exception:
                    logging.exception('Background job failed: %s', name)
        except Exception:
            logging.exception('Background scheduler failed')
