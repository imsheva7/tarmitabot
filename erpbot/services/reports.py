"""Report access checks and data selection, independent of Telegram and Excel rendering."""
from dataclasses import dataclass
from ..repositories import reports as repository
from ..reporting.catalogue import ADMIN_EXPORTS
from ..reporting.models import Sheet,WorkbookReport


class ReportError(ValueError):
    pass


@dataclass(frozen=True)
class Stats:
    name: str
    balance: float
    used_leave: float
    advances: int
    missions: int


def active_staff(conn, actor_id):
    row=repository.active_staff(conn,actor_id)
    if row is None: raise ReportError('حساب پرسنلی فعال یافت نشد.')
    return row


def require_admin(conn, actor_id):
    row=active_staff(conn,actor_id)
    if row[3] not in ('main_admin','finance','purchase'):
        raise ReportError('دسترسی غیرمجاز است.')


def stats(conn, actor_id, month):
    _,name,balance,_=active_staff(conn,actor_id)
    leave,advances,missions=repository.monthly_stats(conn,actor_id,month)
    used=sum(float(row[0]) for row in leave if row[0] and str(row[0]).replace('.','',1).isdigit())
    total=sum(int(row[0]) for row in advances if row[0])
    return Stats(name,balance,used,total,missions)


def personal_requests(conn, actor_id):
    active_staff(conn,actor_id)
    return repository.personal_requests(conn,actor_id,recent=True)


def personal_export(conn, actor_id):
    staff_id,name,_,_=active_staff(conn,actor_id)
    requests=tuple(tuple(row) for row in repository.personal_requests(conn,actor_id))
    assets=tuple(tuple(row) for row in repository.personal_assets(conn,staff_id))
    return WorkbookReport(f"Report_{name.replace(' ','_')}.xlsx",(
        Sheet('درخواست‌های من',('کد درخواست','نوع درخواست','اطلاعات اصلی','جزئیات اول','جزئیات دوم','وضعیت درخواست','تاریخ ثبت'),requests),
        Sheet('اموال من',('نوع تجهیز','مشخصات و جزئیات مال','وضعیت فعال بودن','وضعیت تایید پرسنل','تاریخ واگذاری'),assets),
    ),owner_staff_id=staff_id)


def admin_export(conn, actor_id, key):
    require_admin(conn,actor_id)
    if key not in ADMIN_EXPORTS: raise ReportError('گزارش نامعتبر است.')
    _,filename,title,mapping=ADMIN_EXPORTS[key]
    rows=tuple(tuple(row) for row in repository.admin_export(conn,key))
    return WorkbookReport(filename,(Sheet(title,tuple(mapping.values()),rows),))


def authorize_export(conn, actor_id, report):
    if report.owner_staff_id is None:
        require_admin(conn,actor_id)
    elif active_staff(conn,actor_id)[0]!=report.owner_staff_id:
        raise ReportError('حساب پرسنلی گزارش تغییر کرده است.')


def pending(conn, actor_id):
    require_admin(conn,actor_id)
    return repository.pending(conn)


def staff_list(conn, actor_id):
    require_admin(conn,actor_id)
    return repository.staff_list(conn)


def absences(conn, actor_id, date):
    require_admin(conn,actor_id)
    return matching_absences(repository.absences(conn),date)


def matching_absences(rows, date):
    matched=[]
    for name,kind,c1,c2,start,end in rows:
        if start and end:
            if start<=date<=end: matched.append((name,kind,c1,c2))
        elif date in f'{c1} | {c2}':
            matched.append((name,kind,c1,c2))
    return matched
