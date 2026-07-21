"""Regression tests for scheduled subscription cancellation."""

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
    account_user = models.User(email=f"subscription-cancel-test-{uuid.uuid4()}@example.com")
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


def _create_paid_subscription(
    db_session: Session,
    user: models.User,
    *,
    cancel_at_period_end: bool = False,
) -> models.Subscription:
    plan = models.Plan(
        key=f"subscription-cancel-plan-{uuid.uuid4()}",
        price_paise=4900,
        billing="monthly",
        features={},
    )
    db_session.add(plan)
    db_session.flush()
    subscription = models.Subscription(
        user_id=user.id,
        plan_id=plan.id,
        status="active",
        razorpay_sub_id=f"sub_cancel_{uuid.uuid4().hex[:12]}",
        current_period_end=datetime.now(timezone.utc) + timedelta(days=10),
        cancel_at_period_end=cancel_at_period_end,
    )
    db_session.add(subscription)
    db_session.flush()
    return subscription


def test_cancel_active_subscription_persists_scheduled_flag_and_calls_razorpay_once(
    client,
    db_session: Session,
    user: models.User,
    monkeypatch,
) -> None:
    subscription = _create_paid_subscription(db_session, user)
    cancel_calls: list[tuple[str, dict[str, int]]] = []

    class StubSubscription:
        def cancel(self, subscription_id: str, options: dict[str, int]) -> None:
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
    assert subscription.cancel_at_period_end is True


def test_cancel_already_scheduled_is_idempotent_without_second_razorpay_call(
    client,
    db_session: Session,
    user: models.User,
    monkeypatch,
) -> None:
    subscription = _create_paid_subscription(db_session, user)
    cancel_calls: list[tuple[str, dict[str, int]]] = []
    client_builds: list[str] = []

    class StubSubscription:
        def cancel(self, subscription_id: str, options: dict[str, int]) -> None:
            cancel_calls.append((subscription_id, options))

    class StubClient:
        subscription = StubSubscription()

    def fake_razorpay_client() -> StubClient:
        client_builds.append("built")
        return StubClient()

    monkeypatch.setattr(account_module, "_razorpay_client", fake_razorpay_client)

    first = client.post("/subscription/cancel")
    second = client.post("/subscription/cancel")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["status"] == "cancel_scheduled"
    assert cancel_calls == [
        (subscription.razorpay_sub_id, {"cancel_at_cycle_end": 1}),
    ]
    assert client_builds == ["built"]


def test_cancel_bad_request_does_not_persist_scheduled_flag(
    client,
    db_session: Session,
    user: models.User,
    monkeypatch,
) -> None:
    subscription = _create_paid_subscription(db_session, user)

    class StubSubscription:
        def cancel(self, subscription_id: str, options: dict[str, int]) -> None:
            raise account_module.razorpay.errors.BadRequestError("already cancelling")

    class StubClient:
        subscription = StubSubscription()

    monkeypatch.setattr(account_module, "_razorpay_client", lambda: StubClient())

    response = client.post("/subscription/cancel")

    assert response.status_code == 400
    db_session.refresh(subscription)
    assert subscription.cancel_at_period_end is False


def test_account_me_serializes_cancel_at_period_end(
    client,
    db_session: Session,
    user: models.User,
) -> None:
    free_response = client.get("/account/me")

    assert free_response.status_code == 200
    assert free_response.json()["plan"]["cancel_at_period_end"] is False

    _create_paid_subscription(db_session, user, cancel_at_period_end=True)

    scheduled_response = client.get("/account/me")

    assert scheduled_response.status_code == 200
    assert scheduled_response.json()["plan"]["cancel_at_period_end"] is True
