"""Public hiring calendar and source/DB coverage, using one selection function."""

import calendar as month_calendar
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from api.deps import get_db
from api.programmes import _selected_categories, _selected_statuses
from core.calendar_public import CalendarResponse, build_calendar
from core.calendar_reconciliation import CalendarRow, SkippedCalendarRow, reconcile_calendar
from core.hiring_calendar import IST
from core.models import Programme

router = APIRouter()


class CoverageWindow(BaseModel):
    from_date: date = Field(alias="from")
    to_date: date = Field(alias="to")
    as_of: date


class CalendarCoverage(BaseModel):
    source_digest: str
    source_rows: int
    metadata_programmes: int
    rows_without_metadata: int
    metadata_without_row: int
    rows_without_metadata_ids: list[str]
    metadata_without_row_ids: list[str]
    active_programmes: int
    registry_only_active: int
    published_dated: int
    published_rolling: int
    outside_window: int
    closed: int
    retired: int
    skipped: list[SkippedCalendarRow]
    pending_import: list[CalendarRow]
    unexplained: list[CalendarRow]
    published_total: int
    window: CoverageWindow


@router.get("/calendar/coverage", response_model=CalendarCoverage)
def get_calendar_coverage(db: Session = Depends(get_db)) -> dict:
    return reconcile_calendar(db, today=datetime.now(IST).date()).to_dict()


def validate_range(start: date, end: date) -> None:
    limit = date.max
    if start.year <= 9997:
        limit = date(
            start.year + 2,
            start.month,
            min(start.day, month_calendar.monthrange(start.year + 2, start.month)[1]),
        )
    if end < start or end > limit:
        raise HTTPException(422, "Range must be ordered and span at most two years")


@router.get("/calendar", response_model=CalendarResponse)
def get_calendar(
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
    category: list[str] | None = Query(None),
    status: list[str] | None = Query(None),
    q: str | None = Query(None, max_length=200),
    db: Session = Depends(get_db),
) -> CalendarResponse:
    validate_range(from_date, to_date)
    categories, statuses = _selected_categories(category), _selected_statuses(status)
    programmes = list(
        db.scalars(
            select(Programme)
            .options(selectinload(Programme.editions))
            .where(Programme.is_active.is_(True))
        )
    )
    return build_calendar(
        programmes,
        from_date,
        to_date,
        categories=categories,
        statuses=statuses,
        q=(q or "").strip(),
        now=datetime.now(IST),
    )
