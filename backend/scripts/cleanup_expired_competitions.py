"""Hard-delete closed opportunities after their 14-day closed grace window.

Usage: uv run python -m scripts.cleanup_expired_competitions
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select, text, update
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
    deadline_expired = (
        select(models.Opportunity.id)
        .where(
            models.Opportunity.category.in_(EXPIRING_CATEGORIES),
            models.Opportunity.deadline.is_not(None),
            models.Opportunity.deadline < cutoff,
        )
        .order_by(models.Opportunity.id)
    )
    detected_closed = (
        select(models.Opportunity.id)
        .where(
            models.Opportunity.closed_at.is_not(None),
            models.Opportunity.closed_at < cutoff,
        )
        .order_by(models.Opportunity.id)
    )
    legacy_expired = (
        select(models.Opportunity.id)
        .where(
            models.Opportunity.status == "expired",
            models.Opportunity.closed_at.is_(None),
            func.coalesce(models.Opportunity.updated_at, models.Opportunity.last_seen_at) < cutoff,
        )
        .order_by(models.Opportunity.id)
    )

    deleted_count = 0
    deleted_count += _delete_in_batches(
        session,
        deadline_expired,
        batch_size=batch_size,
        commit_each_batch=commit_each_batch,
    )
    deleted_count += _delete_in_batches(
        session,
        detected_closed,
        batch_size=batch_size,
        commit_each_batch=commit_each_batch,
    )
    deleted_count += _delete_in_batches(
        session,
        legacy_expired,
        batch_size=batch_size,
        commit_each_batch=commit_each_batch,
    )
    return deleted_count


def _delete_in_batches(
    session: Session,
    opportunity_id_query,
    *,
    batch_size: int,
    commit_each_batch: bool,
) -> int:
    deleted_count = 0

    while True:
        opportunity_ids = list(session.scalars(opportunity_id_query.limit(batch_size)).all())
        if not opportunity_ids:
            break

        deleted_count += _delete_opportunity_batch(session, opportunity_ids)

        if commit_each_batch:
            session.commit()

    return deleted_count


def _delete_opportunity_batch(session: Session, opportunity_ids: list[int]) -> int:
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
    return int(result.rowcount or 0)


def main() -> None:
    engine = make_engine()
    with Session(engine) as session:
        session.execute(text(f"SET statement_timeout = '{MAINTENANCE_STATEMENT_TIMEOUT}'"))
        deleted_count = cleanup_expired_competitions(session, commit_each_batch=True)

    print(f"closed/expired opportunities deleted: {deleted_count}", flush=True)


if __name__ == "__main__":
    main()
