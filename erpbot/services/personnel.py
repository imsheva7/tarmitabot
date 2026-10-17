"""Main-admin personnel mutations, with atomic ledger updates and settlement."""
import math
import sqlite3
from ..core.database import transaction
from ..core.dates import normalize_persian_numbers,normalize_jalali_date,validate_custom_date
from ..repositories import personnel as repository

EDIT_FIELDS=frozenset(repository.EDIT_FIELDS)
ROLES=('main_admin','finance','purchase','staff')


class PersonnelError(ValueError): pass


def require_admin(conn, actor_id, *, main_only=True):
    allowed=('main_admin',) if main_only else ('main_admin','finance','purchase')
    if repository.actor_role(conn,actor_id) not in allowed: raise PersonnelError('❌ دسترسی غیرمجاز است.')


def balance_value(value):
    try: result=float(normalize_persian_numbers(str(value)))
    except (ValueError,TypeError,OverflowError): raise PersonnelError('مانده مرخصی باید عدد معتبر باشد.') from None
    if not math.isfinite(result): raise PersonnelError('مانده مرخصی باید عدد محدود و معتبر باشد.')
    return result


def date_value(value):
    value=normalize_jalali_date(value or '')
    if not validate_custom_date(value): raise PersonnelError('تاریخ نامعتبر است.')
    return value


def phone_key(value):
    value=normalize_persian_numbers(value or '').strip().replace(' ','').removeprefix('+')
    if value.startswith('98') and len(value)==12: value='0'+value[2:]
    return value


def check_phone(conn, phone, staff_id=None):
    if not isinstance(phone,str) or not phone.strip(): raise PersonnelError('شماره تماس معتبر وارد کنید.')
    key=phone_key(phone)
    if any(sid!=staff_id and phone_key(existing)==key for sid,existing in repository.phones(conn)):
        raise PersonnelError('شماره تماس قبلاً ثبت شده است.')


def target(conn, actor_id, staff_id):
    require_admin(conn,actor_id)
    if type(staff_id) is not int or not 0<staff_id<=2**63-1: raise PersonnelError('شناسه پرسنلی نامعتبر است.')
    row=repository.target(conn,staff_id)
    if row is None or row[2]!=1: raise PersonnelError('پرسنل فعال یافت نشد.')
    return row


def active_list(conn, actor_id):
    require_admin(conn,actor_id)
    return repository.active_list(conn)


def add(conn, actor_id, name, phone, role, balance, employment_date, timestamp):
    with transaction(conn):
        require_admin(conn,actor_id)
        if not isinstance(name,str) or not name.strip(): raise PersonnelError('نام معتبر وارد کنید.')
        if role not in ROLES: raise PersonnelError('نقش غیرمجاز است.')
        check_phone(conn,phone)
        balance=balance_value(balance)
        date=date_value(employment_date)
        try:
            staff_id=repository.insert(conn,name.strip(),normalize_persian_numbers(phone).strip(),role,balance,date)
        except sqlite3.IntegrityError as exc:
            if getattr(exc,'sqlite_errorcode',None)!=sqlite3.SQLITE_CONSTRAINT_UNIQUE: raise
            raise PersonnelError('نام یا اطلاعات پرسنل قبلاً ثبت شده است.') from None
        if balance!=0:
            repository.record_change(conn,staff_id,name.strip(),balance,'مانده مرخصی اولیه',timestamp)
        return staff_id


def edit(conn, actor_id, staff_id, field, value, timestamp):
    with transaction(conn):
        name,current,_=target(conn,actor_id,staff_id)
        if field not in EDIT_FIELDS: raise PersonnelError('فیلد غیرمجاز است.')
        if field=='leave_balance':
            requested=balance_value(value)
            current=balance_value(current)
            total=balance_value(repository.ledger_total(conn,staff_id))
            if current!=total:
                repository.record_change(conn,staff_id,name,current-total,'تطبیق مانده پیشین با دفتر مرخصی',timestamp)
            if requested!=current:
                repository.record_change(conn,staff_id,name,requested-current,'ویرایش دستی مانده',timestamp)
            value=balance_value(repository.ledger_total(conn,staff_id))
        elif field=='employment_date': value=date_value(value)
        else:
            if not isinstance(value,str) or not value.strip(): raise PersonnelError('مقدار معتبر وارد کنید.')
            value=value.strip()
            if field=='phone_number':
                check_phone(conn,value,staff_id)
                value=normalize_persian_numbers(value)
        try: changed=repository.edit(conn,staff_id,field,value)
        except sqlite3.IntegrityError as exc:
            if getattr(exc,'sqlite_errorcode',None)!=sqlite3.SQLITE_CONSTRAINT_UNIQUE: raise
            raise PersonnelError('اطلاعات پرسنل تکراری است.') from None
        if changed!=1: raise PersonnelError('تغییر اطلاعات ثبت نشد.')


def deactivate(conn, actor_id, staff_id, date):
    with transaction(conn):
        target(conn,actor_id,staff_id)
        date=date_value(date)
        if repository.deactivate(conn,staff_id,date)!=1: raise PersonnelError('تسویه قبلاً ثبت شده است.')
        repository.deactivate_assets(conn,staff_id)
