"""SEC-01: audit of all 33 routes accessing user-owned data in backend/api.

Session-authenticated routes (29 method/path pairs):
  bookmarks.py: GET /bookmarks; POST, PATCH, DELETE /bookmarks/{opportunity_slug}
  saved_searches.py: GET, POST /saved-searches;
    PATCH, DELETE /saved-searches/{saved_search_id}
  dream_companies.py: GET, PUT /dream-companies;
    POST, DELETE /dream-companies/{company_slug}
  notifications.py: GET /notifications; GET /notifications/unread-count;
    POST /notifications/read
  account.py: GET, PATCH /account/me; GET /account/export; POST /subscription/cancel
  resume.py: POST /resume; GET /resume/matches
  referral.py: GET /referral/me; POST /referral/claim
  payments.py: POST /payments/checkout/{plan_key};
    POST /payments/upgrade/{plan_key}; POST /payments/upgrade/verify;
    POST /payments/switch-to-annual/{plan_key}; POST /payments/switch-to-annual/verify
  copilot.py: POST /copilot (reads the caller's subscription feature gate)

Other authorization contracts (4 method/path pairs):
  notifications.py: GET, POST /notifications/unsubscribe (signed scoped token,
    deliberately no session; GET only renders confirmation)
  payments.py: POST /payments/webhook (provider signature, no session)
  reports.py: POST /reports (public create, optional authenticated ownership;
    no read/update/delete API)

There are no per-id reads for bookmarks, searches, follows, notifications,
resume profiles, referrals or subscriptions, nor per-id profile writes/deletes.
Test real routes: foreign search mutations/payment verification reject with
403/404; bookmark/follow DELETE deliberately returns idempotent 204; PUT follows
and POST saves create/update only the caller's row for a public slug. Self-only
and bulk endpoints ignore supplied foreign IDs and must leave all A rows intact.
Plan changes are disabled with 409 for everyone. Referral codes are public
invites, not private object IDs; claiming one intentionally rewards its owner.
/for-you reads public opportunities with client-supplied filters, /waitlist
sends a public signup email without storing user-owned rows, and anonymous
apply/view counts contain no user IDs. These are outside the private audit.

Uses the shared throwaway Postgres engine and rollback fixture pattern from
test_bookmarks.py/test_account.py. All external services are stubbed locally.
"""

import base64
import copy
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from api import account, bookmarks, copilot, dream_companies, payments, reports
from api import saved_searches
from api.auth import get_current_user
from api.deps import get_db
from api.main import app
from core import models
from core.config import get_settings
from core.unsubscribe import make_token
from pipeline import resume_match


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


@pytest.fixture(autouse=True)
def local_services(monkeypatch):
    for module in (account, bookmarks, copilot, dream_companies, reports, saved_searches):
        monkeypatch.setattr(module, "get_redis", lambda: None)

    # Any unexpected provider call is a test failure, never a network request.
    def unexpected_provider(*args, **kwargs):
        pytest.fail("authorization must be checked before contacting a provider")

    monkeypatch.setattr(account, "_razorpay_client", unexpected_provider)
    monkeypatch.setattr(payments, "_razorpay_client", unexpected_provider)
    monkeypatch.setattr(payments.razorpay, "Client", unexpected_provider)
    monkeypatch.setattr(reports, "_notify_founder", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        resume_match.ai_client, "embed", lambda *args, **kwargs: [[1.0] + [0.0] * 1535]
    )
    monkeypatch.setattr(get_settings(), "unsubscribe_secret", "cross-user-test-signing-key")
    monkeypatch.setattr(get_settings(), "razorpay_webhook_secret", "cross-user-test-webhook-key")


