"""Offline regression tests for same-period prorated subscription upgrades."""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

import api.payments as payments_module
from api.auth import get_current_user
from api.deps import get_db
from api.main import app
from api.payments import _prorated_top_up_paise
from core import models
from core.config import get_settings


class _FakeOrder:
    def __init__(self, parent: "FakeRazorpayClient") -> None:
        self._parent = parent

    def create(self, payload: dict[str, Any]) -> dict[str, str]:
        self._parent.order_calls.append(payload)
        return {"id": f"order_upgrade_{uuid.uuid4().hex}"}


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

    def edit(self, subscription_id: str | None, payload: dict[str, Any]) -> None:
        self._parent.edit_calls.append((subscription_id, payload))
        if self._parent.raise_on_edit:
            raise RuntimeError("simulated Razorpay subscription edit failure")


class FakeRazorpayClient:
    def __init__(self) -> None:
        self.order_calls: list[dict[str, Any]] = []
        self.verify_calls: list[dict[str, str]] = []
        self.edit_calls: list[tuple[str | None, dict[str, Any]]] = []
        self.raise_on_edit = False
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
    account_user = models.User(email=f"subscription-upgrade-{uuid.uuid4()}@example.com")
    db_session.add(account_user)
    db_session.flush()
    return account_user


@pytest.fixture
def client(db_session: Session, user: models.User, monkeypatch: pytest.MonkeyPatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "razorpay_key_id", "rzp_test_subscription_upgrade")
    monkeypatch.setattr(settings, "razorpay_key_secret", "test-subscription-upgrade-secret")

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
        key=f"subscription-upgrade-plan-{uuid.uuid4().hex}",
        price_paise=price_paise,
        billing=billing,
        features={},
        razorpay_plan_id=f"plan_upgrade_{uuid.uuid4().hex}",
    )
    db_session.add(plan)
    db_session.flush()
    return plan


def _create_active_subscription(
    db_session: Session,
    user: models.User,
    plan: models.Plan,
    *,
    current_period_end: datetime | None,
    cancel_at_period_end: bool = False,
) -> models.Subscription:
    subscription = models.Subscription(
        user_id=user.id,
        plan_id=plan.id,
        status="active",
        razorpay_sub_id=f"sub_upgrade_{uuid.uuid4().hex}",
        current_period_end=current_period_end,
        cancel_at_period_end=cancel_at_period_end,
    )
    db_session.add(subscription)
    db_session.flush()
    return subscription


def _create_pending_upgrade(
    db_session: Session,
    user: models.User,
    current_plan: models.Plan,
    target_plan: models.Plan,
) -> tuple[models.Subscription, models.SubscriptionUpgrade]:
    subscription = _create_active_subscription(
        db_session,
        user,
        current_plan,
        current_period_end=datetime.now(timezone.utc) + timedelta(days=200),
    )
    upgrade = models.SubscriptionUpgrade(
        user_id=user.id,
        subscription_id=subscription.id,
        from_plan_id=current_plan.id,
        to_plan_id=target_plan.id,
        amount_paise=5_000,
        razorpay_order_id=f"order_pending_{uuid.uuid4().hex}",
        status="pending",
    )
    db_session.add(upgrade)
    db_session.flush()
    return subscription, upgrade


def _verify_payload(
    upgrade: models.SubscriptionUpgrade, signature: str = "valid"
) -> dict[str, str]:
    return {
        "razorpay_order_id": str(upgrade.razorpay_order_id),
        "razorpay_payment_id": f"pay_upgrade_{uuid.uuid4().hex}",
        "razorpay_signature": signature,
    }


def test_prorated_top_up_annual_nine_months_is_within_25_paise_of_7500() -> None:
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)

    amount = _prorated_top_up_paise(
        39_900,
        49_900,
        "annual",
        now + timedelta(days=273),
        now,
    )

    # The nominal 365-day formula returns 7,479 paise; the 25-paise tolerance
    # expresses the founder's approximately-Rs.75 nine-month example.
    assert abs(amount - 7_500) <= 25


def test_prorated_top_up_zero_remaining_is_zero() -> None:
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)

    assert _prorated_top_up_paise(39_900, 49_900, "annual", now, now) == 0


def test_prorated_top_up_clamps_clock_skew_to_full_difference() -> None:
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)

    assert (
        _prorated_top_up_paise(
            39_900,
            49_900,
            "annual",
            now + timedelta(days=500),
            now,
        )
        == 10_000
    )


def test_prorated_top_up_monthly_half_period_is_500() -> None:
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)

    assert (
        _prorated_top_up_paise(
            3_900,
            4_900,
            "monthly",
            now + timedelta(days=15),
            now,
        )
        == 500
    )


