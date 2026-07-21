"""Offline regression tests for checkout's active-subscription guard."""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.auth import get_current_user
from api.deps import get_db
from api.main import app
from core import models
from core.config import get_settings


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
def user(db_session: Session):
    user = models.User(email=f"checkout-test-{uuid.uuid4()}@example.com")
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture
def client(db_session: Session, user: models.User):
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def paid_plan(db_session: Session):
    plan = models.Plan(
        key=f"checkout-test-plan-{uuid.uuid4()}",
        price_paise=3900,
        billing="monthly",
        features={},
        razorpay_plan_id=f"plan_test_{uuid.uuid4().hex}",
    )
    db_session.add(plan)
    db_session.flush()
    return plan


@pytest.fixture
def razorpay_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    class FakeSubscriptions:
        def create(self, payload: dict[str, Any]) -> dict[str, str]:
            calls.append(payload)
            return {"id": f"sub_checkout_{uuid.uuid4().hex}"}

    class FakeClient:
        subscription = FakeSubscriptions()

    monkeypatch.setattr("api.payments._razorpay_client", lambda: FakeClient())
    return calls


def test_checkout_allows_user_without_active_subscription(
    client: TestClient,
    db_session: Session,
    paid_plan: models.Plan,
    razorpay_calls: list[dict[str, Any]],
    user: models.User,
) -> None:
    response = client.post(f"/payments/checkout/{paid_plan.key}")

    assert response.status_code == 200
    assert len(razorpay_calls) == 1
    created = db_session.scalar(
        select(models.Subscription).where(models.Subscription.user_id == user.id)
    )
    assert created is not None
    assert created.status == "created"


def test_checkout_rejects_active_subscription_without_calling_razorpay(
    client: TestClient,
    db_session: Session,
    paid_plan: models.Plan,
    razorpay_calls: list[dict[str, Any]],
    user: models.User,
) -> None:
    db_session.add(
        models.Subscription(
            user_id=user.id,
            plan_id=paid_plan.id,
            status="active",
            razorpay_sub_id=f"sub_existing_{uuid.uuid4().hex}",
        )
    )
    db_session.flush()
    count_before = (
        db_session.query(models.Subscription).filter(models.Subscription.user_id == user.id).count()
    )

    response = client.post(f"/payments/checkout/{paid_plan.key}")

    assert response.status_code == 409
    assert response.json()["detail"] == ("Please cancel your current plan before switching plans.")
    assert razorpay_calls == []
    count_after = (
        db_session.query(models.Subscription).filter(models.Subscription.user_id == user.id).count()
    )
    assert count_after == count_before


def test_checkout_allows_subscription_expired_beyond_grace_with_razorpay_id(
    client: TestClient,
    db_session: Session,
    paid_plan: models.Plan,
    razorpay_calls: list[dict[str, Any]],
    user: models.User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "subscription_grace_days", 3)
    db_session.add(
        models.Subscription(
            user_id=user.id,
            plan_id=paid_plan.id,
            status="active",
            razorpay_sub_id=f"sub_expired_{uuid.uuid4().hex}",
            current_period_end=datetime.now(timezone.utc) - timedelta(days=10),
        )
    )
    db_session.flush()

    response = client.post(f"/payments/checkout/{paid_plan.key}")

    assert response.status_code == 200
    assert len(razorpay_calls) == 1


def test_checkout_rejects_scheduled_cancellation_and_includes_period_end(
    client: TestClient,
    db_session: Session,
    paid_plan: models.Plan,
    razorpay_calls: list[dict[str, Any]],
    user: models.User,
) -> None:
    period_end = datetime(2030, 6, 15, tzinfo=timezone.utc)
    db_session.add(
        models.Subscription(
            user_id=user.id,
            plan_id=paid_plan.id,
            status="active",
            razorpay_sub_id=f"sub_ending_{uuid.uuid4().hex}",
            cancel_at_period_end=True,
            current_period_end=period_end,
        )
    )
    db_session.flush()

    response = client.post(f"/payments/checkout/{paid_plan.key}")

    assert response.status_code == 409
    assert period_end.date().isoformat() in response.json()["detail"]
    assert razorpay_calls == []


def test_checkout_unknown_plan_still_returns_404(
    client: TestClient, razorpay_calls: list[dict[str, Any]]
) -> None:
    response = client.post(f"/payments/checkout/missing-{uuid.uuid4().hex}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Unknown plan"}
    assert razorpay_calls == []


def test_checkout_free_plan_still_returns_400(
    client: TestClient,
    db_session: Session,
    razorpay_calls: list[dict[str, Any]],
) -> None:
    free_plan = db_session.scalar(select(models.Plan).where(models.Plan.key == "free"))
    if free_plan is None:
        db_session.add(
            models.Plan(
                key="free",
                price_paise=0,
                billing=None,
                features={},
                razorpay_plan_id=None,
            )
        )
        db_session.flush()

    response = client.post("/payments/checkout/free")

    assert response.status_code == 400
    assert response.json() == {"detail": "The free plan has no checkout"}
    assert razorpay_calls == []


def test_checkout_unprovisioned_paid_plan_still_returns_503(
    client: TestClient,
    db_session: Session,
    razorpay_calls: list[dict[str, Any]],
) -> None:
    plan = models.Plan(
        key=f"unprovisioned-checkout-test-{uuid.uuid4()}",
        price_paise=3900,
        billing="monthly",
        features={},
        razorpay_plan_id=None,
    )
    db_session.add(plan)
    db_session.flush()

    response = client.post(f"/payments/checkout/{plan.key}")

    assert response.status_code == 503
    assert response.json() == {
        "detail": f"Plan '{plan.key}' has not been provisioned on Razorpay yet"
    }
    assert razorpay_calls == []
