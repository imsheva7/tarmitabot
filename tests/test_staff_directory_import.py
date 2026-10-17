"""Application queries can be imported without credentials or startup effects."""
import os
from pathlib import Path
import subprocess
import sys


def test_directory_layers_import_without_bot_or_files(tmp_path):
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, PYTHONPATH=str(root), PYTHONIOENCODING="utf-8")
    env.pop("BOT_TOKEN", None)
    env.pop("FERNET_KEY", None)
    script = """
import sys
from pathlib import Path
import erpbot.services.staff_directory
import erpbot.repositories.staff_directory
import erpbot.services.organization_memberships
import erpbot.services.organization_roles
import erpbot.repositories.organization_memberships
import erpbot.repositories.organization_roles
assert 'erpbot.core.runtime' not in sys.modules
assert 'aiogram' not in sys.modules
from erpbot.handlers.unit_staff import create_router
from erpbot.handlers.organization_units import create_router as create_units_router
from erpbot.handlers.organization_memberships import create_router as create_memberships_router
from erpbot.handlers.organization_roles import create_router as create_roles_router
import erpbot.services.organization_units
import erpbot.repositories.organization_units
assert 'erpbot.core.runtime' not in sys.modules
router = create_router(lambda: None)
assert len(router.message.handlers) == 1
assert len(router.callback_query.handlers) == 2
units_router = create_units_router(lambda: None)
assert len(units_router.message.handlers) == 1
assert len(units_router.callback_query.handlers) == 4
memberships_router = create_memberships_router(lambda: None)
roles_router = create_roles_router(lambda: None)
assert len(memberships_router.message.handlers) == 1
assert len(memberships_router.callback_query.handlers) == 8
assert len(roles_router.message.handlers) == 1
assert len(roles_router.callback_query.handlers) == 11
assert list(Path.cwd().iterdir()) == []
"""
    result = subprocess.run([sys.executable, "-c", script], cwd=tmp_path, env=env,
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
