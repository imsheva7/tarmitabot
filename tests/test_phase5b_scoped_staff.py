import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "erpbot" / "handlers" / "unit_staff.py"

def test_scoped_handlers_present():
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)}
    assert {"scoped_unit_staff_command", "scoped_unit_staff_view", "scoped_unit_staff_back"} <= funcs.keys()

def test_directory_handlers_do_not_execute_database_queries():
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    handlers = [node for node in ast.walk(tree) if isinstance(node, ast.AsyncFunctionDef)
                and node.name.startswith("scoped_unit_staff_")]
    for handler in handlers:
        for node in ast.walk(handler):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in {"execute", "executemany", "executescript"}

def test_directory_data_layers_do_not_depend_on_telegram_or_runtime():
    root = SRC.parents[2]
    for relative in ("repositories/staff_directory.py", "services/staff_directory.py",
                     "handlers/unit_staff.py"):
        tree = ast.parse((root / "erpbot" / relative).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [name.name for name in node.names]
            elif isinstance(node, ast.ImportFrom):
                assert all(alias.name != "*" for alias in node.names)
                modules = [node.module or ""]
            else:
                continue
            forbidden = ("runtime", "handlers")
            if not relative.startswith("handlers/"):
                forbidden += ("aiogram",)
            assert not any(part in name.split(".") for name in modules for part in forbidden)
