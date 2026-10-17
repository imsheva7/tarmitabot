"""Immutable report data detached from database connections."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Sheet:
    title: str
    headers: tuple[str,...]
    rows: tuple[tuple,...]


@dataclass(frozen=True)
class WorkbookReport:
    filename: str
    sheets: tuple[Sheet,...]
    owner_staff_id: int | None = None
