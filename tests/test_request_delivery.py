"""Shared delivery preserves legacy topics, photos, escaping and committed requests."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import jdatetime
import pytest
from aiogram.types import Message, CallbackQuery
from erpbot.handlers.request_delivery import create_submitter
from erpbot.services.requests import RequestSubmissionError


TOPICS = {"مرخصی":2,"مساعده":3,"ماموریت":38,"تنخواه":57,
          "خرید ملزومات":70,"تحویل اموال":59,"عودت اموال":59}


@pytest.fixture
def delivery(leave_db,monkeypatch):
    reply = AsyncMock()
    monkeypatch.setattr(Message,"answer",reply)
    bot = SimpleNamespace(
        send_message=AsyncMock(return_value=SimpleNamespace(message_id=80,chat=SimpleNamespace(id=-999))),
        send_photo=AsyncMock(return_value=SimpleNamespace(message_id=81,chat=SimpleNamespace(id=-999))),
    )
    message = Message(message_id=10,date=0,chat={"id":202,"type":"private"},
                      from_user={"id":202,"is_bot":False,"first_name":"Telegram"},text="ثبت")
    submit = create_submitter(leave_db.connection,bot,-999,TOPICS,lambda:jdatetime.datetime(1405,7,24,12,30))
    return SimpleNamespace(submit=submit,bot=bot,message=message,reply=reply)


@pytest.mark.parametrize("kind",list(TOPICS)+["سایر"])
def test_delivery_topic_and_persistence_for_every_request_type(leave_db,delivery,kind):
    asyncio.run(delivery.submit(delivery.message,202,"کارمند",kind,"عنوان <الف>","شرح & ب","جزئیات","3"))
    method = delivery.bot.send_message.await_args.kwargs
    assert method["chat_id"] == -999 and method["message_thread_id"] == TOPICS.get(kind,-999)
    assert "عنوان &lt;الف&gt;" in method["text"] and "شرح &amp; ب" in method["text"]
    assert "REQ-1405-00001" in method["text"]
    assert method["reply_markup"].inline_keyboard[0][0].callback_data == "approve_1"
    row = leave_db.row(1)
    assert row["admin_msg_id"] == 80 and row["admin_chat_id"] == -999
    assert row["created_at"] == "1405/07/24 12:30" and row["month_tag"] == "1405/07"
    assert row["request_type"] == kind and row["telegram_info"] == "Telegram"
    delivery.reply.assert_awaited_once()


def test_photo_uses_petty_topic_and_keeps_sensitive_data_out_of_group(leave_db,delivery):
    asyncio.run(delivery.submit(delivery.message,202,"کارمند","تنخواه","مبلغ","شرح","جزئیات","0",
                                sensitive_data="cipher-text",photo_id="fake-photo"))
    method = delivery.bot.send_photo.await_args.kwargs
    assert method["message_thread_id"] == 57 and method["photo"] == "fake-photo"
    assert "cipher-text" not in method["caption"]
    delivery.bot.send_message.assert_not_awaited()
    assert leave_db.row(1)["admin_msg_id"] == 81
    assert leave_db.row(1)["sensitive_data"] == "cipher-text"


def test_delivery_failure_preserves_saved_request_and_informs_requester(leave_db,delivery):
    delivery.bot.send_message.side_effect = RuntimeError("offline delivery failure")
    asyncio.run(delivery.submit(delivery.message,202,"کارمند","مرخصی","نوع: استحقاقی","تاریخ","جزئیات","3"))
    assert leave_db.row(1)["req_code"] == "REQ-1405-00001"
    assert leave_db.row(1)["admin_msg_id"] is None
    assert "ثبت شد اما" in delivery.reply.await_args.args[0]


def test_callback_submission_notifies_assigned_replacement_after_commit(leave_db,delivery):
    callback = CallbackQuery(id="test",from_user=delivery.message.from_user,chat_instance="test",
                             message=delivery.message,data="leave_submit_final")
    asyncio.run(delivery.submit(callback,202,"کارمند","مرخصی","نوع: استحقاقی","تاریخ","جزئیات","3",replacement_staff_id=3))
    calls = delivery.bot.send_message.await_args_list
    assert len(calls) == 2 and calls[1].kwargs["chat_id"] == 303
    assert "جانشین &lt;الف&gt;" in calls[1].kwargs["text"]
    assert calls[1].kwargs["reply_markup"].inline_keyboard[0][0].callback_data == "replapp_1"
    with leave_db.connection() as conn:
        assert conn.execute("SELECT staff_id,response FROM request_replacements").fetchone()[:] == (3,None)


def test_submission_failure_sends_no_success_or_admin_message(leave_db,delivery):
    with leave_db.connection() as conn:
        conn.execute("UPDATE staff_mapping SET is_active=0 WHERE staff_id=2")
    with pytest.raises(RequestSubmissionError):
        asyncio.run(delivery.submit(delivery.message,202,"کارمند","مرخصی","نوع: استحقاقی","تاریخ","جزئیات","3"))
    delivery.bot.send_message.assert_not_awaited()
    delivery.reply.assert_not_awaited()


def test_request_and_replacement_insert_roll_back_together(leave_db,delivery):
    with leave_db.connection() as conn:
        conn.execute("CREATE TRIGGER fail_assignment BEFORE INSERT ON request_replacements BEGIN SELECT RAISE(ABORT,'assignment failed'); END")
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError,match="assignment failed"):
        asyncio.run(delivery.submit(delivery.message,202,"کارمند","مرخصی","نوع: استحقاقی","تاریخ","جزئیات","3",replacement_staff_id=3))
    with leave_db.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM requests").fetchone()[0] == 0
    delivery.reply.assert_not_awaited()
