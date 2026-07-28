"""Integration tests for positive-evidence opportunity expiry."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from core import models
from pipeline.expire import expire_missing_opportunities


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


def _seed_opportunity(
    db_session: Session,
    suffix: str,
    case: str,
    *,
    last_seen_at: datetime,
    last_crawled_at: datetime | None,
) -> models.Opportunity:
    adapter_key = f"expire-test-adapter-{suffix}"
    board_id = f"expire-test-board-{suffix}"
    source = models.Source(
        slug=f"expire-test-source-{case}-{suffix}",
        name=f"Expire test source {case}",
        adapter_key=adapter_key,
    )
    company = models.Company(
        slug=f"expire-test-company-{case}-{suffix}",
        name=f"Expire test company {case}",
        ats_type=adapter_key,
        ats_board_id=board_id,
    )
    db_session.add_all([source, company])
    db_session.flush()

    opportunity = models.Opportunity(
        slug=f"expire-test-opportunity-{case}-{suffix}",
        company_id=company.id,
        title=f"Expire test opportunity {case}",
        apply_url=f"https://example.com/expire/{case}/{suffix}",
        status="active",
        last_seen_at=last_seen_at,
    )
    db_session.add_all(
        [
            models.SourceState(
                source_id=source.id,
                page_key=board_id,
                last_crawled_at=last_crawled_at,
            ),
            opportunity,
        ]
    )
    db_session.flush()
    return opportunity


def _status_for_slug(db_session: Session, slug: str) -> str | None:
    db_session.expire_all()
    return db_session.scalar(
        select(models.Opportunity.status).where(models.Opportunity.slug == slug)
    )


def _status_and_closed_at_for_slug(
    db_session: Session, slug: str
) -> tuple[str, datetime | None] | None:
    db_session.expire_all()
    return db_session.execute(
        select(models.Opportunity.status, models.Opportunity.closed_at).where(
            models.Opportunity.slug == slug
        )
    ).one_or_none()


def test_expire_missing_opportunities_marks_listing_closed_absent_from_recent_crawl(
    db_session: Session,
) -> None:
    now = datetime.now(timezone.utc)
    opportunity = _seed_opportunity(
        db_session,
        str(uuid.uuid4()),
        "gone",
        last_seen_at=now - timedelta(hours=8),
        last_crawled_at=now - timedelta(hours=1),
    )

    expire_missing_opportunities(db_session)

    status_and_closed_at = _status_and_closed_at_for_slug(db_session, opportunity.slug)
    assert status_and_closed_at is not None
    status, closed_at = status_and_closed_at
    assert status == "active"
    assert closed_at is not None


def test_expire_missing_opportunities_does_not_reset_closed_at(
    db_session: Session,
) -> None:
    now = datetime.now(timezone.utc)
    original_closed_at = now - timedelta(days=3)
    opportunity = _seed_opportunity(
        db_session,
        str(uuid.uuid4()),
        "already-closed",
        last_seen_at=now - timedelta(hours=8),
        last_crawled_at=now - timedelta(hours=1),
    )
    opportunity.closed_at = original_closed_at
    db_session.flush()

    expire_missing_opportunities(db_session)

    status_and_closed_at = _status_and_closed_at_for_slug(db_session, opportunity.slug)
    assert status_and_closed_at == ("active", original_closed_at)


def test_expire_missing_opportunities_keeps_listing_seen_after_crawl(
    db_session: Session,
) -> None:
    now = datetime.now(timezone.utc)
    opportunity = _seed_opportunity(
        db_session,
        str(uuid.uuid4()),
        "present",
        last_seen_at=now - timedelta(minutes=30),
        last_crawled_at=now - timedelta(hours=1),
    )

    expire_missing_opportunities(db_session)

    assert _status_for_slug(db_session, opportunity.slug) == "active"


def test_expire_missing_opportunities_keeps_listings_when_crawl_is_stale(
    db_session: Session,
) -> None:
    now = datetime.now(timezone.utc)
    opportunity = _seed_opportunity(
        db_session,
        str(uuid.uuid4()),
        "stale",
        last_seen_at=now - timedelta(days=6),
        last_crawled_at=now - timedelta(days=5),
    )

    expire_missing_opportunities(db_session)

    assert _status_for_slug(db_session, opportunity.slug) == "active"


def test_expire_missing_opportunities_keeps_listings_when_board_was_never_crawled(
    db_session: Session,
) -> None:
    opportunity = _seed_opportunity(
        db_session,
        str(uuid.uuid4()),
        "never-crawled",
        last_seen_at=datetime.now(timezone.utc) - timedelta(days=6),
        last_crawled_at=None,
    )

    expire_missing_opportunities(db_session)

    assert _status_for_slug(db_session, opportunity.slug) == "active"
