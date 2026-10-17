"""Compose feature routers with explicit dependencies; no namespace injection."""
from .core import runtime
from .handlers.unit_staff import create_router as create_unit_staff_router
from .handlers.organization_units import create_router as create_organization_units_router
from .handlers.organization_memberships import create_router as create_memberships_router
from .handlers.organization_roles import create_router as create_roles_router
from .handlers.leave import create_router as create_leave_router
from .handlers.request_delivery import create_submitter
from .handlers.reminders import create_router as create_reminders_router
from .handlers.assets_employee import create_router as create_employee_assets_router
from .handlers.assets_admin import create_router as create_admin_assets_router
from .handlers.finance_forms import create_router as create_finance_forms_router
from .handlers.finance_decisions import create_router as create_finance_decisions_router
from .handlers.reports import create_router as create_reports_router
from .handlers.missions import create_router as create_missions_router
from .handlers.insurance import create_router as create_insurance_router
from .handlers.personnel import create_router as create_personnel_router
from .handlers.holidays import create_router as create_holidays_router
from .handlers.admin_console import create_router as create_admin_console_router
from .handlers.request_decisions import create_router as create_request_decisions_router
from .handlers.navigation import create_router as create_navigation_router
from .handlers.maintenance import create_router as create_maintenance_router

MODULES = ['001_misc', '002_navigation', '003_assets', '004_reports', '005_navigation', '006_reminders', '007_leave', '008_misc', '009_leave', '010_advance', '011_mission', '012_petty', '013_assets', '014_purchase', '015_assets', '016_reports', '017_misc', '018_admin', '019_navigation', '020_misc', '021_admin', '022_navigation', '023_misc', '024_admin', '025_assets', '026_admin']

_registered_dispatcher = None

def register_handlers():
    global _registered_dispatcher
    runtime.require_initialized()
    if _registered_dispatcher is runtime.dp:
        return len(MODULES)
    # Existing callback middleware also applies to the explicitly composed routers.
    # /start must keep priority over message handlers for an unfinished form.
    runtime.dp.include_router(create_navigation_router(runtime.get_connection,runtime.bot,runtime.GROUP_ID))
    runtime.dp.include_router(create_organization_units_router(runtime.get_connection))
    runtime.dp.include_router(create_memberships_router(runtime.get_connection))
    runtime.dp.include_router(create_roles_router(runtime.get_connection))
    runtime.dp.include_router(create_unit_staff_router(runtime.get_connection))
    submit_request = create_submitter(runtime.get_connection, runtime.bot, runtime.GROUP_ID, {
        "مرخصی": runtime.TOPIC_LEAVE, "مساعده": runtime.TOPIC_ADVANCE,
        "ماموریت": runtime.TOPIC_MISSION, "تنخواه": runtime.TOPIC_PETTY,
        "خرید ملزومات": runtime.TOPIC_PURCHASE, "تحویل اموال": runtime.TOPIC_ASSETS,
        "عودت اموال": runtime.TOPIC_ASSETS,
    }, runtime.get_current_tehran_time)
    runtime.dp.include_router(create_leave_router(runtime.get_connection, runtime.bot, submit_request=submit_request))
    runtime.dp.include_router(create_reminders_router(runtime.get_connection, runtime.bot, runtime.get_current_tehran_time))
    runtime.dp.include_router(create_employee_assets_router(runtime.get_connection, runtime.bot,
        runtime.get_current_tehran_time, runtime.encrypt_data, submit_request=submit_request))
    runtime.dp.include_router(create_admin_assets_router(runtime.get_connection, runtime.bot,
        runtime.get_current_tehran_time, runtime.encrypt_data, runtime.decrypt_data))
    runtime.dp.include_router(create_finance_forms_router(runtime.get_connection,
        runtime.get_current_tehran_time, runtime.encrypt_data, submit_request=submit_request))
    runtime.dp.include_router(create_finance_decisions_router(runtime.get_connection, runtime.bot,
        runtime.GROUP_ID, runtime.decrypt_data))
    runtime.dp.include_router(create_reports_router(runtime.get_connection,runtime.get_current_tehran_time))
    runtime.dp.include_router(create_missions_router(runtime.get_connection,runtime.bot,submit_request=submit_request))
    runtime.dp.include_router(create_insurance_router(runtime.get_connection,runtime.bot,runtime.GROUP_ID,runtime.TOPIC_INSURANCE))
    runtime.dp.include_router(create_personnel_router(runtime.get_connection,runtime.get_current_tehran_time))
    runtime.dp.include_router(create_holidays_router(runtime.get_connection))
    runtime.dp.include_router(create_admin_console_router(runtime.get_connection, runtime.DB_PATH))
    runtime.dp.include_router(create_request_decisions_router(runtime.get_connection, runtime.bot))
    runtime.dp.include_router(create_maintenance_router(runtime.get_connection,runtime.DB_PATH,runtime.get_current_tehran_time))
    _registered_dispatcher = runtime.dp
    # Historical return value retained for callers; numbered modules are not imported.
    return len(MODULES)
