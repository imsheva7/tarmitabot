"""Infrastructure modules must stay usable without the Telegram runtime."""
import os
from pathlib import Path
import subprocess
import sys


def test_settings_and_database_import_have_no_startup_effects(tmp_path):
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, PYTHONPATH=str(root), PYTHONIOENCODING="utf-8")
    env.pop("BOT_TOKEN", None)
    env.pop("FERNET_KEY", None)
    # Import must not even parse configuration until explicitly requested.
    env["GROUP_ID"] = "invalid-for-this-import-test"
    script = """
import sys
from pathlib import Path
from erpbot.core.settings import Settings
from erpbot.core.database import connect
settings = Settings.from_env({}, data_directory='unused')
assert settings.bot_token is None
assert 'erpbot.core.runtime' not in sys.modules
assert 'aiogram' not in sys.modules
assert 'cryptography' not in sys.modules
assert list(Path.cwd().iterdir()) == []
"""
    result = subprocess.run([sys.executable, "-c", script], cwd=tmp_path, env=env,
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
