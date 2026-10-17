"""Insurance permissions, validated dates, car selection and seven-day alert calculations."""
from dataclasses import dataclass
import re
import jdatetime
from ..core.database import transaction
from ..core.dates import normalize_jalali_date,validate_custom_date
from ..repositories import insurance as repository


class InsuranceError(ValueError):
    pass


@dataclass(frozen=True)
class Alert:
    code: str
    car: str
    plate: str
    company: str
    due: str


def require_admin(conn, actor_id):
    if repository.actor_role(conn,actor_id) not in ('main_admin','finance','purchase'):
        raise InsuranceError('دسترسی غیرمجاز است.')


def car_code(details):
    details=details or ''
    match=re.search(r'کد:\s*([^|]+)',details)
    return match.group(1).strip() if match else details[:20]


def cars(conn, actor_id):
    require_admin(conn,actor_id)
    seen=set()
    result=[]
    for asset_id,details in repository.cars(conn):
        if details not in seen:
            result.append((asset_id,car_code(details)))
            seen.add(details)
    return result


def selected_car(conn, actor_id, selector=None, *, asset_id=None):
    candidates=cars(conn,actor_id)
    if asset_id is not None:
        if type(asset_id) is not int or not 0<asset_id<=2**63-1:
            raise InsuranceError('شناسه خودرو نامعتبر است.')
        for candidate_id,code in candidates:
            if candidate_id==asset_id: return code
    else:
        for _,code in candidates:
            if code==selector: return code
    raise InsuranceError('خودروی فعال یافت نشد؛ دوباره انتخاب کنید.')


def valid_date(value, *, optional=False):
    if not isinstance(value,str): raise InsuranceError('تاریخ نامعتبر است.')
    value=(value or '').strip()
    if optional and value=='-': return '-'
    normalized=normalize_jalali_date(value)
    if not validate_custom_date(normalized): raise InsuranceError('تاریخ نامعتبر است.')
    return normalized


def save(conn, actor_id, code, car, plate, company, third, body, *, selector=None, asset_id=None):
    with transaction(conn):
        require_admin(conn,actor_id)
        if selector is not None or asset_id is not None:
            if selected_car(conn,actor_id,selector,asset_id=asset_id)!=code:
                raise InsuranceError('انتخاب خودرو معتبر نیست.')
        if any(not isinstance(value,str) or not value.strip() for value in (code,car,plate,company)):
            raise InsuranceError('اطلاعات بیمه کامل نیست.')
        values=(code.strip(),car.strip(),plate.strip(),company.strip(),valid_date(third),valid_date(body,optional=True))
        return repository.insert(conn,values)


def due_alerts(conn, today):
    alerts=[]
    for code,car,plate,company,third,body in repository.all_records(conn):
        for date in (third,body):
            try:
                normalized=valid_date(date)
            except InsuranceError:
                continue
            expiry=jdatetime.date(*map(int,normalized.split('/')))
            if (expiry-today).days==7:
                alerts.append(Alert(code or '',car or '',plate or '',company or '',date))
    return alerts


def main_admins(conn):
    return repository.main_admins(conn)
