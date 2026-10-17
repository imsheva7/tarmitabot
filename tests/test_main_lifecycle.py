"""Initialize before registration; clean up even if startup or polling fails."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import erpbot.main as entry


@pytest.fixture
def lifecycle(monkeypatch):
    events = []

    async def poll(*args, **kwargs):
        events.append("poll")
        await asyncio.sleep(0)

    async def close():
        events.append("close")

    app = SimpleNamespace(bot=object(), dispatcher=SimpleNamespace(start_polling=AsyncMock(side_effect=poll)),
                          close=AsyncMock(side_effect=close))

    def initialize():
        events.append("initialize")
        return app

    monkeypatch.setattr(entry, "initialize_runtime", initialize)
    monkeypatch.setattr(entry.runtime, "init_db", lambda: events.append("database"))
    monkeypatch.setattr(entry, "register_handlers", lambda: events.append("handlers"))
    monkeypatch.setattr(entry, "_get_schedulers", lambda: ())
    return app, events


def test_main_initializes_database_and_handlers_before_polling(lifecycle):
    app, events = lifecycle
    asyncio.run(entry.main())
    assert events == ["initialize", "database", "handlers", "poll", "close"]
    app.dispatcher.start_polling.assert_awaited_once_with(app.bot, close_bot_session=False)
    app.close.assert_awaited_once()


@pytest.mark.parametrize("failure", ["database", "handlers", "poll"])
def test_resources_close_on_startup_or_polling_failure(lifecycle, monkeypatch, failure):
    app, events = lifecycle

    def fail():
        raise RuntimeError("test failure")

    if failure == "database":
        monkeypatch.setattr(entry.runtime, "init_db", fail)
    elif failure == "handlers":
        monkeypatch.setattr(entry, "register_handlers", fail)
    else:
        app.dispatcher.start_polling.side_effect = RuntimeError("test failure")
    with pytest.raises(RuntimeError, match="test failure"):
        asyncio.run(entry.main())
    assert events[-1] == "close"
    app.close.assert_awaited_once()
    if failure != "poll":
        app.dispatcher.start_polling.assert_not_awaited()


def test_background_tasks_finish_before_application_resources_close(lifecycle, monkeypatch):
    app, events = lifecycle

    async def scheduler():
        events.append("scheduler start")
        try:
            await asyncio.sleep(3600)
        finally:
            events.append("scheduler stop")

    monkeypatch.setattr(entry, "_get_schedulers", lambda: (scheduler,))
    asyncio.run(entry.main())
    assert "scheduler start" in events
    assert events.index("scheduler stop") < events.index("close")
