"""Offline regression tests for monthly-to-annual subscription switches."""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import api.payments as payments_module
from api.auth import get_current_user
from api.deps import get_db
from api.main import app
from api.payments import _switch_to_annual_charge_paise
from core import models
from core.config import get_settings


class _FakeOrder:
    def __init__(self, parent: "FakeRazorpayClient") -> None:
        self._parent = parent

    def create(self, payload: dict[str, Any]) -> dict[str, str]:
        self._parent.order_calls.append(payload)
        return {"id": f"order_switch_{uuid.uuid4().hex}"}


class _FakeUtility:
    def __init__(self, parent: "FakeRazorpayClient") -> None:
        self._parent = parent

    def verify_payment_signature(self, payload: dict[str, str]) -> None:
        self._parent.verify_calls.append(payload)
        if payload["razorpay_signature"] == "invalid":
            raise payments_module.razorpay.errors.SignatureVerificationError("invalid signature")


class _FakeSubscription:
    def __init__(self, parent: "FakeRazorpayClient") -> None:
        self._parent = parent

    def cancel(self, subscription_id: str | None, payload: dict[str, Any]) -> None:
        self._parent.cancel_calls.append((subscription_id, payload))
        if self._parent.raise_on_cancel:
            raise RuntimeError("simulated Razorpay subscription cancellation failure")


class FakeRazorpayClient:
    def __init__(self) -> None:
        self.order_calls: list[dict[str, Any]] = []
        self.verify_calls: list[dict[str, str]] = []
        self.cancel_calls: list[tuple[str | None, dict[str, Any]]] = []
        self.raise_on_cancel = False
        self.order = _FakeOrder(self)
        self.utility = _FakeUtility(self)
        self.subscription = _FakeSubscription(self)


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
def user(db_session: Session) -> models.User:
    account_user = models.User(email=f"switch-to-annual-{uuid.uuid4()}@example.com")
    db_session.add(account_user)
    db_session.flush()
    return account_user


@pytest.fixture
def client(db_session: Session, user: models.User, monkeypatch: pytest.MonkeyPatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "razorpay_key_id", "rzp_test_annual_switch")
    monkeypatch.setattr(settings, "razorpay_key_secret", "test-annual-switch-secret")

    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def razorpay_client(monkeypatch: pytest.MonkeyPatch) -> FakeRazorpayClient:
    fake_client = FakeRazorpayClient()
    monkeypatch.setattr(payments_module, "_razorpay_client", lambda: fake_client)
    return fake_client


def _create_plan(
    db_session: Session,
    *,
    price_paise: int,
    billing: str,
) -> models.Plan:
    plan = models.Plan(
        key=f"switch-to-annual-plan-{uuid.uuid4().hex}",
        price_paise=price_paise,
        billing=billing,
        features={},
        razorpay_plan_id=f"plan_switch_{uuid.uuid4().hex}",
    )
    db_session.add(plan)
    db_session.flush()
    return plan


def _create_active_subscription(
    db_session: Session,
    user: models.User,
    plan: models.Plan,
    *,
    current_period_end: datetime,
    cancel_at_period_end: bool = False,
) -> models.Subscription:
    subscription = models.Subscription(
        user_id=user.id,
        plan_id=plan.id,
        status="active",
        razorpay_sub_id=f"sub_switch_{uuid.uuid4().hex}",
        current_period_end=current_period_end,
        cancel_at_period_end=cancel_at_period_end,
    )
    db_session.add(subscription)
    db_session.flush()
    return subscription


def _create_pending_switch(
    db_session: Session,
    user: models.User,
    current_plan: models.Plan,
    target_plan: models.Plan,
) -> tuple[models.Subscription, models.SubscriptionUpgrade]:
    subscription = _create_active_subscription(
        db_session,
        user,
        current_plan,
        current_period_end=datetime.now(timezone.utc) + timedelta(days=20),
    )
    switch = models.SubscriptionUpgrade(
        user_id=user.id,
        subscription_id=subscription.id,
        from_plan_id=current_plan.id,
        to_plan_id=target_plan.id,
        amount_paise=37_300,
        kind="monthly_to_annual_switch",
        razorpay_order_id=f"order_switch_pending_{uuid.uuid4().hex}",
        status="pending",
    )
    db_session.add(switch)
    db_session.flush()
    return subscription, switch


def _verify_payload(switch: models.SubscriptionUpgrade, signature: str = "valid") -> dict[str, str]:
    return {
        "razorpay_order_id": str(switch.razorpay_order_id),
        "razorpay_payment_id": f"pay_switch_{uuid.uuid4().hex}",
        "razorpay_signature": signature,
    }


def _assert_prepaid_annual_period(
    current_period_end: datetime | None,
    started_at: datetime,
    finished_at: datetime,
) -> None:
    assert current_period_end is not None
    assert started_at + timedelta(days=365, seconds=-1) <= current_period_end
    assert current_period_end <= finished_at + timedelta(days=365, seconds=1)


def test_switch_to_annual_charge_credits_remaining_monthly_days() -> None:
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)

    assert _switch_to_annual_charge_paise(3_900, 39_900, now + timedelta(days=20), now) == 37_300


def test_switch_to_annual_charge_zero_remaining_is_full_annual() -> None:
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)

    assert _switch_to_annual_charge_paise(3_900, 39_900, now, now) == 39_900


def test_switch_to_annual_charge_clamps_clock_skew_credit_to_monthly_price() -> None:
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)

    assert _switch_to_annual_charge_paise(3_900, 39_900, now + timedelta(days=45), now) == 36_000


