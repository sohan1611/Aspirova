"""Read-only reconciliation of authored rows with the public calendar selection."""

from dataclasses import asdict, dataclass
from datetime import date
import re

from sqlalchemy import select, text
from sqlalchemy.orm import Session, selectinload

from core import hiring_calendar as source
from core.calendar_public import STATUS_LABELS, build_calendar, default_calendar_window
from core.models import Programme


@dataclass(frozen=True)
class CalendarRow:
    row_id: str
    slug: str


@dataclass(frozen=True)
class SkippedCalendarRow(CalendarRow):
    reason: str


@dataclass(frozen=True)
class CalendarWindow:
    # Strings keep asdict()/json.dumps() usable in public logs without a custom encoder.
    from_date: str
    to_date: str
    as_of: str


@dataclass(frozen=True)
class CalendarReconciliation:
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
    window: CalendarWindow

    def to_dict(self) -> dict:
        result = asdict(self)
        window = result["window"]
        window["from"] = window.pop("from_date")
        window["to"] = window.pop("to_date")
        return result


def metadata_gaps() -> tuple[list[str], list[str]]:
    """Offline source-to-metadata check; do not trust the authored count field."""
    row_ids = {row["id"] for row in source.SOURCE["opportunities"]}
    meta_ids = {meta["row_id"] for meta in source.CALENDAR_META.values()}
    return sorted(row_ids - meta_ids), sorted(meta_ids - row_ids)


def _supported_categories(session: Session) -> set[str] | None:
    """Recognise the importer's sole tolerated failure, including pre-migration DBs.

    Missing rows on a current schema are pending, never guessed to be skipped.
    The named CHECK is a literal IN/ANY list in our migrations. No SQL is executed
    from its text; an unrecognised definition leaves absent rows pending.
    """
    definition = session.scalar(
        text(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = to_regclass('programmes') "
            "AND conname = 'ck_programmes_category' AND contype = 'c'"
        )
    )
    if not definition or "category" not in definition:
        return None
    categories = set(re.findall(r"'([a-z_]+)'", definition))
    return categories or None


def reconcile_calendar(session: Session, *, today: date) -> CalendarReconciliation:
    # Two bulk ORM reads (programmes + editions) and one constraint lookup; no N+1.
    programmes = list(
        session.scalars(
            select(Programme)
            .options(selectinload(Programme.editions))
            .execution_options(populate_existing=True)
        )
    )
    supported = _supported_categories(session)
    start, end = default_calendar_window(today)
    public = build_calendar(
        [programme for programme in programmes if programme.is_active],
        start,
        end,
        categories=[],
        statuses=[],
        q="",
        now=source.at_day(today),
    )
    # Occurrences, projected editions and aliases all count once per authored row.
    dated = {item.metadata.row_id for item in public.items}
    rolling = {item.metadata.row_id for item in public.rolling}
    meta_by_row: dict[str, list[str]] = {}
    for slug, meta in source.CALENDAR_META.items():
        meta_by_row.setdefault(meta["row_id"], []).append(slug)
    by_row: dict[str, list[Programme]] = {}
    registry_only_active = 0
    for programme in programmes:
        meta = source.calendar_metadata(programme.slug, programme.name, programme.organiser)
        if meta and meta["row_id"] in source.ROWS:
            by_row.setdefault(meta["row_id"], []).append(programme)
        else:
            registry_only_active += int(programme.is_active)
    retirements = {
        item["inactive_programme_slug"]
        for item in source.METADATA.get("watchlist", [])
        if item.get("inactive_programme_slug")
    }
    counts = dict(published_dated=0, published_rolling=0, outside_window=0, closed=0, retired=0)
    skipped, pending, unexplained = [], [], []
    for row in source.SOURCE["opportunities"]:
        row_id = row["id"]
        slugs = meta_by_row.get(row_id, [])
        reference = CalendarRow(row_id, slugs[0] if len(slugs) == 1 else "")
        if len(slugs) != 1:
            unexplained.append(reference)
            continue
        slug = slugs[0]
        matches = by_row.get(row_id, [])
        if slug in retirements or (len(matches) == 1 and not matches[0].is_active):
            counts["retired"] += 1
            continue
        if not matches:
            category = source.category_for(row)
            if supported is not None and category not in supported:
                skipped.append(
                    SkippedCalendarRow(
                        row_id, slug, f"ck_programmes_category rejects category {category}"
                    )
                )
            else:
                pending.append(reference)
            continue
        if len(matches) != 1:
            unexplained.append(reference)
            continue
        programme = matches[0]
        if programme.slug in retirements:
            counts["retired"] += 1
            continue
        cycle = source.CALENDAR_META[slug]["cycle_year"]
        edition = next((item for item in programme.editions if item.year == cycle), None)
        if edition is None:
            unexplained.append(reference)
        elif row_id in dated:
            counts["published_dated"] += 1
        elif row_id in rolling:
            counts["published_rolling"] += 1
        elif edition.status == "closed":
            counts["closed"] += 1
        elif edition.status in STATUS_LABELS and (edition.opens_at or edition.closes_at):
            counts["outside_window"] += 1
        else:
            unexplained.append(reference)
    missing_meta, missing_rows = metadata_gaps()
    return CalendarReconciliation(
        source_rows=len(source.SOURCE["opportunities"]),
        metadata_programmes=len(source.CALENDAR_META),
        rows_without_metadata=len(missing_meta),
        metadata_without_row=len(missing_rows),
        rows_without_metadata_ids=missing_meta,
        metadata_without_row_ids=missing_rows,
        active_programmes=sum(programme.is_active for programme in programmes),
        registry_only_active=registry_only_active,
        **counts,
        skipped=skipped,
        pending_import=pending,
        unexplained=unexplained,
        published_total=counts["published_dated"] + counts["published_rolling"],
        window=CalendarWindow(start.isoformat(), end.isoformat(), today.isoformat()),
    )
