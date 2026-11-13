"""Public, range-based hiring calendar over the existing programme registry."""

import calendar as month_calendar
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from api.deps import get_db
from api.programmes import PROGRAMME_CATEGORY_LABELS, _selected_categories, _selected_statuses
from core.hiring_calendar import (
    IST,
    ROWS,
    SLUG_BY_ROW_ID,
    at_day,
    calendar_metadata,
    has_rolling_deadline,
    official_status,
    parse_calendar_date,
    recurrence_windows,
    source_window,
)
from core.models import Programme, ProgrammeEdition

router = APIRouter()
STATUS_LABELS = {
    "expected": "Tentative · historical trend",
    "announced": "Official",
    "open": "Open now",
    "closed": "Closed",
}


class CalendarProgramme(BaseModel):
    slug: str
    name: str
    organiser: str
    category: str
    category_label: str
    url: str
    eligibility: str | None
    country: str | None
    geography: str | None


class CalendarEdition(BaseModel):
    year: int
    status: str
    status_label: str
    opens_at: datetime | None
    closes_at: datetime | None
    opens_precision: Literal["day", "month"] | None
    closes_precision: Literal["day", "month"] | None
    opens_until: datetime | None = None
    closes_from: datetime | None = None
    basis: Literal["official", "tentative"]


class CalendarMetadata(BaseModel):
    deadline_rolling: bool = False
    source_cycle_year: int | None = None
    row_id: str | None = None
    prep_tip: str | None = None
    hiring_mode: str | None = None
    career_linkage: str | None = None
    duration_start: str | None = None
    verification_note: str | None = None
    confidence: str | None = None
    opening_text: str | None = None
    deadline_text: str | None = None


class CalendarItem(BaseModel):
    id: str
    programme: CalendarProgramme
    edition: CalendarEdition
    metadata: CalendarMetadata
    verified_at: datetime | None
    is_open_now: bool


class CalendarMonth(BaseModel):
    month: str
    count: int


class CalendarResponse(BaseModel):
    from_date: date = Field(serialization_alias="from")
    to_date: date = Field(serialization_alias="to")
    items: list[CalendarItem]
    rolling: list[CalendarItem]
    months: list[CalendarMonth]


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


def _month_bound(meta: dict, edition: ProgrammeEdition, field: str) -> datetime | None:
    if not meta:
        return None
    row = ROWS[meta["row_id"]]
    parsed = parse_calendar_date(
        row["application_open" if field == "opens_at" else "registration_deadline"]
    )
    stored = getattr(edition, field)
    source_boundary = parsed.start if field == "opens_at" else parsed.end
    if (
        stored is None
        or source_boundary is None
        or stored.astimezone(IST).month != source_boundary.month
    ):
        return None
    value = parsed.end if field == "opens_at" else parsed.start
    if value is None:
        return None
    year = value.year + edition.year - meta["cycle_year"]
    return value.replace(
        year=year, day=min(value.day, month_calendar.monthrange(year, value.month)[1])
    )


def _item(
    programme: Programme,
    edition: ProgrammeEdition,
    meta: dict,
    *,
    opening: datetime | None,
    closing: datetime | None,
    now: datetime,
    occurrence: int = 0,
    rolling: bool = False,
) -> CalendarItem:
    rule = meta.get("recurrence")
    deadline_rolling = has_rolling_deadline(meta, edition.notes)
    status = edition.status
    if rule and status != "expected":
        # A yearly row covers multiple independent official windows.
        status = "announced"
    status = official_status(status, opening, None if deadline_rolling else closing, now)
    source = source_window(SLUG_BY_ROW_ID[meta["row_id"]]) if meta else {}
    precision = {}
    for field, value in (("opens_at", opening), ("closes_at", closing)):
        exact = f"calendar_exact_{field}" in (edition.notes or "")
        default = (
            rule["precision"] if rule else source.get(field.replace("_at", "_precision")) or "day"
        )
        precision[field] = (
            ("month" if status == "expected" else "day" if exact else default) if value else None
        )
    is_open = status == "open" and not rolling
    label = "Rolling" if rolling and status != "closed" else STATUS_LABELS[status]
    return CalendarItem(
        id=f"{programme.slug}:{edition.year}:{occurrence}",
        programme=CalendarProgramme(
            slug=programme.slug,
            name=programme.name,
            organiser=programme.organiser,
            category=programme.category,
            category_label=PROGRAMME_CATEGORY_LABELS.get(programme.category, programme.category),
            url=programme.url,
            eligibility=programme.eligibility,
            country=programme.country,
            geography=meta.get("geography", programme.country),
        ),
        edition=CalendarEdition(
            year=edition.year,
            status=status,
            status_label=label,
            opens_at=opening,
            closes_at=closing,
            opens_precision=precision["opens_at"],
            closes_precision=precision["closes_at"],
            opens_until=(
                _month_bound(meta, edition, "opens_at")
                if precision["opens_at"] == "month" and not rule
                else None
            ),
            closes_from=(
                _month_bound(meta, edition, "closes_at")
                if precision["closes_at"] == "month" and not rule
                else None
            ),
            basis="tentative" if status == "expected" else "official",
        ),
        metadata=CalendarMetadata(
            source_cycle_year=meta.get("cycle_year"),
            **{
                key: value
                for key, value in meta.items()
                if key in CalendarMetadata.model_fields and key != "deadline_rolling"
            },
            deadline_rolling=deadline_rolling,
        ),
        verified_at=edition.verified_at,
        is_open_now=is_open,
    )


