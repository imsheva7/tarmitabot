r"""Interactive Phase 5B test bot with synthetic data and no background jobs.

Run with .venv312\Scripts\python.exe phase5b_live_test.py.
The token is entered through getpass and is never saved by this script.
"""
import asyncio
import argparse
from dataclasses import replace
import getpass
import os
from pathlib import Path
import re
import secrets
import tempfile


def validate_test_token(token):
    if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", token):
        raise ValueError("Enter only the bot token copied from BotFather, without quotes or a URL.")


def validate_test_bot(username):
    if (username or "").casefold() != "armitaamani_bot":
        raise RuntimeError("Only @ArmitaAmani_bot is allowed in this test runner.")


def explain_failure(exc):
    from aiogram.exceptions import (
        TelegramConflictError, TelegramNetworkError, TelegramNotFound,
        TelegramUnauthorizedError,
    )
    if isinstance(exc, (TelegramNotFound, TelegramUnauthorizedError)):
        return (
            "Telegram did not accept this request. The test bot token may be incorrect or revoked.\n"
            "In @BotFather: /mybots -> select your TEST bot -> API Token.\n"
            "Copy only the full token (digits:letters), without quotes, 'bot', or a URL.\n"
            "Run this script again and paste it at the hidden prompt. Do not share the token in chat."
        )
    if isinstance(exc, TelegramNetworkError):
        return "Could not reach Telegram. Check the connection used by Python, then retry."
    if isinstance(exc, TelegramConflictError):
        return "Another process is polling this test bot. Stop that test bot process and retry."
    if isinstance(exc, ValueError):
        return "Check the token format: paste only the full BotFather token, without quotes or a URL."
    if isinstance(exc, RuntimeError) and str(exc) == "Only @ArmitaAmani_bot is allowed in this test runner.":
        return str(exc)
    return f"Test bot could not continue ({type(exc).__name__})."


def seed_tester(conn, telegram_id):
    """Bind one ordinary tester to two units; grant visibility in only one."""
    conn.execute("INSERT INTO staff_mapping(staff_name,telegram_user_id,role) VALUES(?,?,'staff')",
                 ("کاربر آزمایش", telegram_id))
    tester = conn.execute("SELECT staff_id FROM staff_mapping WHERE telegram_user_id=?",
                          (telegram_id,)).fetchone()[0]
    conn.executemany("INSERT INTO org_units(unit_code,unit_name) VALUES(?,?)", [
        ("test-office", "واحد آزمایشی اداری"),
        ("test-warehouse", "واحد آزمایشی انبار"),
    ])
    units = dict(conn.execute("SELECT unit_code,unit_id FROM org_units"))
    office, warehouse = units["test-office"], units["test-warehouse"]
    conn.executemany("INSERT INTO staff_unit_memberships(staff_id,unit_id) VALUES(?,?)",
                     [(tester, office), (tester, warehouse)])
    for name, unit, active in [
        ("همکار آزمایشی اداری", office, 1),
        ("همکار آزمایشی انبار", warehouse, 1),
        ("همکار غیرفعال", office, 0),
    ]:
        cursor = conn.execute("INSERT INTO staff_mapping(staff_name,is_active) VALUES(?,?)", (name, active))
        conn.execute("INSERT INTO staff_unit_memberships(staff_id,unit_id) VALUES(?,?)",
                     (cursor.lastrowid, unit))
    conn.execute("INSERT INTO roles(role_code,role_name) VALUES('test-viewer','مشاهده آزمایشی')")
    role = conn.execute("SELECT role_id FROM roles WHERE role_code='test-viewer'").fetchone()[0]
    conn.execute("""INSERT INTO role_permissions SELECT ?,permission_id FROM permissions
        WHERE permission_code='staff.view_unit'""", (role,))
    conn.execute("INSERT INTO staff_role_assignments(staff_id,role_id,unit_id) VALUES(?,?,?)",
                 (tester, role, office))


TEST_GROUP_ID = -1004252035726


def configure_test_group(runtime, group_id):
    if group_id != TEST_GROUP_ID:
        raise ValueError("Unsupported test group")
    # A plain test group has no production forum topics.
    for name in ("TOPIC_LEAVE", "TOPIC_ADVANCE", "TOPIC_MISSION", "TOPIC_PETTY",
                 "TOPIC_PURCHASE", "TOPIC_ASSETS", "TOPIC_INSURANCE"):
        setattr(runtime, name, None)


