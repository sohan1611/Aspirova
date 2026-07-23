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
    payload = response.json()
    assert payload["plan"]["status"] == "free"
    assert payload["plan"]["key"] == "free"
    assert payload["field_profile"] is None
    assert payload["skills"] is None
    assert payload["exposure"] is None


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


def test_patch_account_sets_and_replaces_smart_profile_data(client) -> None:
    first = client.patch(
        "/account/me",
        json={
            "field_profile": {
                "stream": "engineering",
                "divisions": ["cse", "it"],
                "interests": ["web_dev", "cloud_devops"],
            },
            "skills": [
                {"name": "Python", "source": "resume"},
                {"name": "Figma", "source": "manual"},
            ],
            "exposure": {
                "experience": "One software internship",
                "notes": "Interested in product teams",
            },
        },
    )

    assert first.status_code == 200
    assert first.json()["field_profile"] == {
        "stream": "engineering",
        "divisions": ["cse", "it"],
        "interests": ["web_dev", "cloud_devops"],
    }
    assert first.json()["skills"] == [
        {"name": "Python", "source": "resume"},
        {"name": "Figma", "source": "manual"},
    ]
    assert first.json()["exposure"] == {
        "experience": "One software internship",
        "notes": "Interested in product teams",
    }

    replacement = client.patch(
        "/account/me",
        json={
            "field_profile": {
                "stream": "management",
                "divisions": ["marketing"],
                "interests": ["growth"],
            },
            "skills": [],
            "exposure": {"experience": None, "notes": "Changing fields"},
        },
    )

    assert replacement.status_code == 200
    payload = replacement.json()
    assert payload["field_profile"] == {
        "stream": "management",
        "divisions": ["marketing"],
        "interests": ["growth"],
    }
    assert payload["skills"] == []
    assert payload["exposure"] == {"experience": None, "notes": "Changing fields"}

    read_back = client.get("/account/me")
    assert read_back.status_code == 200
    assert read_back.json()["field_profile"] == payload["field_profile"]
    assert read_back.json()["skills"] == payload["skills"]
    assert read_back.json()["exposure"] == payload["exposure"]


def test_patch_account_normalizes_smart_profile_data(client) -> None:
    response = client.patch(
        "/account/me",
        json={
            "field_profile": {
                "stream": " engineering ",
                "divisions": [" cse ", 7, "cse", "", "it"],
                "interests": [" web_dev ", None, "web_dev", "data_science"],
            },
            "skills": [
                {"name": " Python ", "source": "resume"},
                {"name": "SQL"},
                {"name": "", "source": "manual"},
                {"name": 7, "source": "manual"},
                {"name": "x" * 81, "source": "manual"},
                {"name": "Figma", "source": "unknown"},
                "not a skill",
            ],
            "exposure": {
                "experience": "  Two internships  ",
                "notes": "   ",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["field_profile"] == {
        "stream": "engineering",
        "divisions": ["cse", "it"],
        "interests": ["web_dev", "data_science"],
    }
    assert payload["skills"] == [
        {"name": "Python", "source": "resume"},
        {"name": "SQL", "source": "manual"},
    ]
    assert payload["exposure"] == {"experience": "Two internships", "notes": None}


def test_patch_account_clamps_smart_profile_collection_caps(client) -> None:
    response = client.patch(
        "/account/me",
        json={
            "field_profile": {
                "stream": "engineering",
                "divisions": [f"division-{index}" for index in range(70)],
                "interests": [f"interest-{index}" for index in range(70)],
            },
            "skills": [{"name": f"Skill {index}"} for index in range(105)],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["field_profile"]["divisions"] == [f"division-{index}" for index in range(64)]
    assert payload["field_profile"]["interests"] == [f"interest-{index}" for index in range(64)]
    assert payload["skills"] == [
        {"name": f"Skill {index}", "source": "manual"} for index in range(100)
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {"field_profile": []},
        {"skills": {}},
        {"exposure": []},
        {"field_profile": {"stream": "x" * 65}},
        {"field_profile": {"divisions": ["x" * 65]}},
        {"field_profile": {"interests": ["x" * 65]}},
        {"exposure": {"notes": "x" * 2_001}},
    ],
)
def test_patch_account_rejects_invalid_smart_profile_shape_or_size(client, payload) -> None:
    response = client.patch("/account/me", json=payload)

    assert response.status_code == 422


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
