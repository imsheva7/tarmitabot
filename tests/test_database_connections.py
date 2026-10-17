"""SQLite lifecycle regression checks against real, isolated databases."""
import sqlite3

import pytest

from erpbot.core.database import connect


def test_connection_is_lazy_and_commits_rows(tmp_path):
    path = tmp_path / "test.db"
    context = connect(path)
    assert not path.exists()
    with context as conn:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 10000
        conn.execute("CREATE TABLE entries(id INTEGER PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO entries(value) VALUES('persisted')")
    with connect(path) as check:
        row = check.execute("SELECT * FROM entries").fetchone()
        assert isinstance(row, sqlite3.Row)
        assert row["value"] == "persisted"
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


@pytest.mark.parametrize("failure", [RuntimeError, KeyboardInterrupt])
def test_failure_rolls_back_and_closes_connection(tmp_path, failure):
    path = tmp_path / "test.db"
    with connect(path) as conn:
        conn.execute("CREATE TABLE entries(value TEXT)")
    with pytest.raises(failure):
        with connect(path) as failed:
            failed.execute("INSERT INTO entries VALUES('must rollback')")
            raise failure("test failure")
    with connect(path) as check:
        assert check.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == 0
    with pytest.raises(sqlite3.ProgrammingError):
        failed.execute("SELECT 1")


def test_foreign_key_failure_rolls_back_entire_transaction(tmp_path):
    path = tmp_path / "test.db"
    with connect(path) as conn:
        conn.execute("CREATE TABLE parent(id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE child(parent_id INTEGER REFERENCES parent(id))")
    with pytest.raises(sqlite3.IntegrityError):
        with connect(path) as conn:
            conn.execute("INSERT INTO parent VALUES(1)")
            conn.execute("INSERT INTO child VALUES(999)")
    with connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM parent").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM child").fetchone()[0] == 0


def test_two_database_paths_do_not_share_data(tmp_path):
    for name, value in [("one.db", "one"), ("two.db", "two")]:
        with connect(tmp_path / name, timeout=2) as conn:
            assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 2000
            conn.execute("CREATE TABLE entries(value TEXT)")
            conn.execute("INSERT INTO entries VALUES(?)", (value,))
    with connect(tmp_path / "one.db") as conn:
        assert conn.execute("SELECT value FROM entries").fetchone()[0] == "one"
    with connect(tmp_path / "two.db") as conn:
        assert conn.execute("SELECT value FROM entries").fetchone()[0] == "two"
