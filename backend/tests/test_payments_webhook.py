"""Integration tests for the Razorpay webhook handler (Doc 02 sec 3.9).
Signature verification is a pure local HMAC-SHA256 computation (no
network call) - fully testable without a real Razorpay account: sign our
own constructed payload with a test secret and confirm the handler
verifies it exactly the same way Razorpay's own client library does.
"""

import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import api.payments as payments_module
from api.deps import get_db
from api.main import app
from core import models
from core.config import get_settings
from core.gating import get_features

TEST_WEBHOOK_SECRET = "test-webhook-secret-not-real"


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
def client(db_session, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "razorpay_webhook_secret", TEST_WEBHOOK_SECRET)
    monkeypatch.setattr(settings, "razorpay_key_id", "rzp_test_placeholder")
    monkeypatch.setattr(settings, "razorpay_key_secret", "placeholder_secret")

    app.dependency_overrides[get_db] = lambda: db_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture(autouse=True)
def sent_emails(monkeypatch) -> list[dict[str, str]]:
    calls: list[dict[str, str]] = []

    def _fake_send(to: str, subject: str, html: str, text: str) -> bool:
        calls.append({"to": to, "subject": subject, "html": html, "text": text})
        return True

    monkeypatch.setattr(payments_module, "send_email", _fake_send)
    return calls


@pytest.fixture
def plan(db_session: Session):
    p = models.Plan(
        key=f"webhook-test-plan-{uuid.uuid4()}",
        price_paise=4900,
        billing="monthly",
        features={},
    )
    db_session.add(p)
    db_session.flush()
    return p


@pytest.fixture
def user(db_session: Session):
    u = models.User(email=f"webhook-test-{uuid.uuid4()}@example.com")
    db_session.add(u)
    db_session.flush()
    return u


def _sign(body_bytes: bytes) -> str:
    return hmac.new(
        key=TEST_WEBHOOK_SECRET.encode("utf-8"), msg=body_bytes, digestmod=hashlib.sha256
    ).hexdigest()


def _subscription_event_body(
    event: str,
    razorpay_sub_id: str,
    current_end: int | None = None,
    created_at: int = 1700000000,
) -> bytes:
    entity = {"id": razorpay_sub_id, "status": event.split(".")[1]}
    if current_end is not None:
        entity["current_end"] = current_end
    payload = {
        "entity": "event",
        "event": event,
        "payload": {"subscription": {"entity": entity}},
        "created_at": created_at,
    }
    return json.dumps(payload).encode("utf-8")


