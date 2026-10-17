"""Account access and atomic contact authentication, independent of Telegram."""
from dataclasses import dataclass
import sqlite3
from ..core.database import transaction
from ..repositories import navigation as repository
from .personnel import phone_key


class LoginError(ValueError):
    pass


@dataclass(frozen=True)
class Account:
    id: int
    name: str
    balance: float
    phone: str | None
    active: int
    role: str


def account(conn, actor_id):
    row=repository.by_telegram(conn,actor_id)
    return Account(*row) if row is not None else None


def active_account(conn, actor_id):
    result=account(conn,actor_id)
    if result is None or result.active!=1:
        raise LoginError('حساب پرسنلی فعال و متصل لازم است.')
    return result


def is_admin(result):
    return result.role in ('main_admin','finance','purchase')


def group_allowed(conn, actor_id, chat_id, configured_group):
    return chat_id==configured_group or repository.actor_role(conn,actor_id)=='main_admin'


def link_contact(conn, actor_id, contact_user_id, phone):
    if type(actor_id) is not int or actor_id<=0 or type(contact_user_id) is not int or contact_user_id!=actor_id:
        raise LoginError('❌ خطای امنیتی: شماره تماس متعلق به حساب تلگرام شما نیست!')
    key=phone_key(phone) if isinstance(phone,str) else ''
    if not key or not key.isdecimal():
        raise LoginError('شماره تماس معتبر یافت نشد.')
    with transaction(conn):
        current=account(conn,actor_id)
        if current is not None and current.active!=1:
            raise LoginError('❌ حساب کاربری شما غیرفعال است.')
        matches=[sid for sid,stored in repository.phones(conn) if phone_key(stored)==key]
        if not matches:
            raise LoginError('⚠️ شماره شما در لیست پرسنل مجاز یافت نشد.')
        if len(matches)!=1:
            raise LoginError('شماره تماس به چند رکورد پرسنلی تعلق دارد؛ برای اصلاح اطلاعات با مدیر تماس بگیرید.')
        row=repository.by_id(conn,matches[0])
        if row[4]!=1:
            raise LoginError('❌ حساب کاربری شما غیرفعال است.')
        if (row[6] is not None and row[6]!=actor_id) or (current is not None and current.id!=row[0]):
            raise LoginError('این حساب قبلاً به تلگرام دیگری متصل شده یا حساب شما به پرسنل دیگری متصل است؛ با مدیر تماس بگیرید.')
        try:
            changed=repository.link(conn,row[0],actor_id)
        except sqlite3.IntegrityError as exc:
            if getattr(exc,'sqlite_errorcode',None)!=sqlite3.SQLITE_CONSTRAINT_UNIQUE:
                raise
            raise LoginError('اتصال حساب تکراری است؛ با مدیر تماس بگیرید.') from None
        if changed!=1:
            raise LoginError('اتصال حساب ثبت نشد؛ دوباره تلاش کنید.')
        return active_account(conn,actor_id)
