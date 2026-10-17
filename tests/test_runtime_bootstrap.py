"""Static regression checks; no Telegram credentials or network required."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_connection_is_available_before_database_initializer():
    tree = ast.parse((ROOT / "erpbot/core/runtime.py").read_text(encoding="utf-8"))
    defs = {n.name: i for i,n in enumerate(tree.body) if isinstance(n, (ast.FunctionDef,ast.AsyncFunctionDef))}
    assert defs["get_connection"] < defs["init_db"]

def test_no_database_initialization_at_import():
    tree = ast.parse((ROOT / "erpbot/core/runtime.py").read_text(encoding="utf-8"))
    for node in tree.body:
        assert not (isinstance(node,ast.Expr) and isinstance(node.value,ast.Call) and isinstance(node.value.func,ast.Name) and node.value.func.id == "init_db")

def test_main_does_not_import_legacy_scheduler_before_initialization():
    tree = ast.parse((ROOT / "erpbot/main.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            assert node.module != "scheduler.jobs"
