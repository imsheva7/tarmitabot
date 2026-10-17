"""Callback validation and controlled authorization errors for organization routers."""
from aiogram import BaseMiddleware
from ..services.organization_admin import OrganizationAdminError


def callback_number(raw):
    if not raw.isdecimal() or len(raw) > 19:
        return None
    value = int(raw)
    return value if value <= 2**63 - 1 else None


def valid_callback_number(raw):
    return callback_number(raw) is not None


class AdminErrorResponder(BaseMiddleware):
    async def __call__(self, handler, event, data):
        try:
            return await handler(event, data)
        except OrganizationAdminError:
            await event.answer("فقط مدیر اصلی مجاز است.", show_alert=True)
