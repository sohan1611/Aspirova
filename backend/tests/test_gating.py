"""Integration tests for core/gating.py's can() (Doc 08 sec 1 hard rule:
plan gating goes through can(), never a scattered if plan == check).
Every test runs inside a transaction that is rolled back at the end (Doc
08: tests must not pollute shared state) - correct whether or not
scripts/seed_plans.py has already been run against the target DB (see the
`plans` fixture below).
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from core import models
from core.gating import can, get_features


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


@pytest.fixture
def plans(db_session: Session):
    # core/gating.py hardcodes the free-tier lookup to key == "free" (there
    # is, by design, exactly one such row in any real environment once
    # scripts/seed_plans.py has run) - reuse it rather than insert a second
    # one, which would violate plans.key's unique constraint the moment
    # this test runs against a DB that already has the real seed applied.
    # Its features are overwritten for this test only, inside the
    # rollback-wrapped transaction, never persisted (Doc 08: tests must not
    # pollute shared state).
    free = db_session.scalar(select(models.Plan).where(models.Plan.key == "free"))
    if free is None:
        free = models.Plan(key="free", price_paise=0, billing=None, features={})
        db_session.add(free)
        db_session.flush()
    free.features = {"dream_companies_limit": 1, "instant_alerts": False, "copilot": False}

    pro_lite = models.Plan(
        key=f"pro-lite-gating-test-{uuid.uuid4()}",
        price_paise=3900,
        billing="monthly",
        features={"dream_companies_limit": 5, "instant_alerts": True, "copilot": False},
    )
    pro = models.Plan(
        key=f"pro-gating-test-{uuid.uuid4()}",
        price_paise=4900,
        billing="monthly",
        features={"dream_companies_limit": None, "instant_alerts": True, "copilot": True},
    )
    db_session.add_all([pro_lite, pro])
    db_session.flush()
    return {"free": free, "pro_lite": pro_lite, "pro": pro}


@pytest.fixture
def user(db_session: Session):
    u = models.User(email=f"gating-test-{uuid.uuid4()}@example.com")
    db_session.add(u)
    db_session.flush()
    return u


def test_unauthenticated_user_resolves_to_free_features(db_session, plans) -> None:
    assert can(db_session, None, "dream_companies_limit") == 1
    assert can(db_session, None, "instant_alerts") is False


def test_authenticated_user_with_no_subscription_resolves_to_free(db_session, plans, user) -> None:
    assert can(db_session, user, "dream_companies_limit") == 1
    assert can(db_session, user, "copilot") is False


def test_active_subscription_grants_that_plans_features(db_session, plans, user) -> None:
    db_session.add(
        models.Subscription(user_id=user.id, plan_id=plans["pro_lite"].id, status="active")
    )
    db_session.flush()

    assert can(db_session, user, "dream_companies_limit") == 5
    assert can(db_session, user, "instant_alerts") is True
    assert can(db_session, user, "copilot") is False


def test_pro_dream_companies_limit_is_none_meaning_unlimited(db_session, plans, user) -> None:
    db_session.add(models.Subscription(user_id=user.id, plan_id=plans["pro"].id, status="active"))
    db_session.flush()

    assert can(db_session, user, "dream_companies_limit") is None
    assert can(db_session, user, "copilot") is True


@pytest.mark.parametrize("bad_status", ["past_due", "canceled"])
def test_lapsed_subscription_does_not_grant_paid_features(
    db_session, plans, user, bad_status
) -> None:
    db_session.add(models.Subscription(user_id=user.id, plan_id=plans["pro"].id, status=bad_status))
    db_session.flush()

    assert can(db_session, user, "dream_companies_limit") == 1  # falls back to free
    assert can(db_session, user, "copilot") is False


def test_trialing_subscription_grants_paid_features(db_session, plans, user) -> None:
    db_session.add(models.Subscription(user_id=user.id, plan_id=plans["pro"].id, status="trialing"))
    db_session.flush()

    assert can(db_session, user, "copilot") is True


def test_most_recent_subscription_wins_when_multiple_exist(db_session, plans, user) -> None:
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    db_session.add(
        models.Subscription(
            user_id=user.id,
            plan_id=plans["pro_lite"].id,
            status="active",
            created_at=now - timedelta(minutes=10),
        )
    )
    db_session.add(
        models.Subscription(
            user_id=user.id, plan_id=plans["pro"].id, status="active", created_at=now
        )
    )
    db_session.flush()

    assert can(db_session, user, "copilot") is True  # the newer (pro) subscription


def test_missing_feature_key_resolves_to_false_not_keyerror(db_session, plans, user) -> None:
    assert can(db_session, user, "some_feature_no_plan_has") is False


def test_get_features_returns_the_full_dict(db_session, plans, user) -> None:
    features = get_features(db_session, None)
    assert features == plans["free"].features
