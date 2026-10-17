"""Main-admin holiday operations on the existing schema."""
from ..core.database import transaction
from ..repositories import holidays as repository
from .personnel import require_admin,date_value,PersonnelError


def recent(conn, actor_id):
    require_admin(conn,actor_id)
    return repository.recent(conn)


def save(conn, actor_id, date, description):
    with transaction(conn):
        require_admin(conn,actor_id)
        date=date_value(date)
        if not isinstance(description,str) or not description.strip(): raise PersonnelError('شرح معتبر وارد کنید.')
        repository.save(conn,date,description.strip())


def delete(conn, actor_id, date):
    with transaction(conn):
        require_admin(conn,actor_id)
        date_value(date)
        return repository.delete(conn,date)
