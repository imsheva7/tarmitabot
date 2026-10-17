"""Keep financial approvals and completion actions out of generic callbacks."""
from aiogram.filters import BaseFilter
from .organization_callbacks import callback_number
from ..services import finance


class FinanceDecisionFilter(BaseFilter):
    def __init__(self, connection_factory, *, include_finance=True):
        self.connection_factory=connection_factory
        self.include_finance=include_finance

    async def __call__(self, callback):
        action,_,raw=(callback.data or '').partition('_')
        matches=action in ('paid','bought')
        request_id=callback_number(raw)
        if action=='approve' and request_id is not None:
            with self.connection_factory() as conn:
                matches=finance.is_financial_request(conn,request_id)
        return matches==self.include_finance
