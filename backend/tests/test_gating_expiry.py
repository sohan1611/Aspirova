"""Regression coverage for paid-feature expiry and its webhook grace window."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from core import models
from core.config import get_settings
from core.gating import get_features


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


@pytest.fixture(autouse=True)
def subscription_grace_days(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "subscription_grace_days", 3)


@pytest.fixture
def plans(db_session: Session) -> dict[str, models.Plan]:
    free = db_session.scalar(select(models.Plan).where(models.Plan.key == "free"))
    if free is None:
        free = models.Plan(key="free", price_paise=0, billing=None, features={})
        db_session.add(free)
        db_session.flush()
    free.features = {"copilot": False, "resume_match": False}

    pro = models.Plan(
        key=f"pro-gating-expiry-{uuid.uuid4().hex}",
        price_paise=4900,
        billing="monthly",
        features={"copilot": True, "resume_match": True},
    )
    db_session.add(pro)
    db_session.flush()
    return {"free": free, "pro": pro}


@pytest.fixture
def user(db_session: Session) -> models.User:
    user = models.User(email=f"gating-expiry-{uuid.uuid4().hex}@example.com")
    db_session.add(user)
    db_session.flush()
    return user


def _add_subscription(
    db_session: Session,
    user: models.User,
    plan: models.Plan,
    *,
    current_period_end: datetime | None,
    razorpay_backed: bool,
    status: str = "active",
) -> None:
    db_session.add(
        models.Subscription(
            user_id=user.id,
            plan_id=plan.id,
            status=status,
            razorpay_sub_id=(f"sub_gating_expiry_{uuid.uuid4().hex}" if razorpay_backed else None),
            current_period_end=current_period_end,
        )
    )
    db_session.flush()


def _assert_paid_features(db_session: Session, user: models.User) -> None:
    features = get_features(db_session, user)
    assert features["copilot"] is True
    assert features["resume_match"] is True


@pytest.mark.parametrize("razorpay_backed", [False, True], ids=["manual", "razorpay"])
def test_active_subscription_with_future_period_grants_paid_features(
    db_session: Session,
    plans: dict[str, models.Plan],
    user: models.User,
    razorpay_backed: bool,
) -> None:
    _add_subscription(
        db_session,
        user,
        plans["pro"],
        current_period_end=datetime.now(timezone.utc) + timedelta(days=1),
        razorpay_backed=razorpay_backed,
    )

    _assert_paid_features(db_session, user)


@pytest.mark.parametrize("razorpay_backed", [False, True], ids=["manual", "razorpay"])
def test_active_subscription_without_period_end_grants_paid_features(
    db_session: Session,
    plans: dict[str, models.Plan],
    user: models.User,
    razorpay_backed: bool,
) -> None:
    _add_subscription(
        db_session,
        user,
        plans["pro"],
        current_period_end=None,
        razorpay_backed=razorpay_backed,
    )

    _assert_paid_features(db_session, user)


@pytest.mark.parametrize("razorpay_backed", [False, True], ids=["manual", "razorpay"])
def test_active_subscription_inside_grace_grants_paid_features(
    db_session: Session,
    plans: dict[str, models.Plan],
    user: models.User,
    razorpay_backed: bool,
) -> None:
    _add_subscription(
        db_session,
        user,
        plans["pro"],
        current_period_end=datetime.now(timezone.utc) - timedelta(days=1),
        razorpay_backed=razorpay_backed,
    )

    _assert_paid_features(db_session, user)


@pytest.mark.parametrize("razorpay_backed", [False, True], ids=["manual", "razorpay"])
def test_active_subscription_beyond_grace_resolves_to_free_even_with_razorpay_id(
    db_session: Session,
    plans: dict[str, models.Plan],
    user: models.User,
    razorpay_backed: bool,
) -> None:
    _add_subscription(
        db_session,
        user,
        plans["pro"],
        current_period_end=datetime.now(timezone.utc) - timedelta(days=10),
        razorpay_backed=razorpay_backed,
    )

    assert get_features(db_session, user) == plans["free"].features


@pytest.mark.parametrize("status", ["past_due", "canceled"])
@pytest.mark.parametrize("period_end_offset", [None, -10, 1], ids=["none", "past", "future"])
def test_past_due_or_canceled_subscription_resolves_to_free_regardless_of_period(
    db_session: Session,
    plans: dict[str, models.Plan],
    user: models.User,
    status: str,
    period_end_offset: int | None,
) -> None:
    current_period_end = (
        None
        if period_end_offset is None
        else datetime.now(timezone.utc) + timedelta(days=period_end_offset)
    )
    _add_subscription(
        db_session,
        user,
        plans["pro"],
        current_period_end=current_period_end,
        razorpay_backed=True,
        status=status,
    )

    assert get_features(db_session, user) == plans["free"].features
