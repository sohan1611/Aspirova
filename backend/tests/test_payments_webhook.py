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

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from api.deps import get_db
from api.main import app
from core import models
from core.config import get_settings
from core.db import make_engine

TEST_WEBHOOK_SECRET = "test-webhook-secret-not-real"


@pytest.fixture
def db_session():
    engine = make_engine()
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
    event: str, razorpay_sub_id: str, current_end: int | None = None
) -> bytes:
    entity = {"id": razorpay_sub_id, "status": event.split(".")[1]}
    if current_end is not None:
        entity["current_end"] = current_end
    payload = {
        "entity": "event",
        "event": event,
        "payload": {"subscription": {"entity": entity}},
        "created_at": 1700000000,
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

    body = _subscription_event_body("subscription.activated", razorpay_sub_id)
    response = client.post(
        "/payments/webhook",
        content=body,
        headers={"X-Razorpay-Signature": _sign(body), "Content-Type": "application/json"},
    )

    assert response.status_code == 200
    updated = db_session.query(models.Subscription).filter_by(razorpay_sub_id=razorpay_sub_id).one()
    assert updated.status == "active"


def test_charged_event_refreshes_current_period_end(client, db_session, plan, user) -> None:
    razorpay_sub_id = f"sub_test_{uuid.uuid4().hex[:12]}"
    db_session.add(
        models.Subscription(
            user_id=user.id, plan_id=plan.id, status="active", razorpay_sub_id=razorpay_sub_id
        )
    )
    db_session.flush()

    new_period_end = 1735689600  # 2025-01-01T00:00:00Z
    body = _subscription_event_body("subscription.charged", razorpay_sub_id, new_period_end)
    response = client.post(
        "/payments/webhook",
        content=body,
        headers={"X-Razorpay-Signature": _sign(body), "Content-Type": "application/json"},
    )

    assert response.status_code == 200
    updated = db_session.query(models.Subscription).filter_by(razorpay_sub_id=razorpay_sub_id).one()
    assert updated.current_period_end.timestamp() == new_period_end


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


def test_unknown_subscription_id_is_acknowledged_not_errored(client) -> None:
    body = _subscription_event_body("subscription.activated", "sub_does_not_exist_anywhere")
    response = client.post(
        "/payments/webhook",
        content=body,
        headers={"X-Razorpay-Signature": _sign(body), "Content-Type": "application/json"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "no_matching_subscription"
