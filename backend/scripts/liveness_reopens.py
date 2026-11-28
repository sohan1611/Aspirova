"""Report per-source counts of rows reopened by liveness in a recent window."""

import argparse
from datetime import datetime, timedelta, timezone

from sqlalchemy import DateTime, case, cast, func, select, text
from sqlalchemy.exc import SQLAlchemyError

from core.db import make_engine
from core.freshness import SOURCE_CADENCE
from core.models import Opportunity


def reopen_counts(connection, *, since: datetime) -> list:
    source = case(
        {name: name for name in SOURCE_CADENCE}, value=Opportunity.primary_source, else_="other"
    ).label("source")
    liveness_at = cast(Opportunity.meta["liveness_reopened_at"].astext, DateTime(timezone=True))
    any_reopen_at = cast(Opportunity.meta["alert_reopened_at"].astext, DateTime(timezone=True))
    query = (
        select(
            source,
            func.count().filter(liveness_at >= since).label("liveness"),
            func.count()
            .filter(liveness_at.is_(None), any_reopen_at >= since)
            .label("unattributed"),
        )
        .where((liveness_at >= since) | (liveness_at.is_(None) & (any_reopen_at >= since)))
        .group_by(source)
        .order_by(source)
    )
    return connection.execute(query).all()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args()
    if not 1 <= args.days <= 365:
        parser.error("--days must be between 1 and 365")
    since = datetime.now(timezone.utc) - timedelta(days=args.days)
    try:
        with make_engine().begin() as connection:
            connection.execute(text("SET TRANSACTION READ ONLY"))
            connection.execute(text("SET LOCAL statement_timeout = '120s'"))
            rows = reopen_counts(connection, since=since)
    except SQLAlchemyError:
        print("LIVENESS REOPENS: unavailable errors=1", flush=True)
        raise SystemExit(1) from None
    for source, liveness, unattributed in rows:
        print(
            f"LIVENESS REOPENS {source}: days={args.days} liveness={liveness} "
            f"unattributed={unattributed}",
            flush=True,
        )
    print(
        f"LIVENESS REOPENS total: days={args.days} liveness={sum(row.liveness for row in rows)} "
        f"unattributed={sum(row.unattributed for row in rows)}",
        flush=True,
    )


if __name__ == "__main__":
    main()
