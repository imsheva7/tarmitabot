"""Authorized asset assignment, receipt, editing, return and request approval."""
from dataclasses import dataclass
from ..core.database import transaction
from ..repositories import assets as repository

ASSET_REQUESTS = ("تحویل اموال","عودت اموال")


class AssetError(ValueError):
    pass


@dataclass(frozen=True)
class ApprovalResult:
    outcome: str
    row: tuple | None = None


def positive_id(value):
    if type(value) is not int or not 0<value<=2**63-1:
        raise AssetError("شناسه نامعتبر است.")
    return value


def active_staff(conn, actor_id):
    row=repository.staff(conn,actor_id)
    if row is None:
        raise AssetError("حساب پرسنلی فعال یافت نشد.")
    return row


def require_admin(conn, actor_id, *, main_only=False):
    row=active_staff(conn,actor_id)
    allowed=("main_admin",) if main_only else ("main_admin","finance","purchase")
    if row[2] not in allowed:
        raise AssetError("دسترسی غیرمجاز است.")
    return row


def recipient(conn, actor_id, staff_id):
    require_admin(conn,actor_id)
    row=repository.recipient(conn,positive_id(staff_id))
    if row is None:
        raise AssetError("پرسنل فعال یافت نشد.")
    return row


def staff_list(conn, actor_id):
    require_admin(conn,actor_id)
    return repository.staff_list(conn)


def owned_asset(conn, actor_id, asset_id):
    staff=active_staff(conn,actor_id)
    row=repository.asset(conn,positive_id(asset_id))
    if row is None or row[0]!=staff[0] or row[3]!=1:
        raise AssetError("تجهیز فعال متعلق به شما یافت نشد.")
    return row


def owned_assets(conn, actor_id):
    staff=active_staff(conn,actor_id)
    return repository.owned_list(conn,staff[0])


def recent(conn, actor_id):
    require_admin(conn,actor_id)
    return repository.recent(conn)


def editable_asset(conn, actor_id, asset_id):
    require_admin(conn,actor_id)
    row=repository.asset(conn,positive_id(asset_id))
    if row is None:
        raise AssetError("رکورد مال یافت نشد.")
    return row


def assign(conn, actor_id, staff_id, kind, details, timestamp, encrypted_password=None):
    with transaction(conn):
        name,telegram_id=recipient(conn,actor_id,staff_id)
        if kind not in ("خودروی سازمانی","کارت سوخت","کارت‌خوان","پرینتر جیبی") or not details:
            raise AssetError("اطلاعات تجهیز نامعتبر است.")
        asset_id=repository.insert(conn,staff_id,name,kind,details,timestamp,encrypted_password)
        return asset_id,name,telegram_id


def confirm_receipt(conn, actor_id, asset_id, timestamp):
    with transaction(conn):
        row=owned_asset(conn,actor_id,asset_id)
        if "تأیید قطعی" in (row[4] or ""):
            raise AssetError("این تجهیز قبلاً تأیید شده است.")
        if repository.confirm(conn,asset_id,row[0],f"تأیید قطعی توسط پرسنل ✅ ({timestamp})")!=1:
            raise AssetError("تأیید دریافت ثبت نشد.")


def edit(conn, actor_id, asset_id, details):
    with transaction(conn):
        editable_asset(conn,actor_id,asset_id)
        if not isinstance(details,str) or not details.strip():
            raise AssetError("توضیحات معتبر وارد کنید.")
        if repository.edit(conn,asset_id,details.strip())!=1:
            raise AssetError("ویرایش ثبت نشد.")


def return_by_admin(conn, actor_id, asset_id, date):
    with transaction(conn):
        editable_asset(conn,actor_id,asset_id)
        if repository.return_asset(conn,asset_id,date)!=1:
            raise AssetError("این تجهیز قبلاً عودت داده شده است.")


def is_asset_request(conn, request_id):
    return repository.request_kind(conn,request_id) in ASSET_REQUESTS


def approve(conn, actor_id, request_id, timestamp):
    with transaction(conn):
        require_admin(conn,actor_id,main_only=True)
        row=repository.request(conn,positive_id(request_id))
        if row is None or row[2] not in ASSET_REQUESTS:
            return ApprovalResult("not_found")
        if "در انتظار" not in (row[9] or ""):
            return ApprovalResult("already_processed")
        replacement=repository.replacement_response(conn,request_id)
        if replacement and replacement[0]!="approved":
            return ApprovalResult("replacement_pending")
        staff=active_staff(conn,row[0])
        if row[2]=="تحویل اموال":
            details=f"ثبت از طریق درخواست پرسنل ({row[3]}) | {row[4]} | {row[5]} | {row[6]}"
            repository.insert(conn,staff[0],row[1],row[8] or "سایر تجهیزات",details,timestamp,row[7],approved=True)
        else:
            raw=str(row[8] or "")
            if not raw.isdecimal() or len(raw)>19:
                raise AssetError("شناسه تجهیز نامعتبر است.")
            asset_id=positive_id(int(raw))
            owned_asset(conn,row[0],asset_id)
            if repository.return_asset(conn,asset_id,timestamp.split(' ')[0],staff_id=staff[0])!=1:
                raise AssetError("عودت تجهیز ثبت نشد.")
        if repository.approve_request(conn,request_id)!=1:
            raise RuntimeError("Request status changed unexpectedly")
        return ApprovalResult("approved",tuple(row))
