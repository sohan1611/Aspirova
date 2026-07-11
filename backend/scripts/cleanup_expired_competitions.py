"""Hard-delete expiring opportunities after their 14-day closed grace window.

Usage: uv run python -m scripts.cleanup_expired_competitions
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, text, update
from sqlalchemy.orm import Session

from core import models
from core.db import make_engine

CLOSED_GRACE_DAYS = 14
BATCH_SIZE = 200
# Maintenance timeout for the batch job: the API-side statement_timeout
# (core/db.py) is deliberately tight; a large prune needs more headroom.
MAINTENANCE_STATEMENT_TIMEOUT = "120s"
EXPIRING_CATEGORIES = ("hackathon", "competition", "internship")


def cleanup_expired_competitions(
    session: Session,
    *,
    now: datetime | None = None,
    batch_size: int = BATCH_SIZE,
    commit_each_batch: bool = False,
) -> int:
    """Prune expired opportunities in batches without committing the transaction."""
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")

    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=CLOSED_GRACE_DAYS)
    deleted_count = 0

    while True:
        opportunity_ids = list(
            session.scalars(
                select(models.Opportunity.id)
                .where(
                    models.Opportunity.category.in_(EXPIRING_CATEGORIES),
                    models.Opportunity.deadline.is_not(None),
                    models.Opportunity.deadline < cutoff,
                )
                .order_by(models.Opportunity.id)
                .limit(batch_size)
            ).all()
        )
        if not opportunity_ids:
            break

        session.execute(
            delete(models.OpportunitySource).where(
                models.OpportunitySource.opportunity_id.in_(opportunity_ids)
            )
        )
        session.execute(
            delete(models.OpportunityTag).where(
                models.OpportunityTag.opportunity_id.in_(opportunity_ids)
            )
        )
        session.execute(
            delete(models.Bookmark).where(models.Bookmark.opportunity_id.in_(opportunity_ids))
        )
        session.execute(
            update(models.RawListing)
            .where(models.RawListing.opportunity_id.in_(opportunity_ids))
            .values(opportunity_id=None)
        )
        session.execute(
            update(models.Notification)
            .where(models.Notification.opportunity_id.in_(opportunity_ids))
            .values(opportunity_id=None)
        )
        result = session.execute(
            delete(models.Opportunity).where(models.Opportunity.id.in_(opportunity_ids))
        )
        deleted_count += result.rowcount

        if commit_each_batch:
            session.commit()

    return deleted_count


def main() -> None:
    engine = make_engine()
    with Session(engine) as session:
        session.execute(text(f"SET statement_timeout = '{MAINTENANCE_STATEMENT_TIMEOUT}'"))
        deleted_count = cleanup_expired_competitions(session, commit_each_batch=True)

    print(f"expired opportunities deleted: {deleted_count}", flush=True)


if __name__ == "__main__":
    main()