def test_valid_signature_activates_a_subscription(client, db_session, plan, user) -> None:
    razorpay_sub_id = f"sub_test_{uuid.uuid4().hex[:12]}"
    db_session.add(
        models.Subscription(
            user_id=user.id, plan_id=plan.id, status="created", razorpay_sub_id=razorpay_sub_id
        )
    )
    db_session.flush()

    new_period_end = 1735689600  # 2025-01-01T00:00:00Z
    body = _subscription_event_body("subscription.activated", razorpay_sub_id, new_period_end)
    response = client.post(
        "/payments/webhook",
        content=body,
        headers={"X-Razorpay-Signature": _sign(body), "Content-Type": "application/json"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    updated = db_session.query(models.Subscription).filter_by(razorpay_sub_id=razorpay_sub_id).one()
    assert updated.status == "active"
    assert updated.current_period_end.timestamp() == new_period_end


def test_replayed_charged_event_does_not_resurrect_canceled_subscription(
    client, db_session, plan, user
) -> None:
    razorpay_sub_id = f"sub_test_{uuid.uuid4().hex[:12]}"
    current_period_end = datetime.fromtimestamp(1735689600, tz=timezone.utc)
    db_session.add(
        models.Subscription(
            user_id=user.id,
            plan_id=plan.id,
            status="canceled",
            razorpay_sub_id=razorpay_sub_id,
            current_period_end=current_period_end,
        )
    )
    db_session.flush()

    new_period_end = 1767225600  # 2026-01-01T00:00:00Z
    body = _subscription_event_body("subscription.charged", razorpay_sub_id, new_period_end)
    response = client.post(
        "/payments/webhook",
        content=body,
        headers={"X-Razorpay-Signature": _sign(body), "Content-Type": "application/json"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ignored_terminal", "event": "subscription.charged"}
    updated = db_session.query(models.Subscription).filter_by(razorpay_sub_id=razorpay_sub_id).one()
    assert updated.status == "canceled"
    assert updated.current_period_end.timestamp() == current_period_end.timestamp()


def test_current_period_end_only_moves_forward(client, db_session, plan, user) -> None:
    razorpay_sub_id = f"sub_test_{uuid.uuid4().hex[:12]}"
    stored_period_end = datetime.fromtimestamp(1735689600, tz=timezone.utc)
    db_session.add(
        models.Subscription(
            user_id=user.id,
            plan_id=plan.id,
            status="active",
            razorpay_sub_id=razorpay_sub_id,
            current_period_end=stored_period_end,
        )
    )
    db_session.flush()

    older_period_end = 1704067200  # 2024-01-01T00:00:00Z
    older_body = _subscription_event_body("subscription.charged", razorpay_sub_id, older_period_end)
    older_response = client.post(
        "/payments/webhook",
        content=older_body,
        headers={"X-Razorpay-Signature": _sign(older_body), "Content-Type": "application/json"},
    )

    assert older_response.status_code == 200
    updated = db_session.query(models.Subscription).filter_by(razorpay_sub_id=razorpay_sub_id).one()
    assert updated.current_period_end.timestamp() == stored_period_end.timestamp()

    newer_period_end = 1767225600  # 2026-01-01T00:00:00Z
    newer_body = _subscription_event_body("subscription.charged", razorpay_sub_id, newer_period_end)
    newer_response = client.post(
        "/payments/webhook",
        content=newer_body,
        headers={"X-Razorpay-Signature": _sign(newer_body), "Content-Type": "application/json"},
    )

    assert newer_response.status_code == 200
    updated = db_session.query(models.Subscription).filter_by(razorpay_sub_id=razorpay_sub_id).one()
    assert updated.current_period_end.timestamp() == newer_period_end


def test_cancelled_event_marks_subscription_canceled(client, db_session, plan, user) -> None:
    razorpay_sub_id = f"sub_test_{uuid.uuid4().hex[:12]}"
    db_session.add(
        models.Subscription(
            user_id=user.id, plan_id=plan.id, status="active", razorpay_sub_id=razorpay_sub_id
        )
    )
    db_session.flush()

    body = _subscription_event_body("subscription.cancelled", razorpay_sub_id)
    response = client.post(
        "/payments/webhook",
        content=body,
        headers={"X-Razorpay-Signature": _sign(body), "Content-Type": "application/json"},
    )

    assert response.status_code == 200
    updated = db_session.query(models.Subscription).filter_by(razorpay_sub_id=razorpay_sub_id).one()
    assert updated.status == "canceled"


def test_invalid_signature_is_rejected(client) -> None:
    body = _subscription_event_body("subscription.activated", "sub_whatever")
    response = client.post(
        "/payments/webhook",
        content=body,
        headers={
            "X-Razorpay-Signature": "not-a-real-signature",
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 400


def test_missing_signature_header_is_rejected(client) -> None:
    body = _subscription_event_body("subscription.activated", "sub_whatever")
    response = client.post("/payments/webhook", content=body)
    assert response.status_code == 400


def test_unrecognized_event_is_acknowledged_not_errored(client) -> None:
    body = _subscription_event_body("subscription.authenticated", "sub_whatever")
    response = client.post(
        "/payments/webhook",
        content=body,
        headers={"X-Razorpay-Signature": _sign(body), "Content-Type": "application/json"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"


def test_malformed_known_event_is_acknowledged_not_errored(client) -> None:
    payload = {
        "entity": "event",
        "event": "subscription.activated",
        "payload": {"subscription": {}},
        "created_at": 1700000000,
    }
    body = json.dumps(payload).encode("utf-8")
    response = client.post(
        "/payments/webhook",
        content=body,
        headers={"X-Razorpay-Signature": _sign(body), "Content-Type": "application/json"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "malformed_payload",
        "event": "subscription.activated",
    }


def test_unknown_subscription_id_is_acknowledged_not_errored(client) -> None:
    body = _subscription_event_body("subscription.activated", "sub_does_not_exist_anywhere")
    response = client.post(
        "/payments/webhook",
        content=body,
        headers={"X-Razorpay-Signature": _sign(body), "Content-Type": "application/json"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "no_matching_subscription"


@pytest.fixture
def subscription(db_session: Session, plan, user):
    subscription = models.Subscription(
        user_id=user.id,
        plan_id=plan.id,
        status="created",
        razorpay_sub_id=f"sub_test_{uuid.uuid4().hex[:12]}",
        current_period_end=datetime.now(timezone.utc) + timedelta(days=30),
    )
    db_session.add(subscription)
    db_session.flush()
    return subscription


def _post_subscription_event(
    client: TestClient,
    subscription: models.Subscription,
    event: str,
    created_at: int,
    current_end: int | None = None,
):
    body = _subscription_event_body(
        event, subscription.razorpay_sub_id, current_end=current_end, created_at=created_at
    )
    return client.post(
        "/payments/webhook",
        content=body,
        headers={"X-Razorpay-Signature": _sign(body), "Content-Type": "application/json"},
    )


def test_stale_halted_event_preserves_paid_access(
    client, db_session, plan, user, subscription, sent_emails
) -> None:
    plan.features = {"copilot": True, "dream_companies_limit": 10}
    period_end = int(subscription.current_period_end.timestamp())
    charged = _post_subscription_event(
        client, subscription, "subscription.charged", 2000, current_end=period_end
    )
    assert charged.status_code == 200
    assert charged.json()["status"] == "ok"

    halted = _post_subscription_event(client, subscription, "subscription.halted", 1000)

    assert halted.status_code == 200
    assert halted.json() == {"status": "ignored_stale", "event": "subscription.halted"}
    db_session.refresh(subscription)
    assert subscription.status == "active"
    assert subscription.last_webhook_event_at == datetime.fromtimestamp(2000, tz=timezone.utc)
    assert (
        db_session.query(models.Notification)
        .filter_by(user_id=user.id, type="subscription_payment_failed")
        .count()
        == 0
    )
    assert len(sent_emails) == 1
    assert sent_emails[0]["subject"] == "Your Aspirova Pro is active"
    assert get_features(db_session, user) == plan.features


@pytest.mark.parametrize(
    "first_event,first_time,second_event,second_time,expected_status,response_status",
    [
        ("subscription.halted", 2000, "subscription.charged", 1000, "past_due", "ignored_stale"),
        ("subscription.charged", 1000, "subscription.halted", 2000, "past_due", "ok"),
        ("subscription.halted", 1000, "subscription.charged", 2000, "active", "ok"),
    ],
    ids=["stale-charge", "newer-failure", "newer-recovery"],
)
def test_subscription_events_follow_creation_order(
    client,
    db_session,
    subscription,
    first_event,
    first_time,
    second_event,
    second_time,
    expected_status,
    response_status,
) -> None:
    first = _post_subscription_event(client, subscription, first_event, first_time)
    assert first.status_code == 200
    assert first.json()["status"] == "ok"

    second = _post_subscription_event(client, subscription, second_event, second_time)

    assert second.status_code == 200
    assert second.json() == {"status": response_status, "event": second_event}
    db_session.refresh(subscription)
    assert subscription.status == expected_status
    assert subscription.last_webhook_event_at == datetime.fromtimestamp(2000, tz=timezone.utc)


def test_same_timestamp_events_apply_in_arrival_order(client, db_session, subscription) -> None:
    activated = _post_subscription_event(client, subscription, "subscription.activated", 1000)
    assert activated.status_code == 200
    assert activated.json()["status"] == "ok"

    charged = _post_subscription_event(client, subscription, "subscription.charged", 1000)

    assert charged.status_code == 200
    assert charged.json() == {"status": "ok", "event": "subscription.charged"}
    db_session.refresh(subscription)
    assert subscription.status == "active"
    assert subscription.last_webhook_event_at == datetime.fromtimestamp(1000, tz=timezone.utc)


def test_missing_created_at_applies_without_moving_event_time(
    client, db_session, subscription, caplog
) -> None:
    charged = _post_subscription_event(client, subscription, "subscription.charged", 2000)
    assert charged.status_code == 200
    payload = json.loads(
        _subscription_event_body("subscription.halted", subscription.razorpay_sub_id)
    )
    del payload["created_at"]
    body = json.dumps(payload).encode("utf-8")

    response = client.post(
        "/payments/webhook",
        content=body,
        headers={"X-Razorpay-Signature": _sign(body), "Content-Type": "application/json"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "event": "subscription.halted"}
    db_session.refresh(subscription)
    assert subscription.status == "past_due"
    assert subscription.last_webhook_event_at == datetime.fromtimestamp(2000, tz=timezone.utc)
    assert "no usable created_at" in caplog.text


@pytest.mark.parametrize("event", ["subscription.cancelled", "subscription.completed"])
def test_stale_terminal_event_still_applies(client, db_session, subscription, event) -> None:
    charged = _post_subscription_event(client, subscription, "subscription.charged", 2000)
    assert charged.status_code == 200

    terminal = _post_subscription_event(client, subscription, event, 1000)

    assert terminal.status_code == 200
    assert terminal.json() == {"status": "ok", "event": event}
    db_session.refresh(subscription)
    assert subscription.status == "canceled"
    assert subscription.last_webhook_event_at == datetime.fromtimestamp(2000, tz=timezone.utc)


def test_stale_event_does_not_extend_current_period_end(client, db_session, subscription) -> None:
    stored_period_end = subscription.current_period_end
    charged = _post_subscription_event(client, subscription, "subscription.charged", 2000)
    assert charged.status_code == 200
    later_period_end = int((stored_period_end + timedelta(days=30)).timestamp())

    stale = _post_subscription_event(
        client, subscription, "subscription.halted", 1000, current_end=later_period_end
    )

    assert stale.status_code == 200
    assert stale.json() == {"status": "ignored_stale", "event": "subscription.halted"}
    db_session.refresh(subscription)
    assert subscription.status == "active"
    assert subscription.current_period_end == stored_period_end
    assert subscription.last_webhook_event_at == datetime.fromtimestamp(2000, tz=timezone.utc)


def test_charged_redelivery_does_not_send_second_activation_email(
    client, db_session, user, subscription, sent_emails
) -> None:
    first = _post_subscription_event(client, subscription, "subscription.charged", 2000)
    assert first.status_code == 200
    assert first.json()["status"] == "ok"

    redelivery = _post_subscription_event(client, subscription, "subscription.charged", 2000)

    assert redelivery.status_code == 200
    assert redelivery.json() == {"status": "ok", "event": "subscription.charged"}
    db_session.refresh(subscription)
    assert subscription.status == "active"
    assert subscription.last_webhook_event_at == datetime.fromtimestamp(2000, tz=timezone.utc)
    assert len(sent_emails) == 1
    assert sent_emails[0]["subject"] == "Your Aspirova Pro is active"
    assert (
        db_session.query(models.Notification)
        .filter_by(user_id=user.id, type="subscription_activated")
        .count()
        == 1
    )


@pytest.mark.parametrize("created_at", [None, True, False, 0, -1, "2000", 1000.5, 10**100])
def test_invalid_created_at_applies_without_moving_event_time(
    client, db_session, subscription, caplog, created_at
) -> None:
    charged = _post_subscription_event(client, subscription, "subscription.charged", 2000)
    assert charged.status_code == 200
    payload = json.loads(
        _subscription_event_body("subscription.halted", subscription.razorpay_sub_id)
    )
    payload["created_at"] = created_at
    body = json.dumps(payload).encode("utf-8")

    response = client.post(
        "/payments/webhook",
        content=body,
        headers={"X-Razorpay-Signature": _sign(body), "Content-Type": "application/json"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "event": "subscription.halted"}
    db_session.refresh(subscription)
    assert subscription.status == "past_due"
    assert subscription.last_webhook_event_at == datetime.fromtimestamp(2000, tz=timezone.utc)
    assert "no usable created_at" in caplog.text
