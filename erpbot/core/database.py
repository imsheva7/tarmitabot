"""SQLite connection lifecycle, independent of configuration and Telegram."""
from contextlib import contextmanager
import sqlite3


@contextmanager
def connect(database_path, *, timeout=10):
    """Commit on success, roll back on failure, and always close the connection.

    Uses the existing sqlite3.Row contract and enforces foreign keys for every
    connection. No connection is opened until the context manager is entered.
    """
    conn = sqlite3.connect(database_path, timeout=timeout)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def transaction(conn):
    """Own one immediate transaction without rolling back a caller's open work."""
    if conn.in_transaction:
        raise RuntimeError("This operation requires a connection without an active transaction")
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
