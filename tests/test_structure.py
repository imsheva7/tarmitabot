
import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HANDLERS_DIR = ROOT / "erpbot" / "handlers"
ADMIN_HANDLER = HANDLERS_DIR / "026_admin.py"


def read_python(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_all_modules_compile():
    paths = list(ROOT.glob("*.py"))
    paths.extend((ROOT / "erpbot").rglob("*.py"))
    paths.extend((ROOT / "tests").rglob("*.py"))
    for path in paths:
        ast.parse(read_python(path), filename=str(path))


def test_handler_count_and_order():
    loader_path = ROOT / "erpbot" / "loader.py"
    loader_tree = ast.parse(
        read_python(loader_path),
        filename=str(loader_path),
    )

    modules = next(
        ast.literal_eval(node.value)
        for node in loader_tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name)
            and target.id == "MODULES"
            for target in node.targets
        )
    )

    assert len(modules) == len(set(modules)), (
        "Duplicate handler modules found in loader."
    )

    count = 0

    for name in modules:
        path = HANDLERS_DIR / f"{name}.py"
        assert path.is_file(), f"Missing handler module: {name}"

        tree = ast.parse(read_python(path), filename=str(path))

        count += sum(
            bool(getattr(node, "decorator_list", []))
            for node in tree.body
        )

    # Features extracted from the legacy modules keep their original handlers.
    for feature in ("unit_staff.py", "organization_units.py", "organization_memberships.py", "organization_roles.py", "leave.py", "reminders.py", "assets_employee.py", "assets_admin.py", "finance_forms.py", "finance_decisions.py", "reports.py", "missions.py", "insurance.py", "personnel.py", "holidays.py", "admin_console.py", "request_decisions.py", "navigation.py", "maintenance.py"):
        feature_tree = ast.parse(read_python(HANDLERS_DIR / feature))
        count += sum(bool(node.decorator_list) for node in ast.walk(feature_tree)
                     if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)))

    assert count == 174, (
        f"Expected 174 decorated handlers, found {count}."
    )


def test_exceptional_leave_approval_handler_exists():
    source = read_python(HANDLERS_DIR / "leave.py")
    tree = ast.parse(source)

    function_names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert "handle_leave_decision" in function_names
    assert "cancel_exceptional_leave_approval" in function_names

    assert "workflow.approve_leave" in source
    assert "needs_override" in source
    assert "exceptional_approved" in source
    assert "leaveoverride_" in source
    assert "leavecancel_" in source


def test_exceptional_leave_approval_service_exists():
    service_path = ROOT / "erpbot" / "services" / "leave_approval.py"

    assert service_path.is_file()

    tree = ast.parse(
        read_python(service_path),
        filename=str(service_path),
    )

    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert "approve_annual_leave" in functions

    approval_function = functions["approve_annual_leave"]

    assert any(
        argument.arg == "exceptional"
        for argument in approval_function.args.kwonlyargs
    ), "Annual leave approval must support explicit exceptional mode."

