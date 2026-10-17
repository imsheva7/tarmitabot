"""Mission/insurance feature imports and SQL boundaries without application startup."""
import ast
import os
from pathlib import Path
import subprocess
import sys
import pytest

ROOT=Path(__file__).resolve().parents[1]


def test_mission_insurance_imports_create_no_resources(tmp_path):
    script='''
import sys
from pathlib import Path
from erpbot.handlers import missions,insurance,mission_filters
from erpbot.services import missions,insurance
from erpbot.repositories import missions,insurance
from erpbot.scheduler.insurance import deliver_alerts
assert 'erpbot.core.runtime' not in sys.modules
assert list(Path.cwd().iterdir())==[]
'''
    env=dict(os.environ,PYTHONPATH=str(ROOT))
    env.pop('BOT_TOKEN',None)
    env.pop('FERNET_KEY',None)
    result=subprocess.run([sys.executable,'-c',script],cwd=tmp_path,env=env,capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr


@pytest.mark.parametrize('path',['handlers/missions.py','handlers/insurance.py','handlers/mission_filters.py',
                               'services/missions.py','services/insurance.py','scheduler/insurance.py'])
def test_mission_insurance_layers_have_no_runtime_or_sql(path):
    tree=ast.parse((ROOT/'erpbot'/path).read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if isinstance(node,ast.ImportFrom):
            assert 'runtime' not in (node.module or '')
            assert all(alias.name!='*' for alias in node.names)
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute):
            assert node.func.attr not in ('execute','executemany','executescript','cursor','commit','rollback')
