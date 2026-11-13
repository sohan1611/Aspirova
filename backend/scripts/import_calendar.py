"""Idempotently import the founder's calendar. Safe on the pre-category-migration DB."""

from datetime import datetime
import logging

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.db import make_engine
from core.hiring_calendar import CALENDAR_META, IST, ROWS, month_date, source_window
from core.models import Programme, ProgrammeEdition

logger = logging.getLogger(__name__)


def _restore_opening_windows(session: Session, programme_id: int, meta: dict, window: dict) -> None:
    if not window["deadline_rolling"]:
        return
    editions = session.scalars(
        select(ProgrammeEdition).where(
            ProgrammeEdition.programme_id == programme_id,
        )
    )
    for edition in editions:
        notes = edition.notes or ""
        if "calendar_exact_closes_at" in notes:
            continue
        if edition.closes_at is not None:
            # Previously verified cutoffs take precedence over the source's
            # unfixed deadline. Keep the date and record its provenance.
            if "calendar_deadline_rolling" not in notes:
                edition.notes = f"{notes}\ncalendar_exact_closes_at".strip()
            continue
        if edition.opens_at is None:
            if edition.status != "expected" and (
                window["status"] == "expected" or edition.year != meta["cycle_year"]
            ):
                continue
            source_opening = window["opens_at"]
            year = source_opening.year + edition.year - meta["cycle_year"]
            edition.opens_at = source_opening.replace(year=year)
            if edition.status == "expected":
                edition.opens_at = month_date(year, source_opening.month)
        source_closing = window["closes_at"]
        source_opening = window["opens_at"]
        opening = edition.opens_at.astimezone(IST)
        source_year = source_opening.year + edition.year - meta["cycle_year"]
        if (opening.year, opening.month) == (source_year, source_opening.month):
            year = source_closing.year + edition.year - meta["cycle_year"]
            edition.closes_at = month_date(year, source_closing.month, end=True)
        else:
            edition.closes_at = month_date(opening.year, opening.month, end=True)
        if "calendar_deadline_rolling" not in notes:
            edition.notes = f"{notes}\ncalendar_deadline_rolling".strip()


def category_for(row: dict) -> str:
    if row["category"] in {"open_source", "early_career"}:
        return row["category"]
    if row["category"] == "Govt":
        return "government_internship"
    if row["category"] == "Competition":
        return "recurring_competition"
    if row["category"] == "Tech":
        return "early_career"
    return (
        "research_internship" if row["geography"].startswith("India") else "international_research"
    )


def _import_row(session: Session, slug: str, meta: dict) -> None:
    row = ROWS[meta["row_id"]]
    programme = session.scalar(select(Programme).where(Programme.slug == slug).with_for_update())
    if programme is None:
        programme = session.scalar(
            select(Programme)
            .where(
                Programme.organiser.ilike(meta["organiser"]),
                or_(Programme.name.ilike(row["opportunity"]), Programme.name.ilike(meta["name"])),
            )
            .with_for_update()
        )
    values = {
        "name": meta["name"],
        "organiser": meta["organiser"],
        "category": category_for(row),
        "url": row["official_portal"],
        "eligibility": row["target_batch_eligibility"],
        "typical_window": f'{row["application_open"]} · {row["registration_deadline"]}',
        "country": "IN" if row["geography"].startswith("India") else None,
    }
    if programme is None:
        session.execute(
            insert(Programme)
            .values(slug=slug, tags=[], **values)
            .on_conflict_do_nothing(index_elements=["slug"])
        )
        programme = session.scalar(
            select(Programme).where(Programme.slug == slug).with_for_update()
        )
    else:
        # Keep the canonical slug stable. Known registry aliases are in metadata.
        for key, value in values.items():
            setattr(programme, key, value)
    session.flush()
    window = source_window(slug)
    verified_at = datetime.fromisoformat(row["source_checked_on"]).replace(tzinfo=IST)
    edition = session.scalar(
        select(ProgrammeEdition).where(
            ProgrammeEdition.programme_id == programme.id,
            ProgrammeEdition.year == meta["cycle_year"],
        )
    )
    # Repair dates omitted by the old rolling classification, including
    # projected editions, while preserving verification timestamps and status.
    _restore_opening_windows(session, programme.id, meta, window)
    # A daily import must preserve crawler discoveries and later human checks.
    if edition is not None and edition.status != "expected" and window["status"] == "expected":
        return
    if (
        edition is not None
        and edition.verified_at is not None
        and edition.verified_at >= verified_at
    ):
        return
    edition_values = {key: window[key] for key in ("status", "opens_at", "closes_at", "notes")}
    edition_values.update(source_url=row["official_portal"], verified_at=verified_at)
    if edition is None:
        session.execute(
            insert(ProgrammeEdition)
            .values(programme_id=programme.id, year=meta["cycle_year"], **edition_values)
            .on_conflict_do_nothing(index_elements=["programme_id", "year"])
        )
    else:
        for key, value in edition_values.items():
            setattr(edition, key, value)
    session.flush()


def import_calendar(session: Session) -> dict[str, int]:
    imported, skipped = 0, 0
    for slug, meta in CALENDAR_META.items():
        try:
            with session.begin_nested():
                _import_row(session, slug, meta)
            imported += 1
        except IntegrityError as exc:
            diagnostic = getattr(exc.orig, "diag", None)
            if getattr(diagnostic, "constraint_name", None) != "ck_programmes_category":
                raise
            skipped += 1
            logger.warning(
                "Calendar row %s (%s) skipped by ck_programmes_category. Apply alembic upgrade head",
                meta["row_id"],
                slug,
            )
    return {"imported": imported, "skipped": skipped}


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    with Session(make_engine()) as session:
        summary = import_calendar(session)
        session.commit()
    logger.info("Calendar import %s", summary)


if __name__ == "__main__":
    main()
