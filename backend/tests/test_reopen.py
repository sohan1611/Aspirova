"""Integration tests for statistical and curated reopen estimates."""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.opportunity import get_opportunity
from core import models
from pipeline.reopen import reopen_estimate


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


def _company(db_session: Session, suffix: str, name: str = "Reopen Test Company") -> models.Company:
    company = models.Company(
        slug=f"reopen-test-company-{suffix}",
        name=name,
        name_normalized=name.casefold(),
    )
    db_session.add(company)
    db_session.flush()
    return company


def _opportunity(
    db_session: Session,
    company: models.Company,
    suffix: str,
    marker: str,
    *,
    title: str = "Recurring Engineering Internship",
    title_normalized: str = "recurring engineering internship",
    posted_at: datetime,
) -> models.Opportunity:
    opportunity = models.Opportunity(
        slug=f"reopen-test-{marker}-{suffix}",
        company=company,
        title=title,
        title_normalized=title_normalized,
        posted_at=posted_at,
        apply_url=f"https://example.com/{marker}",
    )
    db_session.add(opportunity)
    db_session.flush()
    return opportunity


def test_historical_estimate_uses_distinct_prior_years_and_writes_no_ai_usage(
    db_session: Session,
) -> None:
    suffix = str(uuid.uuid4())
    company = _company(db_session, suffix)
    _opportunity(
        db_session,
        company,
        suffix,
        "2024",
        posted_at=datetime(2024, 10, 8, tzinfo=timezone.utc),
    )
    _opportunity(
        db_session,
        company,
        suffix,
        "2025",
        posted_at=datetime(2025, 10, 14, tzinfo=timezone.utc),
    )
    current = _opportunity(
        db_session,
        company,
        suffix,
        "2026",
        posted_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )
    usage_before = db_session.scalar(select(func.count()).select_from(models.AiUsage))

    estimate = reopen_estimate(db_session, current)

    assert estimate is not None
    assert estimate.basis == "historical"
    assert estimate.window == "around October"
    assert estimate.note.startswith("Estimate based on 2 distinct prior postings")

    detail = get_opportunity(current.slug, db_session)
    assert detail.reopen_estimate is not None
    assert detail.reopen_estimate.basis == "historical"
    assert db_session.scalar(select(func.count()).select_from(models.AiUsage)) == usage_before


def test_lone_posting_has_no_estimate(db_session: Session) -> None:
    suffix = str(uuid.uuid4())
    company = _company(db_session, suffix)
    opportunity = _opportunity(
        db_session,
        company,
        suffix,
        "lone",
        posted_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )

    assert reopen_estimate(db_session, opportunity) is None


def test_curated_program_uses_seed_cycle(db_session: Session) -> None:
    suffix = str(uuid.uuid4())
    company = _company(db_session, suffix, name="Google")
    opportunity = _opportunity(
        db_session,
        company,
        suffix,
        "curated",
        title="Google STEP Internship",
        title_normalized="google step internship",
        posted_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )

    estimate = reopen_estimate(db_session, opportunity)

    assert estimate is not None
    assert estimate.basis == "curated"
    assert estimate.window == "October-November"
    assert estimate.note.startswith("Estimate based on the curated seed cycle")
