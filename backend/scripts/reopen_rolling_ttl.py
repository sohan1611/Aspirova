"""Reopen premature rolling-feed TTL closures on one UTC date; dry-run by default."""

import argparse
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import case, func, select, text, update
from sqlalchemy.orm import Session

from core.db import make_engine
from core.models import Opportunity
from pipeline.retirement import ROLLING_WINDOW_TTL_DAYS


@dataclass
class ReopenResult:
    candidates: int = 0
    categories: Counter[str | None] = field(default_factory=Counter)
    min_last_seen_at: datetime | None = None
    max_last_seen_at: datetime | None = None
    excluded: Counter[str] = field(default_factory=Counter)
    reopened: int = 0


def reopen_rolling_ttl(
    session: Session,
    *,
    closed_on: date,
    source: str = "himalayas",
    apply: bool = False,
) -> ReopenResult:
    """Report date-scoped exclusions and optionally reopen candidates. Caller commits."""
    ttl_days = ROLLING_WINDOW_TTL_DAYS[source]
    cutoff = session.scalar(select(func.now())) - timedelta(days=ttl_days)
    start = datetime.combine(closed_on, time.min, tzinfo=timezone.utc)
    statement = select(
        Opportunity.id,
        Opportunity.primary_source,
        Opportunity.status,
        Opportunity.category,
        Opportunity.last_seen_at,
        Opportunity.meta["closed_reason"].astext.label("closed_reason"),
    ).where(Opportunity.closed_at >= start, Opportunity.closed_at < start + timedelta(days=1))
    if apply:
        # Keep the reported candidates stable until the caller's single commit.
        statement = statement.with_for_update()
    rows = session.execute(statement).all()
    result = ReopenResult()
    candidate_ids = []
    for row in rows:
        if row.primary_source != source:
            result.excluded["different source"] += 1
        elif row.status != "active":
            result.excluded["status is not active"] += 1
        elif row.closed_reason not in {None, "rolling_window_ttl"}:
            result.excluded[f"closed_reason={row.closed_reason}"] += 1
        elif row.last_seen_at is None or row.last_seen_at < cutoff:
            result.excluded[f"last_seen_at outside {ttl_days}-day TTL"] += 1
        else:
            candidate_ids.append(row.id)
            result.categories[row.category] += 1
            result.min_last_seen_at = min(
                result.min_last_seen_at or row.last_seen_at, row.last_seen_at
            )
            result.max_last_seen_at = max(
                result.max_last_seen_at or row.last_seen_at, row.last_seen_at
            )
    result.candidates = len(candidate_ids)
    if apply and candidate_ids:
        updated = session.execute(
            update(Opportunity)
            .where(Opportunity.id.in_(candidate_ids))
            .values(
                closed_at=None,
                meta=case(
                    (
                        func.jsonb_typeof(Opportunity.meta) == "object",
                        Opportunity.meta.op("-")(text("'closed_reason'")),
                    ),
                    else_=Opportunity.meta,
                ),
            )
            .execution_options(synchronize_session=False)
        )
        result.reopened = int(updated.rowcount or 0)
    return result


def _closed_on(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() == value:
            return parsed
    except ValueError:
        pass
    raise argparse.ArgumentTypeError("--closed-on must be YYYY-MM-DD")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--dry-run", action="store_true", help="preview only (default)")
    parser.add_argument("--closed-on", type=_closed_on, required=True, help="UTC date, YYYY-MM-DD")
    parser.add_argument("--source", choices=sorted(ROLLING_WINDOW_TTL_DAYS), default="himalayas")
    args = parser.parse_args(argv)
    engine = make_engine()
    try:
        with Session(engine) as session:
            result = reopen_rolling_ttl(
                session, closed_on=args.closed_on, source=args.source, apply=args.apply
            )
            if args.apply:
                session.commit()
            else:
                session.rollback()
            print(f"REOPEN TTL: candidates found: {result.candidates}", flush=True)
            for category, count in sorted(result.categories.items(), key=lambda item: str(item[0])):
                print(f"  category {category!r}: {count}")
            print(f"  min last_seen_at: {result.min_last_seen_at}")
            print(f"  max last_seen_at: {result.max_last_seen_at}")
            print(f"  excluded on {args.closed_on}: {sum(result.excluded.values())}")
            for reason, count in sorted(result.excluded.items()):
                print(f"  excluded {reason}: {count}")
            print(f"REOPEN TTL: rows reopened: {result.reopened}" if args.apply else "DRY RUN")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
