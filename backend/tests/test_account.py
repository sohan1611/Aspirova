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
    assert payload["resume"] is None


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


def test_patch_account_persists_and_round_trips_resume_metadata(client) -> None:
    resume = {
        "path": "7b4dcf67-d226-4d77-b0e5-5a4ec86f7f0a/resume.pdf",
        "filename": "Sohan Resume.pdf",
        "uploaded_at": "2026-07-26T12:00:00.000Z",
        "ats": {
            "score": 82,
            "checks": [
                {
                    "id": "parseability",
                    "label": "PDF parseability",
                    "status": "pass",
                    "points": 20,
                    "maxPoints": 20,
                    "tip": "",
                }
            ],
        },
    }

    response = client.patch("/account/me", json={"resume": resume})

    assert response.status_code == 200
    assert response.json()["resume"] == resume

    read_back = client.get("/account/me")
    assert read_back.status_code == 200
    assert read_back.json()["resume"] == resume


def test_patch_account_clears_resume_without_removing_skills(
    client, db_session: Session, user: models.User
) -> None:
    resume = {
        "path": f"{user.id}/resume.pdf",
        "filename": "resume.pdf",
        "uploaded_at": "2026-11-03T12:00:00.000Z",
        "ats": {"score": 82, "checks": []},
    }
    skills = [
        {"name": "Python", "source": "resume"},
        {"name": "Figma", "source": "manual"},
    ]
    saved = client.patch("/account/me", json={"resume": resume, "skills": skills})
    assert saved.status_code == 200
    assert saved.json()["resume"] == resume

    unchanged = client.patch("/account/me", json={"display_name": "Ada"})
    assert unchanged.status_code == 200
    assert unchanged.json()["resume"] == resume

    response = client.patch("/account/me", json={"resume": None})

    assert response.status_code == 200
    assert response.json()["resume"] is None
    assert response.json()["skills"] == skills

    db_session.refresh(user)
    assert user.resume is None
    assert user.skills == skills

    read_back = client.get("/account/me")
    assert read_back.status_code == 200
    assert read_back.json()["resume"] is None
    assert read_back.json()["skills"] == skills


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
        {"resume": []},
    ],
)
def test_patch_account_rejects_invalid_smart_profile_shape_or_size(client, payload) -> None:
    response = client.patch("/account/me", json=payload)

    assert response.status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {"resume": {"filename": "x" * 256}},
        {"resume": {"filename": "resume.pdf", "extra": "x" * (8 * 1024)}},
    ],
)
def test_patch_account_rejects_invalid_resume_metadata(client, payload) -> None:
    response = client.patch("/account/me", json=payload)

    assert response.status_code == 400


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


def test_account_export_requires_auth() -> None:
    app.dependency_overrides[get_db] = lambda: None
    try:
        with TestClient(app) as unauthenticated_client:
            response = unauthenticated_client.get("/account/export")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 401


def test_account_export_without_optional_data(client, user) -> None:
    response = client.get("/account/export")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    payload = response.json()
    assert datetime.fromisoformat(payload["exported_at"].replace("Z", "+00:00"))
    assert payload["account"]["email"] == user.email
    assert payload["resume"] is None
    assert payload["tracked_opportunities"] == []
    assert payload["saved_searches"] == []
    assert payload["followed_companies"] == []
    assert payload["subscription"] == {
        "plan_key": "free",
        "status": "free",
        "current_period_end": None,
    }