@pytest.fixture
def cross(db_session):
    suffix = uuid.uuid4().hex
    free = db_session.scalar(select(models.Plan).where(models.Plan.key == "free"))
    if free is None:
        free = models.Plan(key="free", price_paise=0, features={})
        db_session.add(free)
    free.features = {"dream_companies_limit": 5, "resume_match": True, "copilot": False}
    paid = models.Plan(
        key=f"authz-paid-{suffix}",
        price_paise=4900,
        billing="monthly",
        features={"dream_companies_limit": 5, "resume_match": True, "copilot": True},
        razorpay_plan_id=f"plan_authz_{suffix}",
    )
    owner = models.User(email=f"authz-a-{suffix}@example.com", invite_code=f"A{suffix}")
    other = models.User(email=f"authz-b-{suffix}@example.com", invite_code=f"B{suffix}")
    company = models.Company(
        slug=f"authz-company-{suffix}",
        name=f"Private follow {suffix}",
        name_normalized=f"private follow {suffix}",
    )
    opportunity = models.Opportunity(
        slug=f"authz-opportunity-{suffix}",
        title="Authorization test opportunity",
        apply_url="https://example.com/authz",
        company=company,
    )
    db_session.add_all([paid, owner, other, company, opportunity])
    db_session.flush()
    referred = models.User(email=f"authz-referred-{suffix}@example.com", referred_by=owner.id)
    subscription = models.Subscription(
        user_id=owner.id,
        plan_id=paid.id,
        status="active",
        razorpay_sub_id=f"sub_authz_{suffix}",
        current_period_end=datetime.now(UTC) + timedelta(days=30),
    )
    db_session.add_all([referred, subscription])
    db_session.flush()
    upgrade = models.SubscriptionUpgrade(
        user_id=owner.id,
        subscription_id=subscription.id,
        from_plan_id=free.id,
        to_plan_id=paid.id,
        amount_paise=100,
        razorpay_order_id=f"order_authz_{suffix}",
        status="created",
    )
    annual = models.SubscriptionUpgrade(
        user_id=owner.id,
        subscription_id=subscription.id,
        from_plan_id=free.id,
        to_plan_id=paid.id,
        amount_paise=100,
        razorpay_order_id=f"order_authz_annual_{suffix}",
        status="created",
        kind="monthly_to_annual_switch",
    )
    notice = models.Notification(
        user_id=owner.id,
        type="closing_soon",
        opportunity_id=opportunity.id,
        status="sent",
        sent_at=datetime.now(UTC),
    )
    db_session.add_all([upgrade, annual, notice])
    db_session.flush()
    actor = {"user": owner}
    previous_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: actor["user"]
    app.dependency_overrides[reports.get_optional_current_user] = lambda: actor["user"]
    try:
        with TestClient(app) as client:
            assert client.post(f"/bookmarks/{opportunity.slug}").status_code == 204
            assert (
                client.patch(
                    f"/bookmarks/{opportunity.slug}", json={"status": "interviewing"}
                ).status_code
                == 204
            )
            search = client.post(
                "/saved-searches", json={"name": f"A search {suffix}", "params": {"q": suffix}}
            )
            assert search.status_code == 200
            assert (
                client.put(
                    "/dream-companies",
                    json={"company_slugs": [company.slug], "roles": ["software"]},
                ).status_code
                == 204
            )
            assert (
                client.patch(
                    "/account/me",
                    json={
                        "display_name": "Private owner",
                        "skills": [{"name": "Python", "source": "manual"}],
                        "field_profile": {
                            "stream": "engineering",
                            "divisions": [],
                            "interests": [],
                        },
                        "exposure": {"notes": suffix},
                        "notification_prefs": {"daily_digest": True},
                        "resume": {
                            "filename": f"private-{suffix}.pdf",
                            "path": f"{owner.id}/private.pdf",
                        },
                    },
                ).status_code
                == 200
            )
            assert (
                client.post("/resume", json={"resume_text": "Owner's private resume"}).status_code
                == 200
            )
            assert (
                client.post(
                    "/reports", json={"category": "bug", "message": f"A private report {suffix}"}
                ).status_code
                == 200
            )
            actor["user"] = other
            yield {
                "client": client,
                "actor": actor,
                "owner": owner,
                "other": other,
                "company": company,
                "opportunity": opportunity,
                "search_id": search.json()["id"],
                "upgrade": upgrade,
                "annual": annual,
                "notice": notice,
                "paid": paid,
                "subscription": subscription,
            }
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)


