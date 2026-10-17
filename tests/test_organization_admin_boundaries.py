"""Architectural dependency boundaries for extracted organization capabilities."""
import ast
from pathlib import Path


def test_membership_role_layers_keep_sql_and_startup_out_of_transport_and_services():
    root = Path(__file__).resolve().parents[1] / "erpbot"
    for layer in ("handlers", "services", "repositories"):
        for feature in ("organization_memberships", "organization_roles"):
            path = root / layer / f"{feature}.py"
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    assert all(alias.name != "*" for alias in node.names)
                    parts = set((node.module or "").split("."))
                    assert "runtime" not in parts
                    if layer != "handlers":
                        assert not {"handlers", "aiogram"} & parts
                    if layer == "repositories":
                        assert "services" not in parts
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    assert node.func.attr not in {"commit", "rollback"}
                    if layer != "repositories":
                        assert node.func.attr not in {"execute", "executemany", "executescript"}