def build_calendar(
    programmes: list[Programme],
    start: date,
    end: date,
    *,
    categories: list[str],
    statuses: list[str],
    q: str,
    now: datetime,
) -> CalendarResponse:
    items, rolling = [], []
    start_at, end_at = at_day(start), at_day(end, end=True)
    for programme in programmes:
        if categories and programme.category not in categories:
            continue
        if q and q.casefold() not in f"{programme.name} {programme.organiser}".casefold():
            continue
        meta = calendar_metadata(programme.slug, programme.name, programme.organiser)
        editions = [edition for edition in programme.editions if edition.status in STATUS_LABELS]
        if meta.get("recurrence") and editions:
            by_year = {edition.year: edition for edition in editions}
            latest = max(editions, key=lambda edition: edition.year)
            # Standing rules also cover requested years without a persisted
            # edition. A later expected edition keeps its tentative basis.
            editions = [
                by_year.get(year)
                or ProgrammeEdition(
                    year=year,
                    status="expected" if latest.status == "expected" else "announced",
                    verified_at=latest.verified_at,
                )
                for year in range(start.year, min(end.year + 1, 9999) + 1)
            ]
        source_rolling = bool(meta and source_window(SLUG_BY_ROW_ID[meta["row_id"]])["rolling"])
        latest_year = max((edition.year for edition in editions), default=0)
        application_offset = meta.get("cycle_year", 2027) - 2027
        rolling_year = max(
            (
                edition.year
                for edition in editions
                if start.year <= edition.year - application_offset <= end.year
            ),
            default=latest_year,
        )
        for edition in editions:
            if source_rolling and edition.opens_at is None and edition.closes_at is None:
                if edition.year != rolling_year:
                    continue
                item = _item(
                    programme, edition, meta, opening=None, closing=None, now=now, rolling=True
                )
                if (
                    not statuses
                    or item.edition.status in statuses
                    and item.edition.status != "open"
                ):
                    rolling.append(item)
                continue
            windows = (
                recurrence_windows(edition.year, meta["recurrence"])
                if meta.get("recurrence")
                else [(edition.opens_at, edition.closes_at)]
            )
            for index, (opening, closing) in enumerate(windows):
                if opening is None and closing is None:
                    continue
                # An unknown endpoint is a single known boundary, not an infinite window.
                if (opening or closing) > end_at or (closing or opening) < start_at:
                    continue
                item = _item(
                    programme,
                    edition,
                    meta,
                    opening=opening,
                    closing=closing,
                    now=now,
                    occurrence=index,
                )
                if not statuses or item.edition.status in statuses:
                    items.append(item)
    items.sort(
        key=lambda item: (
            item.edition.opens_at or item.edition.closes_at,
            item.programme.name,
            item.id,
        )
    )
    rolling.sort(key=lambda item: item.programme.name.casefold())
    months = []
    month = start.replace(day=1)
    while month <= end:
        last = month.replace(day=month_calendar.monthrange(month.year, month.month)[1])
        left, right = at_day(max(start, month)), at_day(min(end, last), end=True)
        count = sum(
            (item.edition.opens_at or item.edition.closes_at) <= right
            and (item.edition.closes_at or item.edition.opens_at) >= left
            for item in items
        )
        months.append(CalendarMonth(month=month.strftime("%Y-%m"), count=count))
        if last >= end:
            break
        month = date(month.year + (month.month == 12), month.month % 12 + 1, 1)
    return CalendarResponse(
        from_date=start, to_date=end, items=items, rolling=rolling, months=months
    )


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
