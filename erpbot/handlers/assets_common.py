"""Shared asset Router authorization and input validation."""
from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery
from ..services import assets as service
from .organization_callbacks import callback_number


def asset_number(raw):
    number=callback_number(raw)
    if number is None or number<=0:
        raise service.AssetError("شناسه نامعتبر است.")
    return number


def charger_value(data):
    value=data.partition('_')[2]
    if value not in ('yes','no'):
        raise service.AssetError("گزینه شارژر نامعتبر است.")
    return 'دارد' if value=='yes' else 'ندارد'


class AssetAccess(BaseMiddleware):
    def __init__(self, connection_factory, *, admin=False):
        self.connection_factory=connection_factory
        self.admin=admin

    async def __call__(self, handler, event, data):
        try:
            with self.connection_factory() as conn:
                if self.admin:
                    service.require_admin(conn,event.from_user.id)
                else:
                    service.active_staff(conn,event.from_user.id)
            return await handler(event,data)
        except service.AssetError as exc:
            if isinstance(event,CallbackQuery):
                await event.answer(str(exc),show_alert=True)
            else:
                await event.answer(str(exc))
