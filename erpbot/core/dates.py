"""Shared date/text helpers without application startup."""
from datetime import datetime
import re
import jdatetime
import pytz


def normalize_persian_numbers(text):
    if not text:
        return ""
    return text.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))


def normalize_jalali_date(text):
    clean = normalize_persian_numbers(text).strip().replace("-", "/")
    parts = clean.split("/")
    if len(parts) == 3:
        try:
            year, month, day = map(int, parts)
            return f"{year:04d}/{month:02d}/{day:02d}"
        except (TypeError, ValueError):
            pass
    return clean


def validate_custom_date(text):
    clean = normalize_jalali_date(text)
    if not re.match(r"^\d{4}/\d{2}/\d{2}$", clean):
        return False
    try:
        jdatetime.date(*map(int, clean.split("/")))
        return True
    except (TypeError, ValueError):
        return False


def get_current_tehran_time():
    return jdatetime.datetime.fromgregorian(datetime=datetime.now(pytz.utc).astimezone(pytz.timezone("Asia/Tehran")))
