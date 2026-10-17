"""Daily absence report, independent of Telegram and runtime."""
import html
import jdatetime
from ..repositories.scheduled_reports import approved_absences
from .insurance import main_admins


def tomorrow_report(conn, now):
    tomorrow = (now + jdatetime.timedelta(days=1)).strftime('%Y/%m/%d')
    matched = []
    for name, kind, first, second, start, end in approved_absences(conn):
        included = start <= tomorrow <= end if start and end else tomorrow in f'{first} | {second}'
        if included:
            matched.append((name, kind, first, second))
    if not matched:
        return None
    text = f'📋 <b>برنامه غایبین و مأموریت‌های فردا ({tomorrow}):</b>\n\n'
    for row in matched:
        name, kind, first, second = (html.escape(str(value or '')) for value in row)
        text += f'▫️ <b>{name}</b> ➔ {kind} ({first} | {second})\n'
    return text
