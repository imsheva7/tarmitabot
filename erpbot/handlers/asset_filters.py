"""Route asset approvals to their transactional use case without changing callback IDs."""
from aiogram.filters import BaseFilter
from .organization_callbacks import callback_number
from ..services import assets


class AssetApprovalFilter(BaseFilter):
    def __init__(self, connection_factory, *, include_assets=True):
        self.connection_factory=connection_factory
        self.include_assets=include_assets

    async def __call__(self, callback):
        action,_,raw=(callback.data or '').partition('_')
        matches=False
        request_id=callback_number(raw)
        if action=='approve' and request_id is not None:
            with self.connection_factory() as conn:
                matches=assets.is_asset_request(conn,request_id)
        return matches==self.include_assets
