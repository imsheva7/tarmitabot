"""Isolated tests for the weekly SQLite backup in erpbot/scheduler/jobs.py.

No real Telegram bot, runtime import, or production database is used.
"""
import asyncio
from contextlib import closing
from pathlib import Path
import sqlite3
from erpbot.core import backup as snapshots
import jdatetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


class FakeTime:
    day = 10

    def strftime(self, fmt):
        return {'%Y/%m/%d': '1405/07/10', '%H:%M': '08:00'}[fmt]

    def togregorian(self):
        return SimpleNamespace(strftime=lambda fmt: 'Monday')

    def date(self):
        return jdatetime.date(1405,7,10)


class StopAfterOneTick:
    def __init__(self):
        self.calls = 0

    async def __call__(self, seconds):
        self.calls += 1
        if self.calls > 1:
            raise asyncio.CancelledError()


def load_background_scheduler(db_path, bot, clock):
    from erpbot.core.database import connect
    from erpbot.scheduler.jobs import background_schedulers
    return lambda: background_schedulers(lambda: connect(db_path), bot, FakeTime, db_path, sleep=clock)


def make_db(path):
    # Keep a WAL writer connection open to verify the backup includes committed WAL changes.
    conn = sqlite3.connect(path)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA wal_autocheckpoint=0')
    conn.execute('CREATE TABLE staff_mapping (telegram_user_id INTEGER, role TEXT, is_active INTEGER)')
    conn.execute('CREATE TABLE vehicle_insurances (car_code TEXT, car_name TEXT, plate_number TEXT, insurance_company TEXT, third_party_date TEXT, body_date TEXT)')
    conn.execute('CREATE TABLE test_data (value TEXT)')
    conn.execute("INSERT INTO staff_mapping VALUES (1001, 'main_admin', 1)")
    conn.execute("INSERT INTO test_data VALUES ('committed-in-wal')")
    conn.commit()
    return conn


@pytest.mark.parametrize('delivery_fails', [False, True])
def test_backup_is_consistent_and_temporary_file_is_removed(tmp_path, monkeypatch, delivery_fails):
    db_path = tmp_path / 'test.sqlite3'
    source = make_db(db_path)
    created = []
    real_named_temp = snapshots.tempfile.NamedTemporaryFile

    def track_temp(*args, **kwargs):
        obj = real_named_temp(*args, **kwargs)
        created.append(obj.name)
        return obj

    monkeypatch.setattr(snapshots.tempfile, 'NamedTemporaryFile', track_temp)

    async def send_document(*, chat_id, document, caption):
        assert chat_id == 1001
        assert document.filename.endswith('.sqlite3')
        assert Path(document.path).is_file()
        with closing(sqlite3.connect(document.path)) as copy:
            assert copy.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            assert copy.execute('SELECT value FROM test_data').fetchone()[0] == 'committed-in-wal'
        if delivery_fails:
            raise RuntimeError('simulated Telegram failure')

    bot = SimpleNamespace(send_document=AsyncMock(side_effect=send_document), send_message=AsyncMock())
    clock = StopAfterOneTick()
    try:
        scheduler = load_background_scheduler(db_path, bot, clock)
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(scheduler())
        assert bot.send_document.await_count == 1
        assert len(created) == 1
        assert not Path(created[0]).exists()
        assert source.execute('SELECT value FROM test_data').fetchone()[0] == 'committed-in-wal'
    finally:
        source.close()


def test_no_backup_when_no_active_main_admin(tmp_path, monkeypatch):
    db_path = tmp_path / 'test.sqlite3'
    source = make_db(db_path)
    source.execute('UPDATE staff_mapping SET is_active = 0')
    source.commit()
    created = []
    real_named_temp = snapshots.tempfile.NamedTemporaryFile

    def track_temp(*args, **kwargs):
        obj = real_named_temp(*args, **kwargs)
        created.append(obj.name)
        return obj

    monkeypatch.setattr(snapshots.tempfile, 'NamedTemporaryFile', track_temp)
    bot = SimpleNamespace(send_document=AsyncMock(), send_message=AsyncMock())
    try:
        scheduler = load_background_scheduler(db_path, bot, StopAfterOneTick())
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(scheduler())
        bot.send_document.assert_not_awaited()
        assert created == []
    finally:
        source.close()
