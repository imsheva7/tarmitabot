"""Startup contracts without polling, production credentials, or network I/O."""
import asyncio
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from erpbot.bootstrap import Application, create_application
from erpbot.core.settings import ConfigurationError, Settings


def run_isolated(tmp_path, script):
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, PYTHONPATH=str(root), PYTHONIOENCODING="utf-8")
    env.pop("BOT_TOKEN", None)
    env.pop("FERNET_KEY", None)
    env["GROUP_ID"] = "invalid-until-explicit-startup"
    result = subprocess.run([sys.executable, "-c", script], cwd=tmp_path, env=env,
                            capture_output=True, text=True, encoding="utf-8", timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr


def test_import_runtime_main_and_loader_does_not_initialize_resources(tmp_path):
    run_isolated(tmp_path, """
import logging
from pathlib import Path
import sys
before = list(logging.getLogger().handlers)
import main
import erpbot.main
import erpbot.loader
from erpbot.core import runtime
assert runtime.bot is None and runtime.dp is None
assert runtime.cipher_suite is None and runtime._settings is None
assert runtime.DB_PATH is None
assert 'erpbot.scheduler.jobs' not in sys.modules
assert 'erpbot.handlers.024_admin' not in sys.modules
assert list(logging.getLogger().handlers) == before
assert list(Path.cwd().iterdir()) == []
""")


def test_missing_token_fails_before_creating_key_or_log(tmp_path):
    settings = Settings.from_env({}, data_directory=tmp_path)
    with pytest.raises(ConfigurationError):
        create_application(settings)
    assert list(tmp_path.iterdir()) == []


def test_malformed_token_fails_before_creating_key(tmp_path):
    from aiogram.utils.token import TokenValidationError
    settings = Settings.from_env({"BOT_TOKEN": "malformed"}, data_directory=tmp_path)
    with pytest.raises(TokenValidationError):
        create_application(settings, configure_logging=False)
    assert list(tmp_path.iterdir()) == []


def test_initialization_is_explicit_reused_and_cannot_rebind_legacy_handlers(tmp_path):
    run_isolated(tmp_path, r'''
import asyncio
from dataclasses import replace
from pathlib import Path
import sys
from erpbot.bootstrap import initialize_runtime
from erpbot.core import runtime
from erpbot.core.settings import Settings
from erpbot.loader import register_handlers

for operation in (register_handlers, runtime.get_connection):
    try:
        operation()
    except RuntimeError as exc:
        assert 'initialize_runtime' in str(exc)
    else:
        raise AssertionError('Uninitialized runtime was used')
assert 'erpbot.handlers.024_admin' not in sys.modules
import erpbot.scheduler.jobs
assert not hasattr(erpbot.scheduler.jobs, 'bot')
assert not hasattr(erpbot.scheduler.jobs, 'dp')
assert list(Path.cwd().iterdir()) == []

settings = Settings.from_env({'BOT_TOKEN':'123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk'},
                             data_directory=Path.cwd())
app = initialize_runtime(settings, configure_logging=False)
assert runtime.bot is app.bot and runtime.dp is app.dispatcher
assert initialize_runtime(settings, configure_logging=False) is app
assert initialize_runtime() is app
assert not Path(settings.database_path).exists()
assert runtime.decrypt_data(runtime.encrypt_data('test data')) == 'test data'
assert runtime.encrypt_data('') == runtime.decrypt_data('') == ''
runtime.init_db()
assert register_handlers() == 26
counts = (len(runtime.dp.message.handlers), len(runtime.dp.callback_query.handlers), len(runtime.dp.sub_routers))
assert register_handlers() == 26
assert counts == (len(runtime.dp.message.handlers), len(runtime.dp.callback_query.handlers), len(runtime.dp.sub_routers))
assert not any(name.startswith('erpbot.handlers.') and name.rsplit('.',1)[-1][:3].isdigit() for name in sys.modules)
from erpbot.scheduler import jobs
from erpbot.main import _get_schedulers
background, reminders = _get_schedulers()
assert background.args[1] is app.bot and reminders.args[1] is app.bot
assert background.args[3] == runtime.DB_PATH
try:
    initialize_runtime(replace(settings, group_id=-100999), configure_logging=False)
except RuntimeError as exc:
    assert 'different settings' in str(exc)
else:
    raise AssertionError('An existing application was rebound')
asyncio.run(app.close())
try:
    initialize_runtime(settings, configure_logging=False)
except RuntimeError as exc:
    assert 'closed' in str(exc)
else:
    raise AssertionError('A closed application was reused')
''')


def test_failed_key_loading_does_not_partially_bind_runtime_and_can_retry(tmp_path):
    run_isolated(tmp_path, r'''
import asyncio
from dataclasses import replace
from pathlib import Path
from cryptography.fernet import Fernet
from erpbot.bootstrap import initialize_runtime
from erpbot.core import runtime
from erpbot.core.settings import Settings
settings = Settings.from_env({'BOT_TOKEN':'123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk'},
                             data_directory=Path.cwd())
Path(settings.database_path).write_bytes(b'existing database fixture')
try:
    initialize_runtime(settings, configure_logging=False)
except RuntimeError as exc:
    assert 'Encryption key missing' in str(exc)
else:
    raise AssertionError('A key was silently rotated')
assert runtime._application is None and runtime.bot is None and runtime.dp is None
assert not Path(settings.encryption_key_path).exists()
app = initialize_runtime(replace(settings, fernet_key=Fernet.generate_key().decode()), configure_logging=False)
assert Path(settings.database_path).read_bytes() == b'existing database fixture'
asyncio.run(app.close())
''')


def test_live_test_entrypoint_keeps_data_and_environment_isolated(tmp_path):
    run_isolated(tmp_path, r'''
import asyncio
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from aiogram import Bot, Dispatcher
from aiogram.types import User
import phase5b_live_test as entry
from erpbot.core import runtime
root = Path.cwd()
database = root / 'enterprise_requests.db'
database.write_bytes(b'original database fixture')
key = root / 'secret.key'
key.write_bytes(b'original key fixture')
entry.__file__ = str(root / 'phase5b_live_test.py')
entry.getpass.getpass = lambda prompt: '123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk'
Bot.get_me = AsyncMock(return_value=User(id=123456789, is_bot=True, first_name='Test', username='ArmitaAmani_bot'))
Bot.get_webhook_info = AsyncMock(return_value=SimpleNamespace(url=''))

async def poll(bot, **kwargs):
    assert Path(runtime.DB_PATH).resolve() != database
    assert Path(runtime.DB_PATH).is_file()
    assert runtime._settings.enable_initial_staff_seed is False
    assert runtime._settings.bootstrap_admin_telegram_id is None
    assert kwargs['close_bot_session'] is False

Dispatcher.start_polling = AsyncMock(side_effect=poll)
before = dict(os.environ)
asyncio.run(entry.main())
assert dict(os.environ) == before
assert database.read_bytes() == b'original database fixture'
assert key.read_bytes() == b'original key fixture'
assert runtime._application._closed
Dispatcher.start_polling.assert_awaited_once()
''')


def test_application_close_always_closes_bot_even_when_storage_fails(tmp_path):
    storage = SimpleNamespace(close=AsyncMock(side_effect=RuntimeError("storage close failed")))
    bot = SimpleNamespace(session=SimpleNamespace(close=AsyncMock()))
    settings = Settings.from_env({}, data_directory=tmp_path)
    app = Application(settings, bot, SimpleNamespace(storage=storage), None)
    with pytest.raises(RuntimeError, match="storage close failed"):
        asyncio.run(app.close())
    asyncio.run(app.close())
    bot.session.close.assert_awaited_once()
    storage.close.assert_awaited_once()
