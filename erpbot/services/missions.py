"""Mission dates, active staff and atomic main-admin approval, independent of Telegram."""
from dataclasses import dataclass
import jdatetime
from ..core.database import transaction
from ..core.dates import normalize_jalali_date,validate_custom_date
from ..repositories import missions as repository


class MissionError(ValueError):
    pass


@dataclass(frozen=True)
class Approval:
    outcome: str
    row: tuple | None = None


def active_staff(conn, actor_id):
    row=repository.staff(conn,actor_id)
    if row is None: raise MissionError('حساب پرسنلی فعال یافت نشد.')
    return row


def date_range(start, end):
    start,end=normalize_jalali_date(start or ''),normalize_jalali_date(end or '')
    if not validate_custom_date(start) or not validate_custom_date(end):
        raise MissionError('تاریخ نامعتبر است.')
    first=jdatetime.date(*map(int,start.split('/')))
    last=jdatetime.date(*map(int,end.split('/')))
    if last<first: raise MissionError('تاریخ پایان نمی‌تواند قبل از شروع باشد.')
    return start,end,(last-first).days+1


def is_mission_request(conn, request_id):
    return repository.request_kind(conn,request_id)=='ماموریت'


def approve(conn, actor_id, request_id):
    if type(request_id) is not int or not 0<request_id<=2**63-1:
        raise MissionError('شناسه درخواست نامعتبر است.')
    with transaction(conn):
        if active_staff(conn,actor_id)[2]!='main_admin':
            raise MissionError('فقط مدیر اصلی مجاز است.')
        row=repository.request(conn,request_id)
        if row is None or row[2]!='ماموریت': return Approval('not_found')
        if 'در انتظار' not in (row[3] or ''): return Approval('already_processed')
        replacement=repository.replacement(conn,request_id)
        if replacement and replacement[0]!='approved': return Approval('replacement_pending')
        if repository.approve(conn,request_id)!=1: raise RuntimeError('Request status changed unexpectedly')
        return Approval('approved',tuple(row))