def owner_snapshot(db: Session, owner_id) -> dict:
    """Reload all A-owned rows so identity-map state cannot hide a leaked write."""
    db.expire_all()
    result = {}
    for model in (
        models.User,
        models.Bookmark,
        models.SavedSearch,
        models.DreamCompany,
        models.Notification,
        models.ResumeProfile,
        models.Subscription,
        models.SubscriptionUpgrade,
        models.BugReport,
    ):
        predicate = model.id == owner_id if model is models.User else model.user_id == owner_id
        rows = db.scalars(select(model).where(predicate)).all()
        values = []
        for row in rows:
            value = {}
            for column in inspect(model).columns:
                item = getattr(row, column.key)
                value[column.key] = (
                    item.tolist() if hasattr(item, "tolist") else copy.deepcopy(item)
                )
            values.append(value)
        result[model.__tablename__] = sorted(values, key=repr)
    return result


@pytest.mark.parametrize(
    "operation", ["search_patch", "search_delete", "bookmark_patch", "upgrade", "annual", "cancel"]
)
def test_foreign_object_mutations_are_rejected(cross, db_session, operation) -> None:
    before = owner_snapshot(db_session, cross["owner"].id)
    client = cross["client"]
    if operation == "search_patch":
        response = client.patch(f"/saved-searches/{cross['search_id']}", json={"name": "Stolen"})
    elif operation == "search_delete":
        response = client.delete(f"/saved-searches/{cross['search_id']}")
    elif operation == "bookmark_patch":
        response = client.patch(
            f"/bookmarks/{cross['opportunity'].slug}", json={"status": "archived"}
        )
    elif operation in {"upgrade", "annual"}:
        record = cross[operation]
        path = "upgrade" if operation == "upgrade" else "switch-to-annual"
        response = client.post(
            f"/payments/{path}/verify",
            json={
                "razorpay_order_id": record.razorpay_order_id,
                "razorpay_payment_id": "payment_attack",
                "razorpay_signature": "invalid",
            },
        )
    else:
        response = client.post(
            "/subscription/cancel", json={"subscription_id": cross["subscription"].id}
        )
    assert response.status_code in {403, 404}
    assert owner_snapshot(db_session, cross["owner"].id) == before


@pytest.mark.parametrize(
    "path",
    [
        "/bookmarks",
        "/saved-searches",
        "/dream-companies",
        "/notifications",
        "/notifications/unread-count",
        "/account/me",
        "/account/export",
        "/referral/me",
        "/resume/matches",
    ],
)
def test_private_reads_return_only_the_caller(cross, db_session, path) -> None:
    before = owner_snapshot(db_session, cross["owner"].id)
    response = cross["client"].get(path, params={"user_id": str(cross["owner"].id)})
    assert response.status_code == 200
    body = response.json()
    if path in {"/bookmarks", "/saved-searches", "/dream-companies", "/resume/matches"}:
        assert body == []
    elif path == "/notifications":
        assert body == {"items": [], "unread": 0}
    elif path == "/notifications/unread-count":
        assert body == {"unread": 0}
    elif path == "/account/me":
        assert body["email"] == cross["other"].email
        assert body["resume"] is None
        assert body["skills"] is None
        assert body["field_profile"] is None
        assert body["exposure"] is None
        assert body["plan"]["status"] == "free"
    elif path == "/account/export":
        assert body["account"]["email"] == cross["other"].email
        assert body["tracked_opportunities"] == []
        assert body["saved_searches"] == []
        assert body["followed_companies"] == []
        assert body["resume"] is None
        assert body["subscription"]["status"] == "free"
    else:
        assert body["invite_code"] == cross["other"].invite_code
        assert body["referral_count"] == 0
        assert body["reward_active_until"] is None
    assert cross["owner"].email not in response.text
    assert owner_snapshot(db_session, cross["owner"].id) == before


def test_idempotent_deletes_and_public_slug_writes_do_not_touch_owner(cross, db_session) -> None:
    before = owner_snapshot(db_session, cross["owner"].id)
    client = cross["client"]
    for path in (
        f"/bookmarks/{cross['opportunity'].slug}",
        f"/dream-companies/{cross['company'].slug}",
    ):
        assert client.delete(path).status_code == 204
        assert owner_snapshot(db_session, cross["owner"].id) == before
        assert client.post(path).status_code == 204
        assert owner_snapshot(db_session, cross["owner"].id) == before
        assert client.delete(path).status_code == 204
        assert owner_snapshot(db_session, cross["owner"].id) == before
    assert (
        client.put(
            "/dream-companies",
            json={
                "company_slugs": [cross["company"].slug],
                "roles": [],
                "user_id": str(cross["owner"].id),
            },
        ).status_code
        == 204
    )
    follow = db_session.scalar(
        select(models.DreamCompany).where(models.DreamCompany.user_id == cross["other"].id)
    )
    assert follow.roles == []
    assert owner_snapshot(db_session, cross["owner"].id) == before


