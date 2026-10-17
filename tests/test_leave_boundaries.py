"""Leave imports and boundaries stay independent of initialized runtime resources."""
import ast
import os
from pathlib import Path
import subprocess
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_leave_modules_import_without_token_database_or_runtime(tmp_path):
    script = '''
import sys
from pathlib import Path
from erpbot.handlers.leave import create_router
from erpbot.handlers.request_delivery import create_submitter
from erpbot.handlers import leave_filters, leave_states
from erpbot.services import leave_workflow, leave_approval, requests
from erpbot.repositories import leave
assert 'erpbot.core.runtime' not in sys.modules
assert list(Path.cwd().iterdir()) == []
'''
    env = dict(os.environ,PYTHONPATH=str(ROOT),PYTHONIOENCODING="utf-8")
    env.pop("BOT_TOKEN",None)
    env.pop("FERNET_KEY",None)
    result = subprocess.run([sys.executable,"-c",script],cwd=tmp_path,env=env,
                            capture_output=True,text=True,encoding="utf-8",timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("path",[
    "handlers/leave.py", "handlers/leave_filters.py", "handlers/request_delivery.py",
    "services/leave_workflow.py", "services/leave_approval.py", "services/requests.py",
])
def test_controllers_and_services_have_no_sql_or_runtime_imports(path):
    tree = ast.parse((ROOT/"erpbot"/path).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node,ast.ImportFrom):
            assert "runtime" not in (node.module or "")
            assert all(alias.name != "*" for alias in node.names)
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute):
            assert node.func.attr not in ("execute","executemany","executescript","cursor","commit","rollback")
