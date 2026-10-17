"""Request persistence use cases. Notification and transaction ownership are external."""
from ..repositories import requests as repository, leave
from . import assets, finance, missions


class RequestSubmissionError(ValueError):
    pass


def create_request(conn, telegram_id, user_name, telegram_info, req_type, col1, col2, col3,
                   location, *, year, created_at, month_tag, amount=0, sensitive_data=None,
                   start_date=None, end_date=None, replacement_staff_id=None):
    if req_type == "مرخصی":
        staff = leave.active_staff(conn, telegram_id)
        if staff is None:
            raise RequestSubmissionError("حساب پرسنلی فعال یافت نشد.")
        user_name = staff[1]
        if replacement_staff_id:
            row = leave.replacement_staff(conn, replacement_staff_id)
            if row is None or row[1] is None or row[1] == telegram_id:
                raise RequestSubmissionError("جانشین فعال و متصل پیدا نشد.")
    if req_type in assets.ASSET_REQUESTS:
        staff = assets.active_staff(conn,telegram_id)
        user_name = staff[1]
        if req_type == "عودت اموال":
            raw = str(location or '')
            if not raw.isdecimal() or len(raw)>19:
                raise assets.AssetError("شناسه تجهیز نامعتبر است.")
            assets.owned_asset(conn,telegram_id,int(raw))
    if req_type in finance.FINANCIAL_TYPES:
        user_name = finance.active_staff(conn,telegram_id)[1]
        if req_type in finance.PAYMENT_TYPES:
            finance.validate_amount(amount)
        if req_type == 'مساعده':
            finance.require_advance_capacity(conn,telegram_id,month_tag,int(created_at[8:10]),amount)
    if req_type == 'ماموریت':
        user_name=missions.active_staff(conn,telegram_id)[1]
        if start_date is not None or end_date is not None:
            start_date,end_date,_=missions.date_range(start_date,end_date)
    request_id = repository.insert_request(conn, (
        telegram_id,user_name,telegram_info,req_type,col1,col2,col3,sensitive_data,amount,
        start_date,end_date,location,"⏳ در انتظار تأیید نهایی مدیریت",created_at,month_tag,
    ))
    if replacement_staff_id:
        repository.insert_replacement(conn, request_id, replacement_staff_id)
    code = f"REQ-{year}-{request_id:05d}"
    repository.set_code(conn, request_id, code)
    return request_id, code


def record_admin_message(conn, request_id, message_id, chat_id):
    repository.set_admin_message(conn, request_id, message_id, chat_id)


def replacement_recipient(conn, staff_id):
    return repository.replacement_recipient(conn, staff_id)