def test_bulk_and_self_writes_ignore_foreign_ids(cross, db_session) -> None:
    before = owner_snapshot(db_session, cross["owner"].id)
    client = cross["client"]
    owner_id = str(cross["owner"].id)
    for payload in (
        {"display_name": "Other user", "resume": {"filename": "other.pdf"}},
        {"resume": None, "skills": [], "exposure": None, "field_profile": None},
    ):
        response = client.patch(
            "/account/me", json={**payload, "user_id": owner_id, "id": owner_id}
        )
        assert response.status_code == 200
        assert response.json()["email"] == cross["other"].email
        assert owner_snapshot(db_session, cross["owner"].id) == before
    assert (
        client.post(
            "/notifications/read", json={"ids": [cross["notice"].id], "user_id": owner_id}
        ).status_code
        == 200
    )
    assert owner_snapshot(db_session, cross["owner"].id) == before
    response = client.post("/resume", json={"resume_text": "B resume", "user_id": owner_id})
    assert response.status_code == 200
    assert response.json()["version"] == 1
    assert owner_snapshot(db_session, cross["owner"].id) == before
    assert (
        client.post(
            "/saved-searches",
            json={
                "name": "B search",
                "params": {"q": "other"},
                "user_id": owner_id,
            },
        ).status_code
        == 200
    )
    response = client.post(
        "/referral/claim", json={"code": "unknown-test-code", "user_id": owner_id}
    )
    assert response.status_code == 200
    assert response.json() == {"referred": False, "reason": "unknown_code"}
    assert owner_snapshot(db_session, cross["owner"].id) == before
    assert (
        client.post(
            "/reports",
            json={
                "category": "bug",
                "message": "B report with spoofed owner",
                "user_id": owner_id,
            },
        ).status_code
        == 200
    )
    report = db_session.scalar(
        select(models.BugReport).where(
            models.BugReport.user_id == cross["other"].id,
        )
    )
    assert report.message == "B report with spoofed owner"
    assert owner_snapshot(db_session, cross["owner"].id) == before


def test_paid_features_do_not_borrow_another_users_subscription(cross, db_session) -> None:
    before = owner_snapshot(db_session, cross["owner"].id)
    response = cross["client"].post(
        "/copilot", json={"message": "Help me", "user_id": str(cross["owner"].id)}
    )
    assert response.status_code == 403
    # Test the gate separately from the enabled resume ownership tests above.
    free = db_session.scalar(select(models.Plan).where(models.Plan.key == "free"))
    free.features = {**free.features, "resume_match": False}
    db_session.flush()
    assert cross["client"].get("/resume/matches").status_code == 403
    assert cross["client"].post("/resume", json={"resume_text": "B"}).status_code == 403
    assert owner_snapshot(db_session, cross["owner"].id) == before


def test_checkout_uses_caller_and_plan_changes_remain_disabled(
    cross, db_session, monkeypatch
) -> None:
    before = owner_snapshot(db_session, cross["owner"].id)
    provider = Mock()
    provider.subscription.create.return_value = {"id": f"sub_b_{uuid.uuid4().hex}"}
    monkeypatch.setattr(payments, "_razorpay_client", lambda: provider)
    response = cross["client"].post(
        f"/payments/checkout/{cross['paid'].key}", json={"user_id": str(cross["owner"].id)}
    )
    assert response.status_code == 200
    assert provider.subscription.create.call_args.args[0]["notes"]["user_id"] == str(
        cross["other"].id
    )
    subscription = db_session.scalar(
        select(models.Subscription).where(models.Subscription.user_id == cross["other"].id)
    )
    assert subscription.razorpay_sub_id == response.json()["razorpay_subscription_id"]
    for route in ("upgrade", "switch-to-annual"):
        assert cross["client"].post(f"/payments/{route}/{cross['paid'].key}").status_code == 409
    assert owner_snapshot(db_session, cross["owner"].id) == before