def test_annual_switch_creation_is_refused_by_plan_change_policy(
    client: TestClient,
    razorpay_client: FakeRazorpayClient,
) -> None:
    response = client.post("/payments/switch-to-annual/any-plan")

    assert response.status_code == 409
    assert response.json() == {
        "detail": (
            "Plan changes aren't supported while a subscription is active - Razorpay "
            "can't modify an active subscription. Cancel your current plan (you keep "
            "access until it ends), then subscribe to the plan you want."
        )
    }
    assert razorpay_client.order_calls == []


def test_switch_to_annual_verify_bad_signature_marks_failed_without_subscription_change(
    client: TestClient,
    db_session: Session,
    razorpay_client: FakeRazorpayClient,
    user: models.User,
) -> None:
    current_plan = _create_plan(db_session, price_paise=3_900, billing="monthly")
    target_plan = _create_plan(db_session, price_paise=39_900, billing="annual")
    subscription, switch = _create_pending_switch(db_session, user, current_plan, target_plan)
    original_razorpay_sub_id = subscription.razorpay_sub_id

    response = client.post(
        "/payments/switch-to-annual/verify",
        json=_verify_payload(switch, "invalid"),
    )

    assert response.status_code == 400
    db_session.refresh(subscription)
    db_session.refresh(switch)
    assert subscription.plan_id == current_plan.id
    assert subscription.razorpay_sub_id == original_razorpay_sub_id
    assert switch.status == "failed"
    assert len(razorpay_client.verify_calls) == 1
    assert razorpay_client.cancel_calls == []


def test_switch_to_annual_verify_applies_prepaid_annual_and_cancels_monthly(
    client: TestClient,
    db_session: Session,
    razorpay_client: FakeRazorpayClient,
    user: models.User,
) -> None:
    current_plan = _create_plan(db_session, price_paise=3_900, billing="monthly")
    target_plan = _create_plan(db_session, price_paise=39_900, billing="annual")
    subscription, switch = _create_pending_switch(db_session, user, current_plan, target_plan)
    old_razorpay_sub_id = subscription.razorpay_sub_id
    verification = _verify_payload(switch)
    started_at = datetime.now(timezone.utc)

    response = client.post("/payments/switch-to-annual/verify", json=verification)
    finished_at = datetime.now(timezone.utc)

    assert response.status_code == 200
    assert response.json() == {"status": "switched_to_annual", "amount_paise": 37_300}
    db_session.refresh(subscription)
    db_session.refresh(switch)
    assert subscription.plan_id == target_plan.id
    assert subscription.status == "active"
    assert subscription.cancel_at_period_end is False
    _assert_prepaid_annual_period(subscription.current_period_end, started_at, finished_at)
    assert subscription.razorpay_sub_id is None
    assert switch.razorpay_payment_id == verification["razorpay_payment_id"]
    assert switch.status == "applied"
    assert razorpay_client.cancel_calls == [(old_razorpay_sub_id, {"cancel_at_cycle_end": 0})]


def test_switch_to_annual_verify_cancel_failure_keeps_annual_and_alerts_founder(
    client: TestClient,
    db_session: Session,
    razorpay_client: FakeRazorpayClient,
    user: models.User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_plan = _create_plan(db_session, price_paise=3_900, billing="monthly")
    target_plan = _create_plan(db_session, price_paise=39_900, billing="annual")
    subscription, switch = _create_pending_switch(db_session, user, current_plan, target_plan)
    old_razorpay_sub_id = subscription.razorpay_sub_id
    razorpay_client.raise_on_cancel = True
    settings = get_settings()
    monkeypatch.setattr(settings, "waitlist_notify_email", "founder@example.com")
    sent_emails: list[dict[str, str]] = []

    def fake_send_email(to: str, subject: str, html: str, text: str) -> bool:
        sent_emails.append({"to": to, "subject": subject, "html": html, "text": text})
        return True

    monkeypatch.setattr(payments_module, "send_email", fake_send_email)
    started_at = datetime.now(timezone.utc)

    response = client.post("/payments/switch-to-annual/verify", json=_verify_payload(switch))
    finished_at = datetime.now(timezone.utc)

    assert response.status_code == 200
    db_session.refresh(subscription)
    db_session.refresh(switch)
    assert subscription.plan_id == target_plan.id
    _assert_prepaid_annual_period(subscription.current_period_end, started_at, finished_at)
    assert subscription.razorpay_sub_id == old_razorpay_sub_id
    assert switch.status == "applied_with_error"
    assert razorpay_client.cancel_calls == [(old_razorpay_sub_id, {"cancel_at_cycle_end": 0})]
    assert len(sent_emails) == 1
    assert sent_emails[0]["to"] == "founder@example.com"
    assert old_razorpay_sub_id in sent_emails[0]["text"]
    assert "paid for annual and has annual access" in sent_emails[0]["text"]
    assert "CANCELLED MANUALLY" in sent_emails[0]["text"]


def test_switch_to_annual_verify_is_idempotent(
    client: TestClient,
    db_session: Session,
    razorpay_client: FakeRazorpayClient,
    user: models.User,
) -> None:
    current_plan = _create_plan(db_session, price_paise=3_900, billing="monthly")
    target_plan = _create_plan(db_session, price_paise=39_900, billing="annual")
    subscription, switch = _create_pending_switch(db_session, user, current_plan, target_plan)
    first_verification = _verify_payload(switch)

    first = client.post("/payments/switch-to-annual/verify", json=first_verification)
    second = client.post(
        "/payments/switch-to-annual/verify",
        json=_verify_payload(switch, "invalid"),
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert len(razorpay_client.verify_calls) == 1
    assert len(razorpay_client.cancel_calls) == 1
    db_session.refresh(subscription)
    db_session.refresh(switch)
    assert subscription.plan_id == target_plan.id
    assert subscription.razorpay_sub_id is None
    assert switch.status == "applied"
