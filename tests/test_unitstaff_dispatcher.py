"""Verify real aiogram routing and middleware without contacting Telegram."""
import os
from pathlib import Path
import subprocess
import sys


def test_unitstaff_through_real_dispatcher(tmp_path):
    root = Path(__file__).resolve().parents[1]
    script = r'''
import asyncio
import os
from pathlib import Path

from cryptography.fernet import Fernet

os.environ["BOT_TOKEN"] = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk"
os.environ["FERNET_KEY"] = Fernet.generate_key().decode("ascii")
os.environ["GROUP_ID"] = "-1000000000000"

from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage
from aiogram.types import Message, Update, User
from erpbot.core import runtime
from erpbot.bootstrap import initialize_runtime
from erpbot.core.settings import Settings
from erpbot.loader import register_handlers


class OfflineSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls = []

    async def close(self):
        pass

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, AnswerCallbackQuery):
            return True
        assert isinstance(method, (SendMessage, EditMessageText)), type(method)
        return Message(message_id=10, date=0,
                       chat={"id": 202, "type": "private"}, text=method.text)

    async def stream_content(self, *args, **kwargs):
        raise AssertionError("Network I/O is disabled")
        yield b""


async def main():
    application = initialize_runtime(Settings.from_env(data_directory=Path.cwd()), configure_logging=False)
    runtime.DB_PATH = str(Path.cwd() / "isolated.db")
    runtime.init_db()
    assert register_handlers() == 26
    with runtime.get_connection() as conn:
        conn.executemany("""INSERT INTO staff_mapping(staff_name,telegram_user_id,role)
            VALUES(?,?,?)""", [("Test viewer",202,"staff"), ("Test colleague",303,"staff")])
        viewer = conn.execute("SELECT staff_id FROM staff_mapping WHERE telegram_user_id=202").fetchone()[0]
        colleague = conn.execute("SELECT staff_id FROM staff_mapping WHERE telegram_user_id=303").fetchone()[0]
        conn.execute("INSERT INTO org_units(unit_code,unit_name) VALUES('test-office','Test Office')")
        unit = conn.execute("SELECT unit_id FROM org_units WHERE unit_code='test-office'").fetchone()[0]
        conn.executemany("INSERT INTO staff_unit_memberships(staff_id,unit_id) VALUES(?,?)",
                         [(viewer,unit),(colleague,unit)])
        conn.execute("INSERT INTO roles(role_code,role_name) VALUES('test-viewer','Test Viewer')")
        role = conn.execute("SELECT role_id FROM roles WHERE role_code='test-viewer'").fetchone()[0]
        conn.execute("""INSERT INTO role_permissions SELECT ?,permission_id FROM permissions
            WHERE permission_code='staff.view_unit'""", (role,))
        conn.execute("INSERT INTO staff_role_assignments(staff_id,role_id,unit_id) VALUES(?,?,?)",
                     (viewer,role,unit))

    session = OfflineSession()
    runtime.bot.session = session
    runtime.bot._me = User(id=123456789, is_bot=True, first_name="Test Bot", username="test_bot")
    chat = {"id":202,"type":"private"}
    user = {"id":202,"is_bot":False,"first_name":"Test viewer"}
    msg = {"message_id":10,"date":0,"chat":chat,"from":user,"text":"/unitstaff"}
    await runtime.dp.feed_update(runtime.bot, Update.model_validate({"update_id":1,"message":msg}))
    menu = session.calls[-1]
    assert isinstance(menu, SendMessage)
    assert [b.callback_data for row in menu.reply_markup.inline_keyboard for b in row] == [f"unitstaff_view_{unit}"]

    async def click(data, update_id):
        session.calls.clear()
        query = {"id":str(update_id),"from":user,"chat_instance":"test","data":data,
                 "message":dict(msg, **{"from":{"id":123456789,"is_bot":True,"first_name":"Bot"}})}
        await runtime.dp.feed_update(runtime.bot, Update.model_validate({"update_id":update_id,"callback_query":query}))

    await click(f"unitstaff_view_{unit}", 2)
    assert isinstance(session.calls[0], EditMessageText)
    assert "Test colleague" in session.calls[0].text
    await click("unitstaff_back", 3)
    assert isinstance(session.calls[0], EditMessageText)
    assert session.calls[0].reply_markup.inline_keyboard[0][0].callback_data == f"unitstaff_view_{unit}"
    with runtime.get_connection() as conn:
        conn.execute("UPDATE staff_role_assignments SET is_active=0 WHERE staff_id=?", (viewer,))
    await click(f"unitstaff_view_{unit}", 4)
    assert len(session.calls) == 1
    assert isinstance(session.calls[0], AnswerCallbackQuery) and session.calls[0].show_alert
    # The parent callback middleware must still guard the extracted child router.
    with runtime.get_connection() as conn:
        conn.execute("UPDATE staff_role_assignments SET is_active=1 WHERE staff_id=?", (viewer,))
        conn.execute("UPDATE staff_mapping SET is_active=0 WHERE staff_id=?", (viewer,))
    await click(f"unitstaff_view_{unit}", 5)
    assert len(session.calls) == 1 and isinstance(session.calls[0], AnswerCallbackQuery)
    assert session.calls[0].text == "حساب پرسنلی فعال و متصل لازم است."
    await application.close()
    print("OFFLINE DISPATCHER OK")


asyncio.run(main())
'''
    env = dict(os.environ, PYTHONPATH=str(root), PYTHONIOENCODING="utf-8")
    result = subprocess.run([sys.executable, "-c", script], cwd=tmp_path,
                            env=env, capture_output=True, text=True,
                            encoding="utf-8", timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OFFLINE DISPATCHER OK" in result.stdout
