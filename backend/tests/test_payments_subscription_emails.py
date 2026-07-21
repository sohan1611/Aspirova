"""DB-free regression tests for Razorpay subscription-status email delivery."""

import hashlib
import hmac
import json
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

import api.payments as payments_module
from api.deps import get_db
from api.main import app
from core import models
from core.config import get_settings

TEST_WEBHOOK_SECRET = "test-webhook-secret-not-real"


@pytest.fixture(scope="session", autouse=True)
def _purge_isolation_test_residue():
    """Override the repository-wide DB cleanup fixture for this DB-free module."""

    yield


class FakeSession:
    """In-memory subset of Session used by the webhook and email notification path."""

    def __init__(self) -> None:
        self.subscription = SimpleNamespace(
            id=101,
            user_id=UUID("00000000-0000-0000-0000-000000000101"),
            plan_id=11,
            status="created",
            razorpay_sub_id="sub_subscription_email_test",
            current_period_end=None,
        )
        self.user = SimpleNamespace(
            id=self.subscription.user_id,
            email="subscription-email-test@example.com",
        )
        self.plan = SimpleNamespace(id=self.subscription.plan_id, key="pro_lite_monthly")
        self.added: list[models.Notification] = []
        self.commit_statuses: list[str] = []
        self.rollbacks = 0

    def scalar(self, statement):
        entity = statement.column_descriptions[0]["entity"]
        if entity is models.Subscription:
            return self.subscription
        if entity is models.User:
            return self.user
        if entity is models.Plan:
            return self.plan
        raise AssertionError(f"Unexpected scalar query for {entity}")

    def add(self, instance) -> None:
        self.added.append(instance)

    def commit(self) -> None:
        self.commit_statuses.append(self.subscription.status)

    def rollback(self) -> None:
        self.rollbacks += 1


@pytest.fixture
def fake_db() -> FakeSession:
    return FakeSession()


@pytest.fixture
def client(fake_db: FakeSession, monkeypatch) -> TestClient:
    settings = get_settings()
    monkeypatch.setattr(settings, "razorpay_webhook_secret", TEST_WEBHOOK_SECRET)
    monkeypatch.setattr(settings, "razorpay_key_id", "rzp_test_placeholder")
    monkeypatch.setattr(settings, "razorpay_key_secret", "placeholder_secret")
    monkeypatch.setattr(settings, "site_url", "https://aspirova.test")

    app.dependency_overrides[get_db] = lambda: fake_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def sent_emails(monkeypatch) -> list[dict[str, str]]:
    calls: list[dict[str, str]] = []

    def _fake_send(to: str, subject: str, html: str, text: str) -> bool:
        calls.append({"to": to, "subject": subject, "html": html, "text": text})
        return True

    monkeypatch.setattr(payments_module, "send_email", _fake_send)
    return calls


def _sign(body_bytes: bytes) -> str:
    return hmac.new(
        key=TEST_WEBHOOK_SECRET.encode("utf-8"), msg=body_bytes, digestmod=hashlib.sha256
    ).hexdigest()


def _subscription_event_body(event: str, razorpay_sub_id: str) -> bytes:
    payload = {
        "entity": "event",
        "event": event,
        "payload": {
            "subscription": {"entity": {"id": razorpay_sub_id, "status": event.split(".")[1]}}
        },
        "created_at": 1700000000,
    }
    return json.dumps(payload).encode("utf-8")


def _post_subscription_event(client: TestClient, event: str, razorpay_sub_id: str):
    body = _subscription_event_body(event, razorpay_sub_id)
    return client.post(
        "/payments/webhook",
        content=body,
        headers={"X-Razorpay-Signature": _sign(body), "Content-Type": "application/json"},
    )


def test_non_active_to_active_sends_one_activation_email(
    client: TestClient, fake_db: FakeSession, sent_emails: list[dict[str, str]]
) -> None:
    response = _post_subscription_event(
        client, "subscription.activated", fake_db.subscription.razorpay_sub_id
    )

    assert response.status_code == 200
    assert fake_db.subscription.status == "active"
    assert fake_db.commit_statuses[0] == "active"
    assert len(sent_emails) == 1
    assert sent_emails[0]["to"] == fake_db.user.email
    assert sent_emails[0]["subject"] == "Your Aspirova Pro is active"
    assert "Pro Lite Monthly" in sent_emails[0]["html"]
    assert "https://aspirova.test" in sent_emails[0]["html"]

    notification = fake_db.added[0]
    assert notification.type == "subscription_activated"
    assert notification.status == "sent"
    assert notification.sent_at is not None
    assert notification.meta == {
        "subscription_id": fake_db.subscription.id,
        "razorpay_sub_id": fake_db.subscription.razorpay_sub_id,
    }


def test_second_charged_event_while_active_sends_nothing(
    client: TestClient, fake_db: FakeSession, sent_emails: list[dict[str, str]]
) -> None:
    first_response = _post_subscription_event(
        client, "subscription.charged", fake_db.subscription.razorpay_sub_id
    )
    second_response = _post_subscription_event(
        client, "subscription.charged", fake_db.subscription.razorpay_sub_id
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert fake_db.subscription.status == "active"
    assert len(sent_emails) == 1
    assert len(fake_db.added) == 1


def test_transition_to_past_due_sends_payment_failed_email(
    client: TestClient, fake_db: FakeSession, sent_emails: list[dict[str, str]]
) -> None:
    response = _post_subscription_event(
        client, "subscription.halted", fake_db.subscription.razorpay_sub_id
    )

    assert response.status_code == 200
    assert fake_db.subscription.status == "past_due"
    assert len(sent_emails) == 1
    assert sent_emails[0]["subject"] == "We couldn't process your payment"
    assert "update your payment method" in sent_emails[0]["text"]
    assert "Pro features are paused until your payment succeeds" in sent_emails[0]["text"]

    notification = fake_db.added[0]
    assert notification.type == "subscription_payment_failed"
    assert notification.status == "sent"


def test_email_exception_does_not_fail_webhook_or_status_update(
    client: TestClient, fake_db: FakeSession, monkeypatch
) -> None:
    def _raise_send_email(*_args) -> bool:
        raise RuntimeError("simulated email failure")

    monkeypatch.setattr(payments_module, "send_email", _raise_send_email)

    response = _post_subscription_event(
        client, "subscription.activated", fake_db.subscription.razorpay_sub_id
    )

    assert response.status_code == 200
    assert fake_db.subscription.status == "active"
    assert fake_db.commit_statuses[0] == "active"
    assert fake_db.added[0].status == "failed"
    assert fake_db.added[0].sent_at is None


def test_terminal_subscription_short_circuits_without_email(
    client: TestClient, fake_db: FakeSession, sent_emails: list[dict[str, str]]
) -> None:
    fake_db.subscription.status = "canceled"

    response = _post_subscription_event(
        client, "subscription.charged", fake_db.subscription.razorpay_sub_id
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ignored_terminal", "event": "subscription.charged"}
    assert fake_db.subscription.status == "canceled"
    assert sent_emails == []
    assert fake_db.added == []
    assert fake_db.commit_statuses == []