def test_upgrade_requires_active_subscription(
    client: TestClient,
    db_session: Session,
    razorpay_client: FakeRazorpayClient,
) -> None:
    target_plan = _create_plan(db_session, price_paise=49_900, billing="annual")

    response = client.post(f"/payments/upgrade/{target_plan.key}")

    assert response.status_code == 409
    assert response.json() == {"detail": "You do not have an active plan to upgrade."}
    assert razorpay_client.order_calls == []


def test_upgrade_rejects_cross_period_target(
    client: TestClient,
    db_session: Session,
    razorpay_client: FakeRazorpayClient,
    user: models.User,
) -> None:
    current_plan = _create_plan(db_session, price_paise=3_900, billing="monthly")
    target_plan = _create_plan(db_session, price_paise=49_900, billing="annual")
    _create_active_subscription(
        db_session,
        user,
        current_plan,
        current_period_end=datetime.now(timezone.utc) + timedelta(days=20),
    )

    response = client.post(f"/payments/upgrade/{target_plan.key}")

    assert response.status_code == 409
    assert "same-period upgrades" in response.json()["detail"]
    assert razorpay_client.order_calls == []


@pytest.mark.parametrize("target_price_paise", [39_900, 39_800])
def test_upgrade_rejects_equal_or_lower_price_target(
    client: TestClient,
    db_session: Session,
    razorpay_client: FakeRazorpayClient,
    target_price_paise: int,
    user: models.User,
) -> None:
    current_plan = _create_plan(db_session, price_paise=39_900, billing="annual")
    target_plan = _create_plan(db_session, price_paise=target_price_paise, billing="annual")
    _create_active_subscription(
        db_session,
        user,
        current_plan,
        current_period_end=datetime.now(timezone.utc) + timedelta(days=200),
    )

    response = client.post(f"/payments/upgrade/{target_plan.key}")

    assert response.status_code == 409
    assert "higher-priced" in response.json()["detail"]
    assert razorpay_client.order_calls == []


def test_upgrade_rejects_scheduled_cancellation(
    client: TestClient,
    db_session: Session,
    razorpay_client: FakeRazorpayClient,
    user: models.User,
) -> None:
    current_plan = _create_plan(db_session, price_paise=39_900, billing="annual")
    target_plan = _create_plan(db_session, price_paise=49_900, billing="annual")
    _create_active_subscription(
        db_session,
        user,
        current_plan,
        current_period_end=datetime.now(timezone.utc) + timedelta(days=200),
        cancel_at_period_end=True,
    )

    response = client.post(f"/payments/upgrade/{target_plan.key}")

    assert response.status_code == 409
    assert "scheduled to end" in response.json()["detail"]
    assert razorpay_client.order_calls == []


def test_upgrade_requires_current_period_end_for_proration(
    client: TestClient,
    db_session: Session,
    razorpay_client: FakeRazorpayClient,
    user: models.User,
) -> None:
    current_plan = _create_plan(db_session, price_paise=39_900, billing="annual")
    target_plan = _create_plan(db_session, price_paise=49_900, billing="annual")
    _create_active_subscription(
        db_session,
        user,
        current_plan,
        current_period_end=None,
    )

    response = client.post(f"/payments/upgrade/{target_plan.key}")

    assert response.status_code == 409
    assert "current period end" in response.json()["detail"]
    assert razorpay_client.order_calls == []


