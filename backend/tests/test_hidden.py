"""Integration tests for deterministic, set-based hidden classification."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.schemas import OpportunityListItem
from core import models
from pipeline.hidden import recompute_hidden


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


def _opportunity(db_session: Session, suffix: str, name: str) -> models.Opportunity:
    opportunity = models.Opportunity(
        slug=f"hidden-test-{name}-{suffix}",
        title=f"Hidden test {name}",
        apply_url=f"https://example.com/{name}",
    )
    db_session.add(opportunity)
    db_session.flush()
    return opportunity


def test_recompute_hidden_classifies_by_source_scarcity_and_tier(
    db_session: Session,
) -> None:
    suffix = str(uuid.uuid4())
    tier_one = models.Source(
        slug=f"hidden-test-tier-one-{suffix}",
        name="Mainstream source",
        crawl_tier=1,
    )
    tier_three = models.Source(
        slug=f"hidden-test-tier-three-{suffix}",
        name="Niche source",
        crawl_tier=3,
    )
    db_session.add_all([tier_one, tier_three])
    db_session.flush()

    hidden = _opportunity(db_session, suffix, "hidden")
    cross_posted = _opportunity(db_session, suffix, "cross-posted")
    mainstream = _opportunity(db_session, suffix, "mainstream")
    cross_posted.is_hidden = True
    mainstream.is_hidden = True
    db_session.add_all(
        [
            models.OpportunitySource(
                opportunity_id=hidden.id,
                source_id=tier_three.id,
                source_url=f"https://niche.example/{suffix}/hidden",
            ),
            models.OpportunitySource(
                opportunity_id=cross_posted.id,
                source_id=tier_three.id,
                source_url=f"https://niche.example/{suffix}/cross-posted",
            ),
            models.OpportunitySource(
                opportunity_id=cross_posted.id,
                source_id=tier_one.id,
                source_url=f"https://mainstream.example/{suffix}/cross-posted",
            ),
            models.OpportunitySource(
                opportunity_id=mainstream.id,
                source_id=tier_one.id,
                source_url=f"https://mainstream.example/{suffix}/mainstream",
            ),
        ]
    )
    db_session.flush()

    first_count = recompute_hidden(db_session)
    db_session.expire_all()

    flags = dict(
        db_session.execute(
            select(models.Opportunity.slug, models.Opportunity.is_hidden).where(
                models.Opportunity.id.in_([hidden.id, cross_posted.id, mainstream.id])
            )
        ).all()
    )
    assert flags[hidden.slug] is True
    assert flags[cross_posted.slug] is False
    assert flags[mainstream.slug] is False

    hidden_model = db_session.scalar(
        select(models.Opportunity).where(models.Opportunity.id == hidden.id)
    )
    assert OpportunityListItem.from_model(hidden_model).is_hidden is True

    second_count = recompute_hidden(db_session)
    assert second_count == first_count
    db_session.expire_all()
    flags_after_second_run = dict(
        db_session.execute(
            select(models.Opportunity.slug, models.Opportunity.is_hidden).where(
                models.Opportunity.id.in_([hidden.id, cross_posted.id, mainstream.id])
            )
        ).all()
    )
    assert flags_after_second_run == flags
