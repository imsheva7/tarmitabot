"""Financial and purchase rules, independent of Telegram and runtime."""
from dataclasses import dataclass
from ..core.database import transaction
from ..core.dates import normalize_persian_numbers
from ..repositories import finance as repository

MAX_BASE_ADVANCE=100_000_000
FINANCIAL_TYPES=('مساعده','تنخواه','خرید ملزومات')
PAYMENT_TYPES=('مساعده','تنخواه')


class FinanceError(ValueError):
    pass


@dataclass(frozen=True)
class Decision:
    outcome: str
    row: tuple | None = None


def active_staff(conn, actor_id):
    row=repository.active_staff(conn,actor_id)
    if row is None:
        raise FinanceError('حساب پرسنلی فعال یافت نشد.')
    return row


def amount_value(text, *, allow_rial=False):
    raw=normalize_persian_numbers(text).replace(',','').strip()
    if allow_rial:
        raw=raw.replace('ریال','').strip()
    if not raw.isdecimal() or len(raw)>19 or int(raw)>2**63-1:
        raise FinanceError('❌ مبلغ معتبر و در محدوده مجاز وارد کنید.')
    return int(raw)


def validate_amount(amount):
    if type(amount) is not int or not 0<=amount<=2**63-1:
        raise FinanceError('❌ مبلغ معتبر و در محدوده مجاز وارد کنید.')


def valid_card(text):
    clean=normalize_persian_numbers(text).strip().replace(' ','').upper()
    return ((clean.isdecimal() and len(clean) in (16,24))
            or (clean.startswith('IR') and len(clean)==26 and clean[2:].isdecimal()))


def advance_capacity(conn, actor_id, month, day):
    active_staff(conn,actor_id)
    taken=sum(int(row[0]) for row in repository.advance_amounts(conn,actor_id,month) if row[0])
    limit=int(day*(MAX_BASE_ADVANCE/30.0))
    return limit-taken,taken,limit


def require_advance_capacity(conn, actor_id, month, day, amount):
    validate_amount(amount)
    remaining,taken,limit=advance_capacity(conn,actor_id,month,day)
    if amount>remaining:
        raise FinanceError(f'⚠️ سقف باقیمانده مساعده شما تا امروز: {remaining:,} ریال است (کل دریافتی این ماه: {taken:,} از سقف {limit:,}):')


def is_financial_request(conn, request_id):
    return repository.kind(conn,request_id) in FINANCIAL_TYPES


def decide(conn, actor_id, request_id, action):
    if type(request_id) is not int or not 0<request_id<=2**63-1:
        raise FinanceError('شناسه درخواست نامعتبر است.')
    roles={'approve':('main_admin',),'paid':('main_admin','finance'),'bought':('main_admin','purchase')}
    if action not in roles:
        raise FinanceError('عملیات نامعتبر است.')
    with transaction(conn):
        if active_staff(conn,actor_id)[2] not in roles[action]:
            raise FinanceError('دسترسی غیرمجاز است.')
        row=repository.request(conn,request_id)
        if row is None:
            return Decision('not_found')
        if row[2] not in FINANCIAL_TYPES or (action=='paid' and row[2] not in PAYMENT_TYPES) or (action=='bought' and row[2]!='خرید ملزومات'):
            return Decision('invalid_type')
        if action=='approve':
            if 'در انتظار' not in (row[8] or ''):
                return Decision('already_processed')
            replacement=repository.replacement(conn,request_id)
            if replacement and replacement[0]!='approved':
                return Decision('replacement_pending')
            changed=repository.approve(conn,request_id)
        else:
            if row[8]!='✅ تأیید شده قطعی':
                return Decision('already_processed')
            status='💳 تسویه و پرداخت شده' if action=='paid' else '🛒 خریداری شده'
            changed=repository.complete(conn,request_id,status)
        if changed!=1:
            raise RuntimeError('Request status changed unexpectedly')
        return Decision(action,tuple(row))


def recipient(conn, role):
    if role not in ('finance','purchase'):
        raise FinanceError('نقش گیرنده نامعتبر است.')
    return repository.recipient(conn,role)
