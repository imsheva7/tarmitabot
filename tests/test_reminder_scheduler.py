"""Regression tests against the independent scheduler; no runtime or network."""
import asyncio
import html
import logging
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from erpbot.scheduler.reminders import run_scheduler as reminder_scheduler

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
JOBS_FILE = PROJECT_ROOT / "erpbot" / "scheduler" / "jobs.py"


class FakeClock:
    def __init__(self, minute):
        self.minute = minute
        self.year = 1405
        self.month = 7
        self.day = 24

    def strftime(self, pattern):
        return {
            "%Y/%m/%d": "1405/07/24",
            "%H:%M": self.minute,
        }[pattern]

    def togregorian(self):
        return SimpleNamespace(strftime=lambda pattern: "Friday")


class FakeBot:
    def __init__(self, failures=0):
        self.failures = failures
        self.calls = []

    async def send_message(self, **kwargs):
        self.calls.append(kwargs)
        if self.failures:
            self.failures -= 1
            raise RuntimeError("Simulated Telegram outage")
        return SimpleNamespace(message_id=len(self.calls))


@pytest.fixture
def database():
    connection = sqlite3.connect(":memory:")
    connection.execute(
        """CREATE TABLE reminders (
            id INTEGER PRIMARY KEY,
            chat_id INTEGER,
            message_thread_id TEXT,
            user_name TEXT,
            text_content TEXT,
            remind_type TEXT,
            is_sent INTEGER,
            remind_at TEXT,
            day_of_week TEXT,
            remind_time TEXT,
            day_of_month INTEGER,
            last_fired TEXT
        )"""
    )
    connection.execute(
        """INSERT INTO reminders
           (id, chat_id, message_thread_id, user_name, text_content,
            remind_type, is_sent, remind_at)
           VALUES (1, 1234, NULL, 'Test User', 'Test reminder',
                   'once', 0, '1405/07/24 09:00')"""
    )
    connection.commit()
    yield connection
    connection.close()


def run_scheduler(database, *, failures, minutes):
    bot = FakeBot(failures=failures)
    iterations = iter(minutes)
    current = [None]

    async def fake_sleep(seconds):
        assert seconds == 15
        try:
            current[0] = FakeClock(next(iterations))
        except StopIteration:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(reminder_scheduler(lambda:database,bot,lambda:current[0],sleep=fake_sleep))

    is_sent = database.execute(
        "SELECT is_sent FROM reminders WHERE id = 1"
    ).fetchone()[0]
    return bot, is_sent


def test_success_marks_one_time_reminder_sent(database):
    bot, is_sent = run_scheduler(database, failures=0, minutes=["09:00"])
    assert len(bot.calls) == 1
    assert is_sent == 1


def test_failed_send_does_not_mark_reminder_sent(database):
    bot, is_sent = run_scheduler(database, failures=1, minutes=["09:00"])
    assert len(bot.calls) == 1
    assert is_sent == 0


def test_failed_reminder_is_retried_next_minute(database):
    bot, is_sent = run_scheduler(
        database, failures=1, minutes=["09:00", "09:01"]
    )
    assert len(bot.calls) == 2
    assert is_sent == 1


def test_success_is_not_sent_twice(database):
    bot, is_sent = run_scheduler(
        database, failures=0, minutes=["09:00", "09:01"]
    )
    assert len(bot.calls) == 1
    assert is_sent == 1
