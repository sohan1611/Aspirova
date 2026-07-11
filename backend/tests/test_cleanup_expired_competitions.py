"""Integration coverage for the expired-competition cleanup script."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core import models
from scripts.cleanup_expired_competitions import cleanup_expired_competitions


@pytest.fixture
def db_session(engine):
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def _opportunity(
    db_session: Session,
    *,
    suffix: str,
    name: str,
    category: str,
    deadline: datetime | None,
) -> models.Opportunity:
    opportunity = models.Opportunity(
        slug=f"cleanup-competition-{name}-{suffix}",
        title=f"Cleanup competition {name}",
        category=category,
        deadline=deadline,
        apply_url=f"https://example.com/{name}/{suffix}",
    )
    db_session.add(opportunity)
    db_session.flush()
    return opportunity


def _count_for_opportunity(
    db_session: Session,
    model: type[models.OpportunitySource] | type[models.OpportunityTag] | type[models.Bookmark],
    opportunity_id: int,
) -> int:
    return db_session.scalar(
        select(func.count()).select_from(model).where(model.opportunity_id == opportunity_id)
    )


def test_cleanup_deletes_only_competitions_beyond_grace_window_and_handles_fks(
    db_session: Session,
) -> None:
    now = datetime.now(timezone.utc)
    suffix = str(uuid.uuid4())
    source = models.Source(slug=f"cleanup-source-{suffix}", name="Cleanup source")
    tag = models.Tag(slug=f"cleanup-tag-{suffix}", label="Cleanup tag")
    user = models.User(email=f"cleanup-{suffix}@example.com")
    db_session.add_all([source, tag, user])
    db_session.flush()

    expired_competition = _opportunity(
        db_session,
        suffix=suffix,
        name="expired-competition",
        category="competition",
        deadline=now - timedelta(days=20),
    )
    expired_hackathon = _opportunity(
        db_session,
        suffix=suffix,
        name="expired-hackathon",
        category="hackathon",
        deadline=now - timedelta(days=15),
    )
    recent_closed = _opportunity(
        db_session,
        suffix=suffix,
        name="recent-closed",
        category="competition",
        deadline=now - timedelta(days=3),
    )
    grace_boundary = _opportunity(
        db_session,
        suffix=suffix,
        name="grace-boundary",
        category="competition",
        deadline=now - timedelta(days=14),
    )
    future_competition = _opportunity(
        db_session,
        suffix=suffix,
        name="future",
        category="hackathon",
        deadline=now + timedelta(days=3),
    )
    undated_competition = _opportunity(
        db_session,
        suffix=suffix,
        name="undated",
        category="competition",
        deadline=None,
    )
    expired_role = _opportunity(
        db_session,
        suffix=suffix,
        name="expired-role",
        category="internship",
        deadline=now - timedelta(days=30),
    )

    raw_listing = models.RawListing(
        source_id=source.id,
        external_id=f"cleanup-raw-{suffix}",
        opportunity_id=expired_competition.id,
    )
    notification = models.Notification(
        user_id=user.id,
        type="cleanup-test",
        opportunity_id=expired_competition.id,
        status="sent",
    )
    retained_raw_listing = models.RawListing(
        source_id=source.id,
        external_id=f"cleanup-retained-raw-{suffix}",
        opportunity_id=recent_closed.id,
    )
    retained_notification = models.Notification(
        user_id=user.id,
        type="cleanup-retained-test",
        opportunity_id=recent_closed.id,
        status="sent",
    )
    db_session.add_all([raw_listing, notification, retained_raw_listing, retained_notification])
    db_session.flush()
    db_session.add_all(
        [
            models.OpportunitySource(
                opportunity_id=expired_competition.id,
                source_id=source.id,
                source_url=f"https://example.com/source/{suffix}",
                raw_listing_id=raw_listing.id,
            ),
            models.OpportunityTag(
                opportunity_id=expired_competition.id,
                tag_id=tag.id,
            ),
            models.Bookmark(
                user_id=user.id,
                opportunity_id=expired_competition.id,
            ),
            models.OpportunitySource(
                opportunity_id=recent_closed.id,
                source_id=source.id,
                source_url=f"https://example.com/source/retained/{suffix}",
                raw_listing_id=retained_raw_listing.id,
            ),
            models.OpportunityTag(
                opportunity_id=recent_closed.id,
                tag_id=tag.id,
            ),
            models.Bookmark(
                user_id=user.id,
                opportunity_id=recent_closed.id,
            ),
        ]
    )
    db_session.flush()

    expired_competition_id = expired_competition.id
    expired_hackathon_id = expired_hackathon.id
    retained_ids = {
        recent_closed.id,
        grace_boundary.id,
        future_competition.id,
        undated_competition.id,
        expired_role.id,
    }
    raw_listing_id = raw_listing.id
    notification_id = notification.id
    retained_raw_listing_id = retained_raw_listing.id
    retained_notification_id = retained_notification.id
    recent_closed_id = recent_closed.id

    deleted_count = cleanup_expired_competitions(db_session, now=now, batch_size=1)
    db_session.expire_all()

    remaining_ids = set(
        db_session.scalars(
            select(models.Opportunity.id).where(
                models.Opportunity.id.in_(
                    retained_ids | {expired_competition_id, expired_hackathon_id}
                )
            )
        ).all()
    )
    assert deleted_count >= 2
    assert expired_competition_id not in remaining_ids
    assert expired_hackathon_id not in remaining_ids
    assert retained_ids <= remaining_ids
    assert _count_for_opportunity(db_session, models.OpportunitySource, expired_competition_id) == 0
    assert _count_for_opportunity(db_session, models.OpportunityTag, expired_competition_id) == 0
    assert _count_for_opportunity(db_session, models.Bookmark, expired_competition_id) == 0
    assert _count_for_opportunity(db_session, models.OpportunitySource, recent_closed_id) == 1
    assert _count_for_opportunity(db_session, models.OpportunityTag, recent_closed_id) == 1
    assert _count_for_opportunity(db_session, models.Bookmark, recent_closed_id) == 1
    assert (
        db_session.scalar(
            select(models.RawListing.opportunity_id).where(models.RawListing.id == raw_listing_id)
        )
        is None
    )
    assert (
        db_session.scalar(
            select(models.Notification.opportunity_id).where(
                models.Notification.id == notification_id
            )
        )
        is None
    )
    assert (
        db_session.scalar(
            select(models.RawListing.opportunity_id).where(
                models.RawListing.id == retained_raw_listing_id
            )
        )
        == recent_closed_id
    )
    assert (
        db_session.scalar(
            select(models.Notification.opportunity_id).where(
                models.Notification.id == retained_notification_id
            )
        )
        == recent_closed_id
    )

    assert cleanup_expired_competitions(db_session, now=now, batch_size=1) == 0
