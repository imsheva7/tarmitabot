"""Shared explicit administrator lookup for organization application services."""
from erpbot.repositories.organization_units import main_admin_staff_id as admin_staff_id


class OrganizationAdminError(PermissionError):
    pass


def require_admin(conn, telegram_user_id):
    actor = admin_staff_id(conn, telegram_user_id)
    if actor is None:
        raise OrganizationAdminError("فقط مدیر اصلی مجاز است.")
    return actor
