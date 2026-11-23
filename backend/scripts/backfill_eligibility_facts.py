"""Fill missing/older eligibility facts in short, founder-run transactions.

From backend/, explicitly set DATABASE_URL to the database you choose, then:
    uv run python -m scripts.backfill_eligibility_facts --dry-run
    uv run python -m scripts.backfill_eligibility_facts --batch 500 [--all]
"""

import argparse
import os

from sqlalchemy import BigInteger, column, func, or_, select, update, values
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from core import models
from core.eligibility_facts import ELIGIBILITY_FACTS_VERSION, extract_eligibility_facts


def _set_timeouts(session: Session) -> None:
    session.connection().exec_driver_sql("SET LOCAL lock_timeout = '3s'")
    session.connection().exec_driver_sql("SET LOCAL statement_timeout = '30s'")


def backfill_eligibility_facts(
    bind: Engine | Connection,
    *,
    batch: int = 500,
    dry_run: bool = False,
    include_inactive: bool = False,
) -> dict[str, int]:
    if batch < 1:
        raise ValueError("batch must be positive")
    opportunity = models.Opportunity
    scope = [
        or_(
            opportunity.eligibility_facts.is_(None),
            opportunity.eligibility_facts["v"].as_integer() < ELIGIBILITY_FACTS_VERSION,
        )
    ]
    if not include_inactive:
        scope.append(opportunity.status == "active")
    updated = 0
    if not dry_run:
        while True:
            with (
                Session(bind, join_transaction_mode="create_savepoint") as session,
                session.begin(),
            ):
                _set_timeouts(session)
                rows = session.execute(
                    select(
                        opportunity.id,
                        opportunity.title,
                        opportunity.description_raw,
                        opportunity.meta,
                    )
                    .where(*scope)
                    .order_by(opportunity.id)
                    .limit(batch)
                    .with_for_update()
                ).all()
                if not rows:
                    break
                parsed = values(
                    column("id", BigInteger), column("facts", JSONB), name="parsed"
                ).data(
                    [
                        (
                            row.id,
                            extract_eligibility_facts(row.title, row.description_raw, row.meta),
                        )
                        for row in rows
                    ]
                )
                result = session.execute(
                    update(opportunity.__table__)
                    .where(opportunity.id == parsed.c.id, *scope)
                    .values(eligibility_facts=parsed.c.facts)
                )
                updated += result.rowcount
    with Session(bind, join_transaction_mode="create_savepoint") as session, session.begin():
        _set_timeouts(session)
        remaining = session.scalar(select(func.count()).select_from(opportunity).where(*scope)) or 0
    counts = {"updated": updated, "remaining": remaining}
    print(f"rows_updated={updated} remaining={remaining}", flush=True)
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", type=int, default=500)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--all", action="store_true", help="include inactive rows")
    args = parser.parse_args()
    if args.batch < 1:
        parser.error("--batch must be positive")
    if not os.environ.get("DATABASE_URL", "").strip():
        parser.error("Set DATABASE_URL explicitly to the database you choose")
    from core.config import get_settings
    from core.db import make_engine

    get_settings.cache_clear()
    engine = make_engine()
    try:
        backfill_eligibility_facts(
            engine, batch=args.batch, dry_run=args.dry_run, include_inactive=args.all
        )
    except SQLAlchemyError:
        parser.exit(1, "Backfill query failed; completed batches remain committed.\n")
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
