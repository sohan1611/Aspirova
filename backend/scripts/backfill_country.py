"""Backfill each opportunity's denormalized country code.

Usage: uv run python -m scripts.backfill_country
"""

from sqlalchemy import case, select, text, update
from sqlalchemy.orm import Session

from core import models
from core.db import make_engine
from pipeline.location_country import derive_country

BATCH_SIZE = 500
# Maintenance timeout for the batch job: the API-side statement_timeout
# (core/db.py) is deliberately tight; a large backfill needs more headroom.
MAINTENANCE_STATEMENT_TIMEOUT = "120s"


def backfill_country(
    session: Session,
    *,
    batch_size: int = BATCH_SIZE,
    commit_each_batch: bool = False,
) -> int:
    """Fill missing country codes in batches without overwriting existing values."""
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")

    updated_count = 0
    last_id: int | None = None

    while True:
        statement = (
            select(models.Opportunity.id, models.Opportunity.location)
            .where(models.Opportunity.country.is_(None))
            .order_by(models.Opportunity.id)
            .limit(batch_size)
        )
        if last_id is not None:
            statement = statement.where(models.Opportunity.id > last_id)

        rows = list(session.execute(statement).all())
        if not rows:
            break

        country_by_id: dict[int, str] = {}
        for opportunity_id, location in rows:
            country = derive_country(location)
            if country is not None:
                country_by_id[opportunity_id] = country

        if country_by_id:
            result = session.execute(
                update(models.Opportunity)
                .where(
                    models.Opportunity.id.in_(country_by_id),
                    models.Opportunity.country.is_(None),
                )
                .values(country=case(country_by_id, value=models.Opportunity.id))
            )
            updated_count += result.rowcount

        if commit_each_batch:
            session.commit()

        last_id = rows[-1].id

    return updated_count


def main() -> None:
    engine = make_engine()
    with Session(engine) as session:
        session.execute(text(f"SET statement_timeout = '{MAINTENANCE_STATEMENT_TIMEOUT}'"))
        updated_count = backfill_country(session, commit_each_batch=True)

    print(f"opportunities updated with country: {updated_count}", flush=True)


if __name__ == "__main__":
    main()
