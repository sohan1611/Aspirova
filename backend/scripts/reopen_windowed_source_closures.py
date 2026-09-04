"""Reopen listings wrongly closed by the aggregator absence branch.

PR #116 added a second "absence" branch to pipeline/expire.py that closes an
opportunity when its aggregator source stops listing it. That reasoning holds for
the original ATS branch - crawling a company's board fetches that company's whole
board, so absence is evidence - but not for aggregator feeds that return a
rolling window instead of a full inventory.

Measured in production after the first crawl carrying that branch (2026-09-04):

    source      listings_found   still open   closed that run
    remoteok    100              100          1001
    himalayas   73                56           772
    arbeitnow   54                52           165
    jobicy       3                 2            43

Every windowed source's open catalogue collapsed to exactly one crawl's worth.
RemoteOK's feed returns ~100 recent jobs and is not an inventory; three of the
closed RemoteOK URLs were spot-checked and all three still returned HTTP 200.

This script clears `closed_at` on the rows that branch closed without evidence.
It deliberately does NOT touch:
  - rows whose company has an ats_type (closed by the sound ATS branch),
  - rows from FULL_INVENTORY_SOURCES, whose feeds do enumerate everything open,
  - rows whose own deadline has genuinely passed, which are correctly closed.

Pair this with the coverage guard in pipeline/expire.py. Running the repair
without that guard only buys one day: the next crawl closes them again.

Usage:
    uv run python -m scripts.reopen_windowed_source_closures
    uv run python -m scripts.reopen_windowed_source_closures --apply
    uv run python -m scripts.reopen_windowed_source_closures --since 2026-09-04 --apply
"""

import argparse
from datetime import date, datetime

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from core import models
from core.db import make_engine

# Sources whose crawl enumerates the complete open inventory, so absence really
# is evidence. Keep this in step with FULL_INVENTORY_SOURCES in
# pipeline/expire.py - rows from these are correctly closed and must not be
# reopened here.
FULL_INVENTORY_SOURCES = ("unstop", "devpost", "devfolio")

MAINTENANCE_STATEMENT_TIMEOUT = "120s"
SAMPLE_SIZE = 10


def _matching_filters(*, since: date) -> tuple[ColumnElement[bool], ...]:
    return (
        # Only the aggregator branch's work: ATS-sourced rows hang off a company
        # with an ats_type and were closed by the branch that is still correct.
        models.Company.ats_type.is_(None),
        models.Opportunity.company_id == models.Company.id,
        models.Opportunity.status == "active",
        models.Opportunity.closed_at.is_not(None),
        func.date(models.Opportunity.closed_at) >= since,
        models.Opportunity.primary_source.not_in(FULL_INVENTORY_SOURCES),
        # A passed deadline closes a listing on its own and that is correct, so
        # leave those closed rather than resurrecting genuinely dead rows.
        (models.Opportunity.deadline.is_(None)) | (models.Opportunity.deadline >= func.now()),
    )


def affected_count(session: Session, *, since: date) -> int:
    count = session.scalar(
        select(func.count())
        .select_from(models.Opportunity)
        .join(models.Company, models.Company.id == models.Opportunity.company_id)
        .where(*_matching_filters(since=since))
    )
    return int(count or 0)


def affected_by_source(session: Session, *, since: date) -> list[dict[str, object]]:
    rows = session.execute(
        select(
            models.Opportunity.primary_source,
            models.Opportunity.category,
            func.count().label("rows"),
        )
        .select_from(models.Opportunity)
        .join(models.Company, models.Company.id == models.Opportunity.company_id)
        .where(*_matching_filters(since=since))
        .group_by(models.Opportunity.primary_source, models.Opportunity.category)
        .order_by(func.count().desc())
    ).mappings()
    return [dict(row) for row in rows]


def sample_rows(
    session: Session, *, since: date, sample_size: int = SAMPLE_SIZE
) -> list[dict[str, object]]:
    rows = session.execute(
        select(
            models.Opportunity.id,
            models.Opportunity.primary_source,
            models.Opportunity.title,
            models.Opportunity.apply_url,
        )
        .select_from(models.Opportunity)
        .join(models.Company, models.Company.id == models.Opportunity.company_id)
        .where(*_matching_filters(since=since))
        .order_by(models.Opportunity.last_seen_at.desc(), models.Opportunity.id)
        .limit(sample_size)
    ).mappings()
    return [dict(row) for row in rows]


def reopen(session: Session, *, since: date) -> int:
    """Clear closed_at on the affected rows.

    The filters join Company, which an UPDATE cannot do directly, so the ids are
    selected first and the update is keyed on them.
    """
    ids = list(
        session.scalars(
            select(models.Opportunity.id)
            .select_from(models.Opportunity)
            .join(models.Company, models.Company.id == models.Opportunity.company_id)
            .where(*_matching_filters(since=since))
        )
    )
    if not ids:
        return 0

    updated = 0
    # Chunked so one statement never carries tens of thousands of bind params.
    for start in range(0, len(ids), 1000):
        chunk = ids[start : start + 1000]
        result = session.execute(
            update(models.Opportunity)
            .where(models.Opportunity.id.in_(chunk))
            .values(closed_at=None)
            .execution_options(synchronize_session=False)
        )
        updated += int(result.rowcount or 0)
    return updated


def _format_sample_row(row: dict[str, object]) -> str:
    title = str(row["title"])
    if len(title) > 60:
        title = f"{title[:57]}..."
    return f"- {row['id']} | {row['primary_source']} | {title} | {row['apply_url']}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reopen listings closed by the aggregator absence branch without evidence."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Preview only (default).")
    mode.add_argument("--apply", action="store_true", help="Apply the repair and commit.")
    parser.add_argument(
        "--since",
        type=lambda value: datetime.strptime(value, "%Y-%m-%d").date(),
        default=date(2026, 9, 4),
        help="Only reopen rows closed on or after this date (default: 2026-09-04, "
        "the first crawl that carried the faulty branch).",
    )
    args = parser.parse_args()

    engine = make_engine()
    with Session(engine) as session:
        session.execute(text(f"SET statement_timeout = '{MAINTENANCE_STATEMENT_TIMEOUT}'"))
        count = affected_count(session, since=args.since)
        breakdown = affected_by_source(session, since=args.since)
        sample = sample_rows(session, since=args.since)

        print(f"mode: {'apply' if args.apply else 'dry-run'}", flush=True)
        print(f"closed on or after: {args.since.isoformat()}", flush=True)
        print(f"wrongly closed rows found: {count}", flush=True)
        if breakdown:
            print("by source:", flush=True)
            for row in breakdown:
                print(
                    f"- {row['primary_source']:<12} {row['category']:<12} {row['rows']}", flush=True
                )
        if sample:
            print("sample:", flush=True)
            for row in sample:
                print(_format_sample_row(row), flush=True)

        if args.apply:
            reopened = reopen(session, since=args.since)
            session.commit()
            print(f"rows reopened: {reopened}", flush=True)
        else:
            session.rollback()
            print("dry-run only; no rows updated", flush=True)


if __name__ == "__main__":
    main()