def test_unsubscribe_token_cannot_target_another_users_search(cross, db_session) -> None:
    before = owner_snapshot(db_session, cross["owner"].id)
    # B's valid signature cannot authorize a write to A's saved-search ID.
    token = make_token(cross["other"].id, f"saved_search:{cross['search_id']}")
    client = cross["client"]
    assert client.post("/notifications/unsubscribe", params={"token": token}).status_code == 200
    assert owner_snapshot(db_session, cross["owner"].id) == before
    # Replacing B with A in the payload invalidates the signature.
    _, signature = token.split(".")
    payload = f"{cross['owner'].id}:saved_search:{cross['search_id']}"
    forged = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=") + "." + signature
    assert client.post("/notifications/unsubscribe", params={"token": forged}).status_code == 200
    assert owner_snapshot(db_session, cross["owner"].id) == before
    valid_owner_token = make_token(cross["owner"].id, "daily_digest")
    assert (
        client.get("/notifications/unsubscribe", params={"token": valid_owner_token}).status_code
        == 200
    )
    assert owner_snapshot(db_session, cross["owner"].id) == before


def test_unsigned_payment_webhook_cannot_change_subscription(cross, db_session) -> None:
    before = owner_snapshot(db_session, cross["owner"].id)
    response = cross["client"].post(
        "/payments/webhook",
        json={
            "event": "subscription.cancelled",
            "payload": {"subscription": {"entity": {"id": cross["subscription"].razorpay_sub_id}}},
        },
    )
    assert response.status_code == 400
    assert owner_snapshot(db_session, cross["owner"].id) == before


# Every session-authenticated method/path pair listed in the audit above.
_AUTH_ROUTES = [
    ("GET", "/bookmarks", None),
    ("POST", "/bookmarks/foreign-slug", None),
    ("PATCH", "/bookmarks/foreign-slug", {"status": "applied"}),
    ("DELETE", "/bookmarks/foreign-slug", None),
    ("GET", "/saved-searches", None),
    ("POST", "/saved-searches", {"params": {"q": "test"}}),
    ("PATCH", "/saved-searches/1", {"name": "Stolen"}),
    ("DELETE", "/saved-searches/1", None),
    ("GET", "/dream-companies", None),
    ("PUT", "/dream-companies", {"company_slugs": ["foreign"], "roles": []}),
    ("POST", "/dream-companies/foreign", None),
    ("DELETE", "/dream-companies/foreign", None),
    ("GET", "/notifications", None),
    ("GET", "/notifications/unread-count", None),
    ("POST", "/notifications/read", None),
    ("GET", "/account/me", None),
    ("PATCH", "/account/me", {"display_name": "Stolen"}),
    ("GET", "/account/export", None),
    ("POST", "/subscription/cancel", None),
    ("POST", "/resume", {"resume_text": "Private resume"}),
    ("GET", "/resume/matches", None),
    ("GET", "/referral/me", None),
    ("POST", "/referral/claim", {"code": "foreign-code"}),
    ("POST", "/payments/checkout/paid", None),
    ("POST", "/payments/upgrade/paid", None),
    (
        "POST",
        "/payments/upgrade/verify",
        {
            "razorpay_order_id": "foreign",
            "razorpay_payment_id": "foreign",
            "razorpay_signature": "invalid",
        },
    ),
    ("POST", "/payments/switch-to-annual/paid", None),
    (
        "POST",
        "/payments/switch-to-annual/verify",
        {
            "razorpay_order_id": "foreign",
            "razorpay_payment_id": "foreign",
            "razorpay_signature": "invalid",
        },
    ),
    ("POST", "/copilot", {"message": "Private question"}),
]


@pytest.mark.parametrize("method,path,payload", _AUTH_ROUTES)
def test_private_routes_require_authentication(db_session, method, path, payload) -> None:
    previous_overrides = app.dependency_overrides.copy()
    app.dependency_overrides.clear()
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        with TestClient(app) as client:
            assert client.request(method, path, json=payload).status_code == 401
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)
