"""Daily conservative calendar refresh. Usage: uv run python -m scripts.refresh_calendar."""

from datetime import datetime
import logging

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, selectinload

from core.db import make_engine
from core.hiring_calendar import (
    IST,
    calendar_metadata,
    has_rolling_deadline,
    month_date,
    official_status,
    shift_year,
)
from core.models import Programme, ProgrammeEdition
from pipeline.programme_verification import CalendarPageFetcher, extract_official_calendar_dates
from scripts.import_calendar import import_calendar

logger = logging.getLogger(__name__)


def apply_page(
    edition: ProgrammeEdition,
    html: str | None,
    *,
    now: datetime,
    cycle_start: datetime,
    deadline_rolling: bool = False,
) -> bool:
    before = (edition.status, edition.opens_at, edition.closes_at)
    if html:
        found = extract_official_calendar_dates(
            html, cycle_year=edition.year, cycle_start=cycle_start
        )
        opening = found.get("opens_at", None if edition.status == "expected" else edition.opens_at)
        closing = found.get(
            "closes_at",
            None if edition.status == "expected" or deadline_rolling else edition.closes_at,
        )
        if found and (opening is None or closing is None or opening <= closing):
            # An expected boundary remains tentative unless this page verifies
            # it too. Do not silently promote the other historical boundary.
            if edition.status == "expected":
                edition.opens_at = found.get("opens_at")
                edition.closes_at = found.get("closes_at")
                edition.status = "announced"
            else:
                edition.opens_at, edition.closes_at = opening, closing
            notes = edition.notes or ""
            for field in found:
                marker = f"calendar_exact_{field}"
                if marker not in notes:
                    notes += f"\n{marker}"
            edition.notes = notes.strip()
            if deadline_rolling and "closes_at" not in found and edition.opens_at is not None:
                opening = edition.opens_at.astimezone(IST)
                edition.closes_at = month_date(opening.year, opening.month, end=True)
    actual_closing = edition.closes_at
    if deadline_rolling and "calendar_exact_closes_at" not in (edition.notes or ""):
        actual_closing = None
    edition.status = official_status(edition.status, edition.opens_at, actual_closing, now)
    return before != (edition.status, edition.opens_at, edition.closes_at)


def roll_forward(session: Session, edition: ProgrammeEdition, *, now: datetime) -> bool:
    if edition.status != "closed" and edition.year >= now.year:
        return False
    opening = shift_year(edition.opens_at.astimezone(IST)) if edition.opens_at else None
    closing = shift_year(edition.closes_at.astimezone(IST)) if edition.closes_at else None
    # Every projected boundary is deliberately reduced to month precision.
    if opening:
        opening = month_date(opening.year, opening.month)
    if closing:
        closing = month_date(closing.year, closing.month, end=True)
    notes = "Projected next cycle from historical months. Verify the new official call."
    if "calendar_deadline_rolling" in (edition.notes or "") and "calendar_exact_closes_at" not in (
        edition.notes or ""
    ):
        notes += "\ncalendar_deadline_rolling"
    result = session.execute(
        insert(ProgrammeEdition)
        .values(
            programme_id=edition.programme_id,
            year=edition.year + 1,
            status="expected",
            opens_at=opening,
            closes_at=closing,
            notes=notes,
        )
        .on_conflict_do_nothing(index_elements=["programme_id", "year"])
        .returning(ProgrammeEdition.id)
    )
    return result.scalar_one_or_none() is not None


def refresh_calendar(
    session: Session, fetcher: CalendarPageFetcher, *, now: datetime | None = None
) -> dict[str, int]:
    now = now or datetime.now(IST)
    summary = {**import_calendar(session), "checked": 0, "updated": 0, "rolled": 0, "errors": 0}
    programmes = list(
        session.scalars(
            select(Programme)
            .options(selectinload(Programme.editions))
            .where(Programme.is_active.is_(True))
        )
    )
    for programme in programmes:
        meta = calendar_metadata(programme.slug, programme.name, programme.organiser)
        if not meta:
            continue
        try:
            with session.begin_nested():
                # Liveness belongs to the programme, and a page check only
                # verifies the newest cycle. Older editions still transition.
                editions = [
                    edition for edition in programme.editions if edition.status != "discontinued"
                ]
                if not editions:
                    continue
                latest = max(editions, key=lambda edition: edition.year)
                try:
                    liveness, html = fetcher.fetch(programme.url)
                except Exception as exc:
                    logger.warning(
                        "Calendar %s fetch failed (%s)", programme.slug, type(exc).__name__
                    )
                    liveness, html = "inconclusive", None
                summary["checked"] += 1
                logger.info("Calendar %s liveness=%s", programme.slug, liveness)
                if liveness in {"inconclusive", "robots_disallowed", "closed"}:
                    summary["errors"] += 1
                for edition in editions:
                    # Intake applications can fall in the preceding year.
                    # Extraction also requires this edition's year in the block.
                    cycle_start = month_date(max(1, edition.year - 1), 1)
                    changed = apply_page(
                        edition,
                        (html if edition is latest and not meta.get("recurrence") else None),
                        now=now,
                        cycle_start=cycle_start,
                        deadline_rolling=has_rolling_deadline(meta, edition.notes),
                    )
                    if edition is latest and liveness == "alive":
                        edition.verified_at = now
                    summary["updated"] += int(changed)
                    summary["rolled"] += int(roll_forward(session, edition, now=now))
                session.flush()
        except Exception as exc:
            summary["errors"] += 1
            # Exception text may contain DB parameters. Only log the type.
            logger.warning("Calendar %s refresh failed (%s)", programme.slug, type(exc).__name__)
    return summary


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    with httpx.Client() as client, Session(make_engine()) as session:
        summary = refresh_calendar(session, CalendarPageFetcher(client))
        session.commit()
    logger.info("Calendar summary %s", summary)


if __name__ == "__main__":
    main()
