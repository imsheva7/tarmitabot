"""Reminder validation, Persian command parsing and calendar rules, without Telegram."""
from dataclasses import dataclass
import re
import jdatetime
from ..core.dates import normalize_jalali_date, normalize_persian_numbers, validate_custom_date
from ..repositories import reminders as repository

DAY_MAP = {"شنبه":"Saturday", "یکشنبه":"Sunday", "دوشنبه":"Monday", "سه‌شنبه":"Tuesday",
           "چهارشنبه":"Wednesday", "پنج‌شنبه":"Thursday", "جمعه":"Friday"}


class ReminderError(ValueError):
    pass


@dataclass(frozen=True)
class ReminderSpec:
    kind: str
    when: str | int
    time: str
    content: str


def active_staff_name(conn, actor_id):
    name = repository.active_staff_name(conn, actor_id)
    if not name:
        raise ReminderError("❌ ابتدا باید حساب پرسنلی فعال خود را با دستور /start متصل کنید.")
    return name


def normalized_time(text):
    text = normalize_persian_numbers(text).strip()
    if not re.fullmatch(r"\d{1,2}:\d{2}", text):
        raise ReminderError("❌ فرمت ساعت نامعتبر است (مثال: 08:30).")
    hour,minute = map(int,text.split(':'))
    if hour > 23 or minute > 59:
        raise ReminderError("❌ ساعت وارد شده نامعتبر است.")
    return f"{hour:02d}:{minute:02d}"


def reminder_date(kind, text, now):
    text = normalize_persian_numbers(str(text)).strip()
    if kind == "once":
        offset = {"فردا":1,"پس‌فردا":2}.get(text)
        if offset:
            return (now + jdatetime.timedelta(days=offset)).strftime("%Y/%m/%d")
        if validate_custom_date(text):
            return normalize_jalali_date(text)
        raise ReminderError("❌ تاریخ نامعتبر است.")
    if kind == "monthly":
        if not text.isdecimal() or len(text)>2 or not 1<=int(text)<=31:
            raise ReminderError("❌ روز ماه باید عددی بین ۱ تا ۳۱ باشد.")
        return int(text)
    if kind == "weekly" and text in DAY_MAP.values():
        return text
    raise ReminderError("❌ نوع یادآوری یا روز هفته نامعتبر است.")


def build_spec(kind, when, time, content, now):
    when = reminder_date(kind,when,now)
    time = normalized_time(time)
    if not isinstance(content,str) or not content.strip():
        raise ReminderError("❌ لطفاً متن معتبر ارسال کنید.")
    if kind == "once" and f"{when} {time}" <= now.strftime("%Y/%m/%d %H:%M"):
        raise ReminderError("❌ زمان یادآوری نمی‌تواند در گذشته باشد.")
    return ReminderSpec(kind,when,time,content.strip())


def parse_group(text, now):
    patterns = [
        ("weekly",r"#یادآوری\s+هر\s+(شنبه|یکشنبه|دوشنبه|سه‌شنبه|چهارشنبه|پنج‌شنبه|جمعه)\s+(?:ساعت\s+)?(\d{1,2}:\d{2})\s+(.+)"),
        ("monthly",r"#یادآوری\s+روز\s+(اول|یک|\d{1,2})\s+هر\s+ماه\s+(?:ساعت\s+)?(\d{1,2}:\d{2})\s+(.+)"),
        ("natural",r"#یادآوری\s+(فردا|پس‌فردا|امروز)\s+(?:ساعت\s+)?(\d{1,2}:\d{2})\s+(.+)"),
        ("once",r"#یادآوری\s+(\d{4}/\d{1,2}/\d{1,2})\s+(\d{1,2}:\d{2})\s+(.+)"),
    ]
    for kind,pattern in patterns:
        match = re.search(pattern,text,re.DOTALL) if kind != "once" else re.match(pattern,text,re.DOTALL)
        if not match:
            continue
        when,time,content = match.groups()
        if kind == "weekly":
            when = DAY_MAP[when]
        elif kind == "monthly" and when in ("اول","یک"):
            when = 1
        elif kind == "natural":
            kind = "once"
            if when == "امروز":
                when = now.strftime("%Y/%m/%d")
        return build_spec(kind,when,time,content,now)
    raise ReminderError("❌ فرمت یادآوری نامعتبر است. نمونه صحیح: #یادآوری فردا ساعت ۱۰:۳۰ جلسه")


def target(chat_id, thread_id):
    if type(chat_id) is not int or not -(2**63) <= chat_id < 0:
        raise ReminderError("❌ شناسه گروه نامعتبر است.")
    if thread_id is not None and (type(thread_id) is not int or not 0 < thread_id <= 2**63-1):
        raise ReminderError("❌ شناسه موضوع نامعتبر است.")
    return chat_id,thread_id


def parse_link(payload):
    parts = payload.split('_')
    if len(parts)!=3 or parts[0]!='reminder' or any(len(p)>20 for p in parts[1:]):
        raise ReminderError("❌ لینک یادآوری نامعتبر است.")
    try:
        chat_id = int(parts[1])
        thread_id = None if parts[2]=='None' else int(parts[2])
    except ValueError:
        raise ReminderError("❌ لینک یادآوری نامعتبر است.") from None
    return target(chat_id,thread_id)


def register(conn, actor_id, chat_id, thread_id, spec, now):
    name = active_staff_name(conn,actor_id)
    chat_id,thread_id = target(chat_id,thread_id)
    spec = build_spec(spec.kind,spec.when,spec.time,spec.content,now)
    return repository.insert(conn,chat_id,thread_id,actor_id,name,spec)


def manage(conn, actor_id, chat_id, thread_id, *, page=0, reminder_id=None, delete=False):
    active_staff_name(conn,actor_id)
    target(chat_id,thread_id)
    if type(page) is not int or not 0 <= page <= 1000000:
        raise ReminderError('صفحه نامعتبر است.')
    if reminder_id is None:
        return repository.owned_list(conn,actor_id,chat_id,thread_id,page*5)
    if type(reminder_id) is not int or not 0 < reminder_id <= 2**63-1:
        raise ReminderError('شناسه یادآور نامعتبر است.')
    row=repository.owned(conn,actor_id,chat_id,thread_id,reminder_id)
    if row is None:
        raise ReminderError('یادآور یافت نشد یا متعلق به شما در این مقصد نیست.')
    if delete:
        repository.delete_owned(conn,actor_id,chat_id,thread_id,reminder_id)
    return row


def due(conn, now):
    max_days = 31 if now.month<=6 else 30 if now.month<=11 else (30 if jdatetime.date(now.year,1,1).isleap() else 29)
    days = list(range(now.day,32)) if now.day>=max_days else [now.day]
    date,time = now.strftime("%Y/%m/%d"),now.strftime("%H:%M")
    return repository.due(conn,f"{date} {time}",date,time,now.togregorian().strftime("%A"),days)


def mark_delivered(conn, reminder_id, kind, date):
    return repository.mark_delivered(conn,reminder_id,kind,date)
