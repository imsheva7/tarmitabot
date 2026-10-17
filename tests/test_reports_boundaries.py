"""Report code is independent of initialized runtime and controllers/services contain no SQL."""
import ast
import os
from pathlib import Path
import subprocess
import sys
import pytest

ROOT=Path(__file__).resolve().parents[1]


def test_report_imports_create_no_files_or_runtime(tmp_path):
    script='''
import sys
from pathlib import Path
from erpbot.handlers.reports import create_router
from erpbot.services import reports
from erpbot.repositories import reports
from erpbot.reporting import models,xlsx,catalogue
assert 'erpbot.core.runtime' not in sys.modules
assert list(Path.cwd().iterdir())==[]
'''
    env=dict(os.environ,PYTHONPATH=str(ROOT))
    env.pop('BOT_TOKEN',None)
    env.pop('FERNET_KEY',None)
    result=subprocess.run([sys.executable,'-c',script],cwd=tmp_path,env=env,capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr


@pytest.mark.parametrize('path',['handlers/reports.py','services/reports.py','reporting/xlsx.py'])
def test_report_boundaries_have_no_sql_or_runtime_imports(path):
    tree=ast.parse((ROOT/'erpbot'/path).read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if isinstance(node,ast.ImportFrom):
            assert 'runtime' not in (node.module or '')
            assert all(alias.name!='*' for alias in node.names)
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute):
            assert node.func.attr not in ('execute','executemany','executescript','cursor','commit','rollback','read_sql_query','to_excel')