def test_upgrade_creates_order_and_pending_row_without_changing_subscription(
    client: TestClient,
    db_session: Session,
    razorpay_client: FakeRazorpayClient,
    user: models.User,
) -> None:
    current_plan = _create_plan(db_session, price_paise=39_900, billing="annual")
    target_plan = _create_plan(db_session, price_paise=49_900, billing="annual")
    subscription = _create_active_subscription(
        db_session,
        user,
        current_plan,
        current_period_end=datetime.now(timezone.utc) + timedelta(days=273),
    )

    response = client.post(f"/payments/upgrade/{target_plan.key}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "payment_required"
    assert len(razorpay_client.order_calls) == 1
    assert razorpay_client.order_calls[0] == {
        "amount": payload["amount_paise"],
        "currency": "INR",
        "notes": {
            "user_id": str(user.id),
            "from_plan": current_plan.key,
            "to_plan": target_plan.key,
            "subscription_id": str(subscription.id),
        },
    }

    db_session.refresh(subscription)
    assert subscription.plan_id == current_plan.id
    upgrade = db_session.scalar(
        select(models.SubscriptionUpgrade).where(
            models.SubscriptionUpgrade.razorpay_order_id == payload["razorpay_order_id"]
        )
    )
    assert upgrade is not None
    assert upgrade.status == "pending"
    assert upgrade.amount_paise == payload["amount_paise"]


def test_upgrade_waives_sub_rupee_top_up_without_order(
    client: TestClient,
    db_session: Session,
    razorpay_client: FakeRazorpayClient,
    user: models.User,
) -> None:
    current_plan = _create_plan(db_session, price_paise=39_900, billing="annual")
    target_plan = _create_plan(db_session, price_paise=39_950, billing="annual")
    subscription = _create_active_subscription(
        db_session,
        user,
        current_plan,
        current_period_end=datetime.now(timezone.utc) + timedelta(days=200),
    )

    response = client.post(f"/payments/upgrade/{target_plan.key}")

    assert response.status_code == 200
    assert response.json() == {"status": "upgraded", "amount_paise": 0, "waived": True}
    assert razorpay_client.order_calls == []
    db_session.refresh(subscription)
    assert subscription.plan_id == target_plan.id
    upgrade = db_session.scalar(
        select(models.SubscriptionUpgrade).where(
            models.SubscriptionUpgrade.subscription_id == subscription.id
        )
    )
    assert upgrade is not None
    assert upgrade.amount_paise == 0
    assert upgrade.razorpay_order_id is None
    assert upgrade.status == "applied"


def test_upgrade_verify_bad_signature_marks_failed_without_plan_change(
    client: TestClient,
    db_session: Session,
    razorpay_client: FakeRazorpayClient,
    user: models.User,
) -> None:
    current_plan = _create_plan(db_session, price_paise=39_900, billing="annual")
    target_plan = _create_plan(db_session, price_paise=49_900, billing="annual")
    subscription, upgrade = _create_pending_upgrade(db_session, user, current_plan, target_plan)

    response = client.post("/payments/upgrade/verify", json=_verify_payload(upgrade, "invalid"))

    assert response.status_code == 400
    db_session.refresh(subscription)
    db_session.refresh(upgrade)
    assert subscription.plan_id == current_plan.id
    assert upgrade.status == "failed"
    assert len(razorpay_client.verify_calls) == 1
    assert razorpay_client.edit_calls == []


def test_upgrade_verify_applies_locally_and_schedules_razorpay_cycle_end(
    client: TestClient,
    db_session: Session,
    razorpay_client: FakeRazorpayClient,
    user: models.User,
) -> None:
    current_plan = _create_plan(db_session, price_paise=39_900, billing="annual")
    target_plan = _create_plan(db_session, price_paise=49_900, billing="annual")
    subscription, upgrade = _create_pending_upgrade(db_session, user, current_plan, target_plan)
    verification = _verify_payload(upgrade)
    original_period_end = subscription.current_period_end

    response = client.post("/payments/upgrade/verify", json=verification)

    assert response.status_code == 200
    db_session.refresh(subscription)
    db_session.refresh(upgrade)
    assert subscription.plan_id == target_plan.id
    assert subscription.current_period_end == original_period_end
    assert upgrade.status == "applied"
    assert upgrade.razorpay_payment_id == verification["razorpay_payment_id"]
    assert razorpay_client.edit_calls == [
        (
            subscription.razorpay_sub_id,
            {
                "plan_id": target_plan.razorpay_plan_id,
                "schedule_change_at": "cycle_end",
            },
        )
    ]


def test_upgrade_verify_edit_failure_keeps_local_upgrade_and_marks_applied_with_error(
    client: TestClient,
    db_session: Session,
    razorpay_client: FakeRazorpayClient,
    user: models.User,
) -> None:
    current_plan = _create_plan(db_session, price_paise=39_900, billing="annual")
    target_plan = _create_plan(db_session, price_paise=49_900, billing="annual")
    subscription, upgrade = _create_pending_upgrade(db_session, user, current_plan, target_plan)
    razorpay_client.raise_on_edit = True

    response = client.post("/payments/upgrade/verify", json=_verify_payload(upgrade))

    assert response.status_code == 200
    db_session.refresh(subscription)
    db_session.refresh(upgrade)
    assert subscription.plan_id == target_plan.id
    assert upgrade.status == "applied_with_error"
    assert len(razorpay_client.edit_calls) == 1


def test_upgrade_verify_is_idempotent(
    client: TestClient,
    db_session: Session,
    razorpay_client: FakeRazorpayClient,
    user: models.User,
) -> None:
    current_plan = _create_plan(db_session, price_paise=39_900, billing="annual")
    target_plan = _create_plan(db_session, price_paise=49_900, billing="annual")
    subscription, upgrade = _create_pending_upgrade(db_session, user, current_plan, target_plan)

    first = client.post("/payments/upgrade/verify", json=_verify_payload(upgrade))
    second = client.post("/payments/upgrade/verify", json=_verify_payload(upgrade, "invalid"))

    assert first.status_code == 200
    assert second.status_code == 200
    assert len(razorpay_client.verify_calls) == 1
    assert len(razorpay_client.edit_calls) == 1
    db_session.refresh(subscription)
    db_session.refresh(upgrade)
    assert subscription.plan_id == target_plan.id
    assert upgrade.status == "applied"
