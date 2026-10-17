"""Preserve persisted state strings while removing the runtime dependency."""
from aiogram.fsm.state import State, StatesGroup


class Form(StatesGroup):
    waiting_for_leave_type = State()
    waiting_for_leave_start_date = State()
    waiting_for_leave_end_date = State()
    waiting_for_hourly_date = State()
    waiting_for_hourly_times = State()
    waiting_for_replacement = State()
    waiting_for_leave_preview = State()


class AdminForm(StatesGroup):
    rejection_reason = State()
