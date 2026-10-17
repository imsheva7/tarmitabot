"""Administrative access and authorized snapshots without Telegram objects."""
from contextlib import contextmanager
from ..core.backup import database_snapshot
from .personnel import require_admin, PersonnelError


@contextmanager
def authorized_backup(get_connection, database_path, actor_id):
    with get_connection() as conn:
        require_admin(conn, actor_id)
    with database_snapshot(database_path) as path:
        # Permission may change while SQLite copies a large database.
        with get_connection() as conn:
            require_admin(conn, actor_id)
        yield path
