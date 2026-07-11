"""Backfill each opportunity's denormalized primary source.

Usage: uv run python -m scripts.backfill_primary_source
"""

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from core import models
from core.db import make_engine

BATCH_SIZE = 500
# Maintenance timeout for the batch job: the API-side statement_timeout
# (core/db.py) is deliberately tight; a large backfill needs more headroom.
MAINTENANCE_STATEMENT_TIMEOUT = "120s"


def backfill_primary_source(
    session: Session,
    *,
    batch_size: int = BATCH_SIZE,
    commit_each_batch: bool = False,
) -> int:
    """Fill missing primary sources in batches without overwriting existing values."""
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")

    has_provenance = (
        select(models.OpportunitySource.id)
        .where(models.OpportunitySource.opportunity_id == models.Opportunity.id)
        .exists()
    )
    preferred_source = (
        select(models.Source.slug)
        .join(
            models.OpportunitySource,
            models.OpportunitySource.source_id == models.Source.id,
        )
        .where(models.OpportunitySource.opportunity_id == models.Opportunity.id)
        .order_by(
            models.OpportunitySource.is_primary.desc(),
            models.OpportunitySource.seen_at.asc(),
            models.OpportunitySource.id.asc(),
        )
        .limit(1)
        .correlate(models.Opportunity)
        .scalar_subquery()
    )
    updated_count = 0

    while True:
        opportunity_ids = list(
            session.scalars(
                select(models.Opportunity.id)
                .where(
                    models.Opportunity.primary_source.is_(None),
                    has_provenance,
                )
                .order_by(models.Opportunity.id)
                .limit(batch_size)
            ).all()
        )
        if not opportunity_ids:
            break

        result = session.execute(
            update(models.Opportunity)
            .where(
                models.Opportunity.id.in_(opportunity_ids),
                models.Opportunity.primary_source.is_(None),
            )
            .values(primary_source=preferred_source)
        )
        updated_count += result.rowcount

        if commit_each_batch:
            session.commit()

    return updated_count


def main() -> None:
    engine = make_engine()
    with Session(engine) as session:
        session.execute(text(f"SET statement_timeout = '{MAINTENANCE_STATEMENT_TIMEOUT}'"))
        updated_count = backfill_primary_source(session, commit_each_batch=True)

    print(f"opportunities updated with primary_source: {updated_count}", flush=True)


if __name__ == "__main__":
    main()
