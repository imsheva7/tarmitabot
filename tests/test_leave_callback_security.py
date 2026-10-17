"""Isolated security tests for annual-leave Telegram callbacks.

No bot startup, Telegram network access, or production database is required.
"""

import asyncio
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from erpbot.handlers.leave import create_router
from erpbot.services import leave_workflow as workflow


class FakeState:
    def __init__(self, initial=None):
        self.data = dict(initial or {})

    async def get_data(self):
        return dict(self.data)

    async def update_data(self, **kwargs):
        self.data.update(kwargs)


class FakeMessage:
    def __init__(self, *, message_id=50, chat_id=900):
        self.message_id = message_id
        self.chat = SimpleNamespace(id=chat_id)
        self.text = "درخواست مرخصی"
        self.caption = None
        self.photo = None
        self.answer = AsyncMock(
            return_value=SimpleNamespace(
                message_id=77,
                chat=SimpleNamespace(id=chat_id),
            )
        )
        self.edit_text = AsyncMock()
        self.edit_caption = AsyncMock()
        self.edit_reply_markup = AsyncMock()


class FakeCallback:
    def __init__(self, data, *, user_id=1, message_id=50, chat_id=900):
        self.data = data
        self.from_user = SimpleNamespace(id=user_id)
        self.message = FakeMessage(message_id=message_id, chat_id=chat_id)
        self.answer = AsyncMock()


@pytest.fixture
def handler_env(monkeypatch):
    row = (100, "REQ-TEST", "مرخصی", "نوع: استحقاقی", "3")
    service_calls = []
    service_result = {"outcome": "needs_override", "balance": 2.0}
    authorized_users = {1}

    @contextmanager
    def connection():
        yield object()

    def approval(conn, req_id, actor_id, *, exceptional=False):
        assert actor_id in authorized_users
        service_calls.append((req_id, exceptional))
        return SimpleNamespace(**service_result)

    monkeypatch.setattr(workflow, "approve_leave", approval)
    monkeypatch.setattr(workflow, "is_main_admin", lambda conn, uid: uid in authorized_users)
    monkeypatch.setattr(workflow, "approval_request", lambda conn, req_id: row)
    bot = SimpleNamespace(send_message=AsyncMock())
    router = create_router(connection, bot, submit_request=AsyncMock())
    handler = next(h.callback for h in router.callback_query.handlers if h.callback.__name__ == "handle_leave_decision")
    return SimpleNamespace(
        handler=handler,
        calls=service_calls,
        result=service_result,
        authorized=authorized_users,
        bot=bot,
    )


def run(handler, callback, state):
    asyncio.run(handler(callback, state))


def test_unauthorized_user_cannot_approve_or_override(handler_env):
    for action in ("approve_10", "leaveoverride_10"):
        callback = FakeCallback(action, user_id=999)
        run(handler_env.handler, callback, FakeState())
        callback.answer.assert_awaited()
    assert handler_env.calls == []


def test_override_without_first_click_is_rejected(handler_env):
    callback = FakeCallback("leaveoverride_10", message_id=77)
    run(handler_env.handler, callback, FakeState())
    assert handler_env.calls == []
    callback.answer.assert_awaited()


def test_first_click_creates_warning_but_does_not_debit(handler_env):
    callback = FakeCallback("approve_10")
    state = FakeState()
    run(handler_env.handler, callback, state)
    assert handler_env.calls == [(10, False)]
    assert state.data["leave_override_request_id"] == 10
    assert state.data["leave_override_admin_id"] == 1
    assert state.data["leave_override_message_id"] == 77
    assert state.data["leave_override_chat_id"] == 900
    callback.message.answer.assert_awaited_once()


@pytest.mark.parametrize(
    "override",
    [
        {"leave_override_request_id": 11},
        {"leave_override_admin_id": 2},
        {"leave_override_message_id": 76},
        {"leave_override_chat_id": 901},
    ],
)
def test_mismatched_override_context_is_rejected(handler_env, override):
    saved = {
        "leave_override_request_id": 10,
        "leave_override_admin_id": 1,
        "leave_override_message_id": 77,
        "leave_override_chat_id": 900,
    }
    saved.update(override)
    callback = FakeCallback("leaveoverride_10", message_id=77)
    run(handler_env.handler, callback, FakeState(saved))
    assert handler_env.calls == []


def test_valid_second_click_approves_and_clears_context(handler_env):
    state = FakeState()
    run(handler_env.handler, FakeCallback("approve_10"), state)
    handler_env.result.update(outcome="exceptional_approved", balance=-1.0)
    callback = FakeCallback("leaveoverride_10", message_id=77)
    run(handler_env.handler, callback, state)
    assert handler_env.calls == [(10, False), (10, True)]
    assert state.data["leave_override_request_id"] is None
    assert state.data["leave_override_message_id"] is None
    callback.message.edit_text.assert_awaited_once()
    assert callback.message.edit_text.await_args.kwargs["reply_markup"] is None
    handler_env.bot.send_message.assert_awaited_once()


def test_old_button_rejected_after_success(handler_env):
    state = FakeState()
    run(handler_env.handler, FakeCallback("approve_10"), state)
    handler_env.result.update(outcome="exceptional_approved", balance=-1.0)
    run(handler_env.handler, FakeCallback("leaveoverride_10", message_id=77), state)
    run(handler_env.handler, FakeCallback("leaveoverride_10", message_id=77), state)
    assert handler_env.calls == [(10, False), (10, True)]
