"""Keep mission approval out of the legacy generic approval branch."""
from aiogram.filters import BaseFilter
from .organization_callbacks import callback_number
from ..services import missions


class MissionApprovalFilter(BaseFilter):
    def __init__(self,connection_factory,*,include_missions=True):
        self.connection_factory=connection_factory
        self.include_missions=include_missions

    async def __call__(self,callback):
        action,_,raw=(callback.data or '').partition('_')
        number=callback_number(raw)
        matches=False
        if action=='approve' and number is not None:
            with self.connection_factory() as conn: matches=missions.is_mission_request(conn,number)
        return matches==self.include_missions
