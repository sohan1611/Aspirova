"""Null out implausibly far-future competition deadlines.

Usage:
    uv run python -m scripts.fix_garbage_deadlines
    uv run python -m scripts.fix_garbage_deadlines --apply
"""

import argparse
from datetime import datetime, timezone

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from core import models
from core.db import make_engine
from crawlers.common import MAX_DEADLINE_HORIZON

GARBAGE_DEADLINE_CATEGORIES = ("competition", "hackathon")
MAINTENANCE_STATEMENT_TIMEOUT = "120s"
SAMPLE_SIZE = 10


def _matching_filters(cutoff: datetime) -> tuple[ColumnElement[bool], ...]:
    return (
        models.Opportunity.category.in_(GARBAGE_DEADLINE_CATEGORIES),
        models.Opportunity.deadline.is_not(None),
        models.Opportunity.deadline > cutoff,
    )


def garbage_deadline_count(session: Session, *, cutoff: datetime) -> int:
    count = session.scalar(
        select(func.count()).select_from(models.Opportunity).where(*_matching_filters(cutoff))
    )
    return int(count or 0)


def garbage_deadline_sample(
    session: Session,
    *,
    cutoff: datetime,
    sample_size: int = SAMPLE_SIZE,
) -> list[dict[str, object]]:
    rows = session.execute(
        select(
            models.Opportunity.id,
            models.Opportunity.title,
            models.Opportunity.category,
            models.Opportunity.deadline,
        )
        .where(*_matching_filters(cutoff))
        .order_by(models.Opportunity.deadline.desc(), models.Opportunity.id)
        .limit(sample_size)
    ).mappings()
    return [dict(row) for row in rows]


def fix_garbage_deadlines(session: Session, *, cutoff: datetime) -> int:
    result = session.execute(
        update(models.Opportunity)
        .where(*_matching_filters(cutoff))
        .values(deadline=None, deadline_confidence="unknown")
    )
    return int(result.rowcount or 0)


def _format_sample_row(row: dict[str, object]) -> str:
    title = str(row["title"])
    if len(title) > 80:
        title = f"{title[:77]}..."
    return f"- {row['id']} | {row['category']} | {row['deadline']} | {title}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Null competition/hackathon deadlines beyond the plausibility horizon."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Preview only (default).")
    mode.add_argument("--apply", action="store_true", help="Apply cleanup and commit.")
    args = parser.parse_args()

    cutoff = datetime.now(timezone.utc) + MAX_DEADLINE_HORIZON
    engine = make_engine()
    with Session(engine) as session:
        session.execute(text(f"SET statement_timeout = '{MAINTENANCE_STATEMENT_TIMEOUT}'"))
        count = garbage_deadline_count(session, cutoff=cutoff)
        sample = garbage_deadline_sample(session, cutoff=cutoff)

        mode_label = "apply" if args.apply else "dry-run"
        print(f"mode: {mode_label}", flush=True)
        print(f"cutoff: {cutoff.isoformat()}", flush=True)
        print(f"garbage deadlines found: {count}", flush=True)
        if sample:
            print("sample:", flush=True)
            for row in sample:
                print(_format_sample_row(row), flush=True)

        if args.apply:
            updated_count = fix_garbage_deadlines(session, cutoff=cutoff)
            session.commit()
            print(f"garbage deadlines fixed: {updated_count}", flush=True)
        else:
            session.rollback()
            print("dry-run only; no rows updated", flush=True)


if __name__ == "__main__":
    main()
