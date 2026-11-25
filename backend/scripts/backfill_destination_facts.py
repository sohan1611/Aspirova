"""Founder-run TRUST-01 backfill; default is a read-only dry run. No network or .env."""

import argparse
import os
from datetime import datetime, timezone

from sqlalchemy import BigInteger, column, create_engine, select, update, values
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import make_url
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from core import models
from core.destination_facts import destination_facts_need_refresh, refresh_destination_facts


def chosen_engine() -> Engine:
    value = os.environ.get("DATABASE_URL", "").strip()
    if not value:
        raise ValueError("Set DATABASE_URL explicitly in this shell")
    url = make_url(value)
    if url.drivername in {"postgres", "postgresql"}:
        url = url.set(drivername="postgresql+psycopg")
    if url.get_backend_name() != "postgresql":
        raise ValueError("A PostgreSQL connection is required")
    return create_engine(url, connect_args={"connect_timeout": 10})


def needs_backfill(facts: dict | None, url: str, **context) -> bool:
    return destination_facts_need_refresh(facts, url, **context)


def backfill_destination_facts(
    bind: Engine,
    *,
    batch: int = 500,
    dry_run: bool = True,
) -> dict[str, int]:
    if batch < 1:
        raise ValueError("batch must be positive")
    opportunity, company = models.Opportunity, models.Company
    cursor = updated = pending = scanned = 0
    while True:
        with bind.connect().execution_options(postgresql_readonly=dry_run) as connection:
            with connection.begin(), Session(bind=connection) as session:
                connection.exec_driver_sql("SET LOCAL lock_timeout = '3s'")
                connection.exec_driver_sql("SET LOCAL statement_timeout = '30s'")
                query = (
                    select(
                        opportunity.id,
                        opportunity.apply_url,
                        opportunity.primary_source,
                        opportunity.company_id,
                        opportunity.destination_facts,
                        company.domain,
                        company.ats_type,
                        company.ats_board_id,
                    )
                    .outerjoin(company, opportunity.company_id == company.id)
                    .where(opportunity.id > cursor)
                    .order_by(opportunity.id)
                    .limit(batch)
                )
                if not dry_run:
                    query = query.with_for_update(of=opportunity)
                rows = session.execute(query).all()
                if not rows:
                    break
                updates = []
                for row in rows:
                    scanned += 1
                    context = dict(
                        source=row.primary_source,
                        company_id=row.company_id,
                        company_domain=row.domain,
                        ats_type=row.ats_type,
                        ats_board_id=row.ats_board_id,
                    )
                    if not needs_backfill(row.destination_facts, row.apply_url, **context):
                        continue
                    pending += 1
                    # Dry run computes too, exposing parser issues without writes.
                    facts = refresh_destination_facts(
                        row.apply_url,
                        row.destination_facts,
                        computed_at=datetime.now(timezone.utc).isoformat(),
                        **context,
                    )
                    if not dry_run:
                        updates.append((row.id, facts))
                if updates:
                    parsed = values(
                        column("id", BigInteger),
                        column("facts", JSONB),
                        name="destination_backfill",
                    ).data(updates)
                    # Selected rows stay locked through this single batch UPDATE.
                    result = session.execute(
                        update(opportunity)
                        .where(opportunity.id == parsed.c.id)
                        .values(destination_facts=parsed.c.facts)
                        .execution_options(synchronize_session=False)
                    )
                    updated += result.rowcount
                cursor = rows[-1].id
    result = {"scanned": scanned, "pending": pending, "updated": updated}
    print(" ".join(f"{key}={value}" for key, value in result.items()))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--batch", type=int, default=500)
    args = parser.parse_args()
    try:
        engine = chosen_engine()
        try:
            backfill_destination_facts(engine, batch=args.batch, dry_run=not args.apply)
        finally:
            engine.dispose()
    except (SQLAlchemyError, ValueError):
        # Connection exceptions can embed passwords and parameters.
        parser.exit(
            2, "Backfill failed; check connection/arguments. Completed batches are committed.\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
