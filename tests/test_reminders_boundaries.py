"""The reminder feature imports independently of runtime and keeps SQL in repositories."""
import ast
import os
from pathlib import Path
import subprocess
import sys
import pytest

ROOT=Path(__file__).resolve().parents[1]


def test_reminder_imports_create_no_resources(tmp_path):
    script='''
import sys
from pathlib import Path
from erpbot.handlers.reminders import create_router
from erpbot.scheduler.reminders import run_scheduler
from erpbot.services import reminders
from erpbot.repositories import reminders
assert 'erpbot.core.runtime' not in sys.modules
assert list(Path.cwd().iterdir())==[]
'''
    env=dict(os.environ,PYTHONPATH=str(ROOT))
    env.pop('BOT_TOKEN',None)
    env.pop('FERNET_KEY',None)
    result=subprocess.run([sys.executable,'-c',script],cwd=tmp_path,env=env,capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr


@pytest.mark.parametrize('path',['handlers/reminders.py','scheduler/reminders.py','services/reminders.py'])
def test_reminder_boundary_has_no_runtime_import_or_sql(path):
    tree=ast.parse((ROOT/'erpbot'/path).read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if isinstance(node,ast.ImportFrom):
            assert 'runtime' not in (node.module or '')
            assert all(alias.name!='*' for alias in node.names)
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute):
            assert node.func.attr not in ('execute','executemany','executescript','cursor','commit','rollback')