def configure_handlers(runtime, join_code, *, admin_mode=False, group_id=None):
    from aiogram.filters import Command, CommandObject
    from aiogram.types import Message

    tester_id = None

    @runtime.dp.message(Command("start"))
    async def join(message: Message, command: CommandObject):
        nonlocal tester_id
        if message.chat.type != "private":
            return
        if tester_id == message.from_user.id:
            if admin_mode:
                await message.answer("برای بازکردن پنل مدیریت /admin را بفرست.")
                return
            await message.answer("حساب آزمایشی آماده است. دستور /unitstaff را بفرست.")
            return
        if tester_id is not None or not secrets.compare_digest(command.args or "", join_code):
            await message.answer("برای ورود از لینک نمایش‌داده‌شده در ترمینال استفاده کن.")
            return
        with runtime.get_connection() as conn:
            seed_tester(conn, message.from_user.id)
            if admin_mode:
                conn.execute("UPDATE staff_mapping SET role='main_admin' WHERE telegram_user_id=?",
                             (message.from_user.id,))
                if group_id is not None:
                    staff_id = conn.execute('SELECT staff_id FROM staff_mapping WHERE telegram_user_id=?',
                                            (message.from_user.id,)).fetchone()[0]
                    conn.execute('UPDATE staff_mapping SET leave_balance=10 WHERE staff_id=?', (staff_id,))
                    conn.execute('''INSERT INTO leave_ledger
                        (staff_id,staff_name,change_amount,description,registered_by,created_at)
                        VALUES(?,?,10,?,?,?)''',
                        (staff_id, 'کاربر آزمایش', 'مانده اولیه آزمایشی', 'test runner',
                         runtime.get_current_tehran_time().strftime('%Y/%m/%d %H:%M')))
        tester_id = message.from_user.id
        if admin_mode:
            await message.answer(
                "حساب مدیر اصلی آزمایشی در دیتابیس جدا آماده شد.\n"
                "برای پنل مدیریت /admin را بفرست. فقط داده ساختگی وارد کن.\n"
                + ("گروه آزمایشی متصل است؛ مانده اولیه شما ۱۰ روز است."
                   if group_id is not None else "ارسال درخواست به گروه در این محیط پیکربندی نشده است.")
            )
            return
        await message.answer(
            "حساب تو با نقش پرسنل عادی آماده شد.\n"
            "۱. /unitstaff را بفرست؛ فقط واحد اداری باید نمایش داده شود.\n"
            "۲. واحد را باز کن؛ فقط خودت و همکار آزمایشی اداری باید دیده شوید.\n"
            "۳. /test_revoke را بفرست و روی بازگشتِ پیام قبلی بزن؛ دسترسی باید حذف شود.\n"
            "۴. برای آزمایش دکمه قدیمی واحد، /test_grant و سپس /unitstaff را بفرست؛ "
            "بدون انتخاب واحد، /test_revoke را بفرست و دکمه واحدِ پیام قبلی را بزن.\n"
            "۵. /unitstaff پس از لغو مجوز باید پیام نداشتن مجوز بدهد."
        )

    @runtime.dp.message(Command("test_revoke", "test_grant"))
    async def change_access(message: Message, command: CommandObject):
        if admin_mode:
            return
        if message.chat.type != "private" or message.from_user.id != tester_id:
            return
        active = int(command.command == "test_grant")
        with runtime.get_connection() as conn:
            conn.execute("""UPDATE staff_role_assignments SET is_active=? WHERE staff_id=(
                SELECT staff_id FROM staff_mapping WHERE telegram_user_id=?)""",
                         (active, tester_id))
        await message.answer("مجوز آزمایشی فعال شد." if active else "مجوز آزمایشی لغو شد؛ دکمه قبلی را آزمایش کن.")

    if admin_mode:
        @runtime.dp.message(Command("test_group"))
        async def identify_group(message: Message):
            if (message.chat.type not in ("group", "supergroup") or
                    message.from_user is None or message.from_user.id != tester_id):
                return
            await message.answer(f"شناسه گروه آزمایشی: {message.chat.id}")


async def main(*, admin_mode=False, group_id=None):
    if group_id is not None and (not admin_mode or group_id != TEST_GROUP_ID):
        raise RuntimeError("Use --admin with the approved test group only.")
    token = getpass.getpass("Test bot token (hidden): ").strip()
    validate_test_token(token)

    # Configure isolation explicitly before creating application resources.
    from cryptography.fernet import Fernet
    root = Path(__file__).resolve().parent
    runs = root / "sandbox" / "phase5b"
    runs.mkdir(parents=True, exist_ok=True)
    run_dir = Path(tempfile.mkdtemp(prefix="run-", dir=runs))
    os.chdir(run_dir)
    from erpbot.bootstrap import initialize_runtime
    from erpbot.core.settings import Settings
    from erpbot.core import runtime
    from erpbot.loader import register_handlers
    settings = Settings.from_env({
        "BOT_TOKEN": token,
        "FERNET_KEY": Fernet.generate_key().decode("ascii"),
        "ENCRYPTION_KEY_PATH": str(run_dir / "test-only.key"),
        "GROUP_ID": str(group_id if group_id is not None else -1000000000000),
    }, data_directory=run_dir)
    settings = replace(settings, database_path=str(run_dir / "test-only.db"))
    application = initialize_runtime(settings)
    try:
        runtime.init_db()
        join_code = secrets.token_urlsafe(24)
        if group_id is not None:
            configure_test_group(runtime, group_id)
        configure_handlers(runtime, join_code, admin_mode=admin_mode, group_id=group_id)
        register_handlers()
        print("Checking test bot token (getMe)...", flush=True)
        me = await runtime.bot.get_me()
        validate_test_bot(me.username)
        print(f"Token accepted: @{me.username}. Checking webhook...", flush=True)
        hook = await runtime.bot.get_webhook_info()
        if hook.url:
            print("This bot has a webhook. Use a separate test bot without a webhook.")
            return
        print(f"\nTest bot: @{me.username}")
        print(f"Test database: {runtime.DB_PATH}")
        print(f"Open this private test link: https://t.me/{me.username}?start={join_code}")
        print("Keep this terminal open. Stop with Ctrl+C.\n", flush=True)
        # No scheduler, production token, production database, or webhook deletion.
        await runtime.dp.start_polling(runtime.bot, allowed_updates=["message", "callback_query"],
                                       close_bot_session=False)
    finally:
        await application.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--admin", action="store_true", help="Use a synthetic main administrator in a fresh test database.")
    parser.add_argument("--group-id", type=int, choices=[TEST_GROUP_ID], help="Approved private test group.")
    args = parser.parse_args()
    try:
        asyncio.run(main(admin_mode=args.admin, group_id=args.group_id))
    except KeyboardInterrupt:
        print("Test bot stopped.")
    except Exception as exc:
        # Avoid dumping HTTP objects or credentials into the console.
        print(explain_failure(exc))
        raise SystemExit(1)
