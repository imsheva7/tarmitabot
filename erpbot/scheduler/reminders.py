"""Single-worker reminder delivery; no database connection is held during Telegram I/O."""
import asyncio
import html
import logging
from ..services import reminders as service


async def deliver_due(get_connection, bot, now):
    with get_connection() as conn:
        reminders = service.due(conn,now)
    headings = {"once":"🔔 <b>یادآوری ثبت‌شده</b>","weekly":"🔄 <b>یادآوری هفتگی</b>","monthly":"🔄 <b>یادآوری ماهانه</b>"}
    for reminder_id,chat_id,thread_id,name,content,kind in reminders:
        text = f"{headings[kind]}\n\n👤 ثبت‌کننده: <b>{html.escape(name)}</b>\n📝 {html.escape(content)}"
        try:
            kwargs = {"chat_id":chat_id,"text":text,"parse_mode":"HTML"}
            if thread_id and thread_id != "None":
                kwargs["message_thread_id"] = int(thread_id)
            await bot.send_message(**kwargs)
            with get_connection() as conn:
                service.mark_delivered(conn,reminder_id,kind,now.strftime("%Y/%m/%d"))
        except Exception:
            logging.exception("Reminder delivery failed for %s",reminder_id)


async def run_scheduler(get_connection, bot, clock, *, sleep=asyncio.sleep):
    last_minute = ""
    while True:
        await sleep(15)
        try:
            now = clock()
            minute = f'{now.strftime("%Y/%m/%d")} {now.strftime("%H:%M")}'
            if minute == last_minute:
                continue
            await deliver_due(get_connection,bot,now)
            last_minute = minute
        except Exception:
            logging.exception("Reminder scheduler failed")
