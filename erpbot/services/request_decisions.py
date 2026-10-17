"""Atomic shared approval, non-leave rejection and owner cancellation."""
from dataclasses import dataclass
from ..core.database import transaction
from ..repositories import request_decisions as repository
from .personnel import require_admin, PersonnelError
from .finance import FINANCIAL_TYPES
from .assets import ASSET_REQUESTS

SPECIAL_APPROVALS=('مرخصی','ماموریت')+FINANCIAL_TYPES+ASSET_REQUESTS


class DecisionError(ValueError):
    pass


@dataclass(frozen=True)
class Request:
    id: int
    owner: int
    code: str
    kind: str
    status: str
    admin_chat: int | None
    admin_message: int | None


@dataclass(frozen=True)
class Decision:
    outcome: str
    request: Request | None = None


def request_id(value):
    if type(value) is not int or not 0<value<=2**63-1:
        raise DecisionError('شناسه درخواست نامعتبر است.')
    return value


def resolve(conn, number, fallback_code=None):
    row=repository.request(conn,request_id(number))
    if row is None and fallback_code:
        row=repository.by_code(conn,fallback_code)
    return Request(*row) if row is not None else None


def inspect_decision(conn, actor_id, number, action, fallback_code=None):
    require_admin(conn,actor_id)
    if action not in ('approve','reject'):
        raise DecisionError('عملیات نامعتبر است.')
    row=resolve(conn,number,fallback_code)
    if row is None:
        return Decision('not_found')
    if row.kind=='مرخصی' or (action=='approve' and row.kind in SPECIAL_APPROVALS):
        return Decision('invalid_type',row)
    if 'در انتظار' not in (row.status or ''):
        return Decision('already_processed',row)
    return Decision('ready',row)


def approve(conn, actor_id, number, fallback_code=None):
    with transaction(conn):
        result=inspect_decision(conn,actor_id,number,'approve',fallback_code)
        if result.outcome!='ready':
            return result
        row=result.request
        replacement=repository.replacement(conn,row.id)
        if replacement and replacement[0]!='approved':
            return Decision('replacement_pending',row)
        if repository.approve(conn,row.id)!=1:
            return Decision('already_processed',row)
        return Decision('approved',row)


def reject(conn, actor_id, number, reason):
    if not isinstance(reason,str) or not reason.strip():
        raise DecisionError('❌ دلیل معتبر وارد کنید.')
    with transaction(conn):
        result=inspect_decision(conn,actor_id,number,'reject')
        if result.outcome!='ready':
            return result
        if repository.reject(conn,result.request.id,reason.strip())!=1:
            return Decision('already_processed',result.request)
        return Decision('rejected',result.request)


def cancel(conn, actor_id, code):
    if not isinstance(code,str) or not code or len(code)>64:
        raise DecisionError('کد درخواست نامعتبر است.')
    with transaction(conn):
        if repository.active_staff(conn,actor_id) is None:
            raise PersonnelError('حساب پرسنلی فعال و متصل لازم است.')
        raw=repository.by_code(conn,code)
        if raw is None:
            return Decision('not_found')
        row=Request(*raw)
        if row.kind=='مرخصی':
            return Decision('invalid_type',row)
        if row.owner!=actor_id or 'در انتظار' not in (row.status or ''):
            return Decision('cannot_cancel')
        if repository.cancel(conn,row.id,actor_id)!=1:
            return Decision('cannot_cancel')
        return Decision('cancelled',row)
