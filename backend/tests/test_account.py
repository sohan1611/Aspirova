"""Integration tests for authenticated account endpoints."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

import api.account as account_module
from api.auth import get_current_user
from api.deps import get_db
from api.main import app
from core import models
from core.config import get_settings
from pipeline.notifications import wants


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
def free_plan(db_session: Session) -> models.Plan:
    plan = db_session.scalar(select(models.Plan).where(models.Plan.key == "free"))
    if plan is None:
        plan = models.Plan(
            key="free",
            price_paise=0,
            billing=None,
            features={},
        )
        db_session.add(plan)
        db_session.flush()
    return plan


@pytest.fixture
def user(db_session: Session, free_plan: models.Plan) -> models.User:
    account_user = models.User(email=f"account-test-{uuid.uuid4()}@example.com")
    db_session.add(account_user)
    db_session.flush()
    return account_user


@pytest.fixture
def client(db_session: Session, user: models.User):
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)


def test_get_account_me_returns_free_plan(client) -> None:
    response = client.get("/account/me")

    assert response.status_code == 200
    assert response.json()["plan"]["status"] == "free"
    assert response.json()["plan"]["key"] == "free"


def test_account_me_treats_subscription_expired_beyond_grace_as_free(
    client,
    db_session: Session,
    free_plan: models.Plan,
    user: models.User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "subscription_grace_days", 3)
    paid_plan = models.Plan(
        key=f"account-expired-{uuid.uuid4().hex}",
        price_paise=4900,
        billing="monthly",
        features={"copilot": True},
    )
    db_session.add(paid_plan)
    db_session.flush()
    db_session.add(
        models.Subscription(
            user_id=user.id,
            plan_id=paid_plan.id,
            status="active",
            razorpay_sub_id=f"sub_account_expired_{uuid.uuid4().hex}",
            current_period_end=datetime.now(timezone.utc) - timedelta(days=10),
        )
    )
    db_session.flush()

    response = client.get("/account/me")

    assert response.status_code == 200
    assert response.json()["plan"]["status"] == "free"
    assert response.json()["plan"]["key"] == free_plan.key


def test_patch_account_updates_profile_and_merges_preferences(
    client, db_session: Session, user: models.User
) -> None:
    first = client.patch(
        "/account/me",
        json={
            "display_name": "  Ada Lovelace  ",
            "college": "  University of London  ",
            "graduation_year": 2030,
            "notification_prefs": {"daily_digest": False},
        },
    )
    second = client.patch(
        "/account/me",
        json={"notification_prefs": {"weekly_report": False}},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    payload = second.json()
    assert payload["display_name"] == "Ada Lovelace"
    assert payload["college"] == "University of London"
    assert payload["graduation_year"] == 2030
    assert payload["notification_prefs"] == {
        "daily_digest": False,
        "weekly_report": False,
    }

    db_session.refresh(user)
    assert user.notification_prefs == payload["notification_prefs"]


def test_patch_account_rejects_invalid_graduation_year(client) -> None:
    response = client.patch("/account/me", json={"graduation_year": 1500})

    assert response.status_code == 422


def test_cancel_subscription_returns_404_without_active_subscription(client) -> None:
    response = client.post("/subscription/cancel")

    assert response.status_code == 404
    assert response.json()["detail"] == "No active subscription"


def test_cancel_subscription_schedules_remote_cancel_without_changing_local_status(
    client,
    db_session: Session,
    user: models.User,
    monkeypatch,
) -> None:
    paid_plan = models.Plan(
        key=f"account-paid-{uuid.uuid4()}",
        price_paise=4900,
        billing="monthly",
        features={},
    )
    db_session.add(paid_plan)
    db_session.flush()
    subscription = models.Subscription(
        user_id=user.id,
        plan_id=paid_plan.id,
        status="active",
        razorpay_sub_id=f"sub_account_{uuid.uuid4().hex[:12]}",
        current_period_end=datetime.now(timezone.utc) + timedelta(days=10),
    )
    db_session.add(subscription)
    db_session.flush()

    cancel_calls = []

    class StubSubscription:
        def cancel(self, subscription_id, options):
            cancel_calls.append((subscription_id, options))

    class StubClient:
        subscription = StubSubscription()

    monkeypatch.setattr(account_module, "_razorpay_client", lambda: StubClient())

    response = client.post("/subscription/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "cancel_scheduled"
    assert cancel_calls == [
        (subscription.razorpay_sub_id, {"cancel_at_cycle_end": 1}),
    ]
    db_session.refresh(subscription)
    assert subscription.status == "active"


def test_wants_defaults_on_and_only_respects_explicit_false() -> None:
    user = models.User(
        email="wants-test@example.com",
        notification_prefs={"daily_digest": False},
    )

    assert wants(user, "daily_digest") is False
    assert wants(user, "instant_alerts") is True

    user.notification_prefs = None
    assert wants(user, "daily_digest") is True
