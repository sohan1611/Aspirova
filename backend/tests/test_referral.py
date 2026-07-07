"""Integration tests for the referral invite loop and comp Pro Lite reward."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.auth import get_current_user
from api.deps import get_db
from api.main import app
from core import models
from core.gating import can
from core.referral import (
    INVITE_CODE_ALPHABET,
    INVITE_CODE_LENGTH,
    ReferralResult,
    get_or_create_invite_code,
    record_referral,
)

FREE_FEATURES = {"instant_alerts": False, "copilot": False}
PRO_LITE_FEATURES = {"instant_alerts": True, "copilot": False}


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


def _ensure_plan(
    db: Session,
    *,
    key: str,
    price_paise: int,
    billing: str | None,
    features: dict,
) -> models.Plan:
    plan = db.scalar(select(models.Plan).where(models.Plan.key == key))
    if plan is None:
        plan = models.Plan(
            key=key,
            price_paise=price_paise,
            billing=billing,
            features=features,
        )
        db.add(plan)
    else:
        plan.price_paise = price_paise
        plan.billing = billing
        plan.features = features
    db.flush()
    return plan


def _ensure_referral_plans(db: Session) -> dict[str, models.Plan]:
    return {
        "free": _ensure_plan(
            db,
            key="free",
            price_paise=0,
            billing=None,
            features=FREE_FEATURES,
        ),
        "pro_lite": _ensure_plan(
            db,
            key="pro_lite_monthly",
            price_paise=3900,
            billing="monthly",
            features=PRO_LITE_FEATURES,
        ),
    }


@pytest.fixture
def seeded(db_session: Session):
    plans = _ensure_referral_plans(db_session)
    suffix = uuid.uuid4()
    referrer = models.User(email=f"referral-referrer-{suffix}@example.com")
    referred = models.User(email=f"referral-referred-{suffix}@example.com")
    other = models.User(email=f"referral-other-{suffix}@example.com")
    db_session.add_all([referrer, referred, other])
    db_session.flush()
    return {"plans": plans, "referrer": referrer, "referred": referred, "other": other}


@pytest.fixture
def client(db_session: Session, seeded):
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: seeded["referrer"]
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)


def _comp_subscriptions(db: Session, user: models.User) -> list[models.Subscription]:
    return list(
        db.scalars(
            select(models.Subscription)
            .join(models.Plan, models.Plan.id == models.Subscription.plan_id)
            .where(
                models.Subscription.user_id == user.id,
                models.Subscription.razorpay_sub_id.is_(None),
                models.Plan.key == "pro_lite_monthly",
            )
        ).all()
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def test_invite_code_is_unique_and_stable(db_session: Session, seeded) -> None:
    first = get_or_create_invite_code(db_session, seeded["referrer"])
    second = get_or_create_invite_code(db_session, seeded["referrer"])
    other = get_or_create_invite_code(db_session, seeded["other"])

    assert first == second
    assert first != other
    assert len(first) == INVITE_CODE_LENGTH
    assert set(first) <= set(INVITE_CODE_ALPHABET)


def test_referral_me_lazily_creates_code_without_invite_url(client) -> None:
    response = client.get("/referral/me")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["invite_code"]) == INVITE_CODE_LENGTH
    assert "invite_url" not in payload
    assert payload["referral_count"] == 0
    assert payload["reward_active_until"] is None


def test_referral_claim_endpoint_returns_ok_for_valid_code(
    client, db_session: Session, seeded
) -> None:
    code = get_or_create_invite_code(db_session, seeded["referrer"])
    app.dependency_overrides[get_current_user] = lambda: seeded["referred"]

    response = client.post("/referral/claim", json={"code": code.lower()})

    assert response.status_code == 200
    assert response.json() == {"referred": True, "reason": "ok"}


def test_first_claim_sets_referrer_and_grants_one_pro_lite_comp_sub(
    db_session: Session, seeded
) -> None:
    started_at = datetime.now(timezone.utc)
    code = get_or_create_invite_code(db_session, seeded["referrer"])

    result = record_referral(db_session, seeded["referred"], code)

    db_session.refresh(seeded["referred"])
    assert result == ReferralResult(referred=True, reason="ok")
    assert seeded["referred"].referred_by == seeded["referrer"].id

    subscriptions = _comp_subscriptions(db_session, seeded["referrer"])
    assert len(subscriptions) == 1
    subscription = subscriptions[0]
    assert subscription.status == "active"
    assert subscription.razorpay_sub_id is None
    assert subscription.current_period_end is not None
    reward_delta = _as_utc(subscription.current_period_end) - started_at
    assert timedelta(days=29, minutes=59) <= reward_delta <= timedelta(days=30, minutes=1)

    assert can(db_session, seeded["referrer"], "instant_alerts") is True
    assert can(db_session, seeded["referrer"], "copilot") is False


def test_claim_is_idempotent_after_user_has_a_referrer(db_session: Session, seeded) -> None:
    first_code = get_or_create_invite_code(db_session, seeded["referrer"])
    other_code = get_or_create_invite_code(db_session, seeded["other"])

    first = record_referral(db_session, seeded["referred"], first_code)
    second = record_referral(db_session, seeded["referred"], other_code)

    db_session.refresh(seeded["referred"])
    assert first == ReferralResult(referred=True, reason="ok")
    assert second == ReferralResult(referred=False, reason="already_referred")
    assert seeded["referred"].referred_by == seeded["referrer"].id
    assert len(_comp_subscriptions(db_session, seeded["referrer"])) == 1
    assert len(_comp_subscriptions(db_session, seeded["other"])) == 0


def test_self_referral_and_unknown_code_are_noops(db_session: Session, seeded) -> None:
    code = get_or_create_invite_code(db_session, seeded["referrer"])

    self_referral = record_referral(db_session, seeded["referrer"], code)
    unknown = record_referral(db_session, seeded["other"], "UNKNOWN2")

    db_session.refresh(seeded["referrer"])
    db_session.refresh(seeded["other"])
    assert self_referral == ReferralResult(referred=False, reason="self_referral")
    assert unknown == ReferralResult(referred=False, reason="unknown_code")
    assert seeded["referrer"].referred_by is None
    assert seeded["other"].referred_by is None
    assert len(_comp_subscriptions(db_session, seeded["referrer"])) == 0
    assert len(_comp_subscriptions(db_session, seeded["other"])) == 0


def test_referral_commits_do_not_leak_users_or_subscriptions_past_outer_rollback(
    engine,
) -> None:
    suffix = uuid.uuid4()
    emails = [
        f"referral-leak-referrer-{suffix}@example.com",
        f"referral-leak-referred-{suffix}@example.com",
    ]
    user_ids = []

    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    try:
        _ensure_referral_plans(session)
        referrer = models.User(email=emails[0])
        referred = models.User(email=emails[1])
        session.add_all([referrer, referred])
        session.flush()
        user_ids = [referrer.id, referred.id]

        code = get_or_create_invite_code(session, referrer)
        result = record_referral(session, referred, code)
        assert result == ReferralResult(referred=True, reason="ok")
    finally:
        session.close()
        transaction.rollback()
        connection.close()

    with Session(engine) as verification:
        leaked_users = verification.scalar(
            select(func.count()).select_from(models.User).where(models.User.email.in_(emails))
        )
        leaked_subscriptions = verification.scalar(
            select(func.count())
            .select_from(models.Subscription)
            .where(models.Subscription.user_id.in_(user_ids))
        )

    assert leaked_users == 0
    assert leaked_subscriptions == 0
