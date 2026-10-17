"""Consistent temporary SQLite snapshots, including committed WAL changes."""
from contextlib import contextmanager, closing
import os
import sqlite3
import tempfile
from pathlib import Path


@contextmanager
def database_snapshot(database_path):
    path = None
    try:
        with tempfile.NamedTemporaryFile(prefix='erpbot_backup_', suffix='.sqlite3', delete=False) as temp:
            path = temp.name
        uri = Path(database_path).resolve().as_uri() + '?mode=ro'
        with closing(sqlite3.connect(uri, uri=True, timeout=10)) as source:
            with closing(sqlite3.connect(path, timeout=10)) as destination:
                source.backup(destination)
        yield path
    finally:
        if path is not None:
            os.remove(path)
