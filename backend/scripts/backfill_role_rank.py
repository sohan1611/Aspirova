"""Fill legacy NULL role ranks in short transactions; counts only.

From backend/, with DATABASE_URL explicitly set to the database you choose:
    uv run python -m scripts.backfill_role_rank --dry-run
    uv run python -m scripts.backfill_role_rank --batch 2000

The migration must be applied first. This script never changes titles or meta.
"""

import argparse
import os

from sqlalchemy import func, select, update
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from core import models

LOCK_TIMEOUT = "3s"
STATEMENT_TIMEOUT = "30s"


def _set_timeouts(session: Session) -> None:
    session.connection().exec_driver_sql(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'")
    session.connection().exec_driver_sql(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'")


def backfill_role_rank(
    bind: Engine | Connection,
    *,
    batch: int = 1000,
    dry_run: bool = False,
    include_inactive: bool = False,
) -> dict[str, int]:
    if batch < 1:
        raise ValueError("batch must be positive")
    opportunity = models.Opportunity
    scope = [opportunity.role_rank.is_(None)]
    if not include_inactive:
        scope.append(opportunity.status == "active")
    updated = 0
    if not dry_run:
        while True:
            # A new Session per batch commits and releases its locks promptly.
            # Savepoint joining lets tests roll all batches back on their connection.
            with (
                Session(bind, join_transaction_mode="create_savepoint") as session,
                session.begin(),
            ):
                _set_timeouts(session)
                ids = session.scalars(
                    select(opportunity.id)
                    .where(*scope)
                    .order_by(opportunity.id)
                    .limit(batch)
                    .with_for_update()
                ).all()
                if not ids:
                    break
                result = session.execute(
                    update(opportunity)
                    .where(opportunity.id.in_(ids), opportunity.role_rank.is_(None))
                    .values(
                        role_rank=func.opportunity_role_rank(
                            opportunity.title, opportunity.category, opportunity.meta
                        )
                    )
                    .execution_options(synchronize_session=False)
                )
                updated += result.rowcount
    with Session(bind, join_transaction_mode="create_savepoint") as session, session.begin():
        _set_timeouts(session)
        remaining = session.scalar(select(func.count()).select_from(opportunity).where(*scope))
    counts = {"updated": updated, "remaining_null": remaining}
    print(f"rows_updated={updated} remaining_null={remaining}", flush=True)
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", type=int, default=1000)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--all",
        action="store_true",
        help="also fill closed/withdrawn rows (not needed for ranking)",
    )
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
        backfill_role_rank(
            engine, batch=args.batch, dry_run=args.dry_run, include_inactive=args.all
        )
    except SQLAlchemyError:
        # Driver exceptions may contain credentials; keep them out of output.
        parser.exit(1, "Backfill query failed; completed batches remain committed.\n")
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