def test_account_exports_are_user_scoped_and_omit_internal_fields(
    client, db_session: Session, user: models.User, free_plan: models.Plan
) -> None:
    other_user = models.User(email=f"export-other-{uuid.uuid4()}@example.com")
    db_session.add(other_user)
    db_session.flush()
    user.referred_by = other_user.id
    users = [user, other_user]
    company_names = []
    company_slugs = []
    opportunity_slugs = []
    saved_names = []
    for index, owner in enumerate(users):
        suffix = uuid.uuid4().hex
        company = models.Company(slug=f"export-company-{suffix}", name=f"Export company {index}")
        db_session.add(company)
        db_session.flush()
        opportunity = models.Opportunity(
            slug=f"export-opportunity-{suffix}",
            company_id=company.id,
            title=f"Export opportunity {index}",
            apply_url="https://example.com/apply",
        )
        db_session.add(opportunity)
        db_session.flush()
        owner.display_name = f"Export user {index}"
        owner.college = f"College {index}"
        owner.graduation_year = 2030 + index
        owner.field_profile = {"stream": "engineering", "divisions": [], "interests": []}
        owner.skills = [{"name": f"Skill {index}", "source": "manual"}]
        owner.exposure = {"notes": f"Experience {index}"}
        owner.notification_prefs = {"daily_digest": False}
        owner.resume = {
            "path": f"{owner.id}/private-resume.pdf",
            "filename": f"resume-{index}.pdf",
            "uploaded_at": "2026-11-01T12:00:00Z",
            "ats": {"score": 70 + index, "checks": []},
        }
        search_name = f"Export search {index}"
        db_session.add_all(
            [
                models.Bookmark(user_id=owner.id, opportunity_id=opportunity.id, status="applied"),
                models.SavedSearch(
                    user_id=owner.id, name=search_name, params={"q": f"Query {index}"}
                ),
                models.DreamCompany(user_id=owner.id, company_id=company.id),
                models.Subscription(
                    user_id=owner.id,
                    plan_id=free_plan.id,
                    status="canceled",
                    razorpay_sub_id=f"sub_export_test_{suffix}",
                    current_period_end=datetime(2026, 12, 1, tzinfo=timezone.utc),
                ),
            ]
        )
        company_names.append(company.name)
        company_slugs.append(company.slug)
        opportunity_slugs.append(opportunity.slug)
        saved_names.append(search_name)
    db_session.flush()

    def assert_no_internal_fields(value):
        if isinstance(value, dict):
            for key, item in value.items():
                assert key not in {"path", "storage_path", "referred_by"}
                assert "razorpay" not in key
                assert "provider" not in key
                assert_no_internal_fields(item)
        elif isinstance(value, list):
            for item in value:
                assert_no_internal_fields(item)

    for index, owner in enumerate(users):
        app.dependency_overrides[get_current_user] = lambda: owner
        response = client.get("/account/export")
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-store"
        payload = response.json()
        assert payload["account"] == {
            key: getattr(owner, key)
            for key in (
                "email",
                "display_name",
                "college",
                "graduation_year",
                "field_profile",
                "skills",
                "exposure",
                "notification_prefs",
            )
        } | {"created_at": payload["account"]["created_at"]}
        assert payload["account"]["created_at"]
        assert payload["resume"] == {
            key: owner.resume[key] for key in ("filename", "uploaded_at", "ats")
        }
        tracked = payload["tracked_opportunities"]
        assert len(tracked) == 1
        assert tracked[0] == {
            "slug": opportunity_slugs[index],
            "title": f"Export opportunity {index}",
            "company": company_names[index],
            "status": "applied",
            "saved_at": tracked[0]["saved_at"],
        }
        assert tracked[0]["saved_at"]
        assert len(payload["saved_searches"]) == 1
        assert payload["saved_searches"][0]["name"] == saved_names[index]
        assert payload["saved_searches"][0]["params"] == {"q": f"Query {index}"}
        assert payload["saved_searches"][0]["alerts_enabled"] is True
        assert payload["saved_searches"][0]["created_at"]
        assert payload["followed_companies"] == [
            {"name": company_names[index], "slug": company_slugs[index]},
        ]
        assert payload["subscription"]["status"] == "canceled"
        assert payload["subscription"]["plan_key"] == free_plan.key
        assert payload["subscription"]["current_period_end"]
        assert users[1 - index].email not in response.text
        assert opportunity_slugs[1 - index] not in response.text
        assert saved_names[1 - index] not in response.text
        assert "private-resume.pdf" not in response.text
        assert "sub_export_test_" not in response.text
        assert_no_internal_fields(payload)


def test_account_export_rate_limit_uses_authenticated_user(
    client, user: models.User, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.ratelimit import RateLimitResult

    calls = []

    async def deny_export(redis, **kwargs):
        calls.append(kwargs)
        return RateLimitResult(allowed=False, retry_after_seconds=30)

    monkeypatch.setattr(account_module, "check_rate_limit", deny_export)
    response = client.get("/account/export")

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "30"
    assert calls == [
        {
            "bucket": "account_export",
            "identifier": str(user.id),
            "max_requests": 5,
            "window_seconds": 60,
        }
    ]
