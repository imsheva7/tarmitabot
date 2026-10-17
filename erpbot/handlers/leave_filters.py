"""Separate leave from legacy request callbacks without changing callback IDs."""
from aiogram.filters import BaseFilter
from .organization_callbacks import callback_number
from ..services import leave_workflow as workflow


class LeaveDecisionFilter(BaseFilter):
    def __init__(self, connection_factory, *, include_leave=True):
        self.connection_factory, self.include_leave = connection_factory, include_leave

    async def __call__(self, callback):
        action, _, raw = (callback.data or "").partition("_")
        if action == "leaveoverride":
            return self.include_leave
        if action not in ("approve", "reject"):
            return not self.include_leave
        request_id = callback_number(raw)
        if request_id is None:
            return self.include_leave
        with self.connection_factory() as conn:
            matches = workflow.is_leave_request(conn, request_id)
        return matches == self.include_leave


class LeaveRejectionFilter(BaseFilter):
    def __init__(self, connection_factory, *, include_leave=True):
        self.connection_factory, self.include_leave = connection_factory, include_leave

    async def __call__(self, message, state):
        saved = await state.get_data()
        request_id = saved.get("rejecting_req_id")
        if type(request_id) is not int or not 0 < request_id <= 2**63 - 1:
            return not self.include_leave
        with self.connection_factory() as conn:
            matches = workflow.is_leave_request(conn, request_id)
        return matches == self.include_leave


class LeaveCancellationFilter(BaseFilter):
    def __init__(self, connection_factory, *, include_leave=True):
        self.connection_factory, self.include_leave = connection_factory, include_leave

    async def __call__(self, callback):
        code = (callback.data or "").partition("_")[2]
        with self.connection_factory() as conn:
            matches = workflow.is_leave_code(conn, code)
        return matches == self.include_leave
