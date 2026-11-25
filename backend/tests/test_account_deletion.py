"""Account purge integration tests. Run only on a migrated throwaway database.

All outbound transports are blocked; Supabase, Resend and Razorpay are mocked.
The shared conftest engine is bound to a rollback-only outer transaction.
"""

import base64
import json
import time
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, with_loader_criteria

import api.account as account
import api.auth as auth
import api.payments as payments
import core.account_deletion as deletion
import pipeline.notifications as notifications
import pipeline.saved_search_alerts as searches
import pipeline.weekly_report as weekly
from api.deps import get_db
from api.main import app
from core import email_outbox, models
from core.config import get_settings
from scripts.finish_account_deletions import finish_account_deletions


@pytest.fixture
def db_session(engine):
    with engine.connect() as connection:
        transaction = connection.begin()
        with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
            yield session
        transaction.rollback()


@pytest.fixture(autouse=True)
def outbound(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Unmocked outbound HTTP")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", blocked)
    monkeypatch.setattr("resend.Emails.send", blocked)
    monkeypatch.setattr("razorpay.Client", blocked)
    monkeypatch.setattr(account, "get_redis", lambda: None)
    settings = get_settings()
    monkeypatch.setattr(settings, "supabase_url", "https://supabase.example.test")
    monkeypatch.setattr(settings, "supabase_service_key", "test-service-key")
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setattr("core.unsubscribe._signing_key", lambda: b"deletion-test-key")
    mail = MagicMock(return_value=True)
    monkeypatch.setattr(account, "send_email", mail)
    monkeypatch.setattr(notifications, "send_email", mail)
    monkeypatch.setattr(searches, "send_email", mail)
    monkeypatch.setattr(weekly, "send_email", mail)
    monkeypatch.setattr(payments, "send_email", mail)
    return mail


@pytest.fixture
def user(db_session):
    user = models.User(
        email=f"delete-{uuid.uuid4()}@example.test",
        display_name="Personal name",
        college="Personal college",
        graduation_year=2030,
        invite_code=uuid.uuid4().hex[:8],
        notification_prefs={"daily_digest": True},
        field_profile={"country": "IN", "fields": ["engineering"]},
        skills=[{"name": "Python", "source": "manual"}],
        exposure={"experience": "student"},
        resume={"filename": "personal.pdf"},
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def client(db_session, user, monkeypatch):
    # A successful /user response models a still-valid, Supabase-verified JWT.
    # Requests exercise the real auth guard and first-request mirroring code.
    payload = {
        "id": str(user.id),
        "email": user.email,
        "user_metadata": {"full_name": "Do not refill"},
    }
    monkeypatch.setattr(
        auth, "_get_supabase_user", lambda *a, **k: httpx.Response(200, json=payload)
    )
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)


def bearer(issued=None, **claims):
    payload = {"iat": int(time.time()) if issued is None else issued}
    payload.update(claims)
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return {"Authorization": f"Bearer header.{encoded}.verified-by-mock"}


def admin_mock(monkeypatch, handler):
    monkeypatch.setattr(
        deletion,
        "_admin_client",
        lambda: httpx.Client(
            base_url="https://supabase.example.test",
            transport=httpx.MockTransport(handler),
            headers={"Authorization": "Bearer test-service-key", "apikey": "test-service-key"},
        ),
    )


@pytest.fixture
def external_calls(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path.endswith("/list/resumes"):
            return httpx.Response(200, json=[{"id": "file-id", "name": "resume.pdf"}])
        return httpx.Response(200, json={})

    admin_mock(monkeypatch, handler)
    return calls


def seed_owned(db, user):
    suffix = uuid.uuid4().hex
    other = models.User(email=f"survivor-{suffix}@example.test")
    company = models.Company(slug=f"delete-{suffix}", name="Deletion fixture")
    programme = models.Programme(
        slug=f"delete-{suffix}",
        name="Research",
        organiser="Institute",
        category="research_internship",
        url="https://example.test",
    )
    plan = models.Plan(key=f"delete-{suffix}", price_paise=4900, billing="monthly", features={})
    db.add_all([other, company, programme, plan])
    db.flush()
    user.referred_by = other.id
    other.referred_by = user.id
    opportunity = models.Opportunity(
        slug=f"delete-{suffix}",
        company_id=company.id,
        title="Student role",
        apply_url="https://example.test",
        category="internship",
    )
    db.add(opportunity)
    db.flush()
    subscription = models.Subscription(
        user_id=user.id,
        plan_id=plan.id,
        status="active",
        cancel_at_period_end=True,
        razorpay_sub_id=f"sub_{suffix}",
    )
    db.add(subscription)
    db.flush()
    upgrade = models.SubscriptionUpgrade(
        user_id=user.id,
        subscription_id=subscription.id,
        from_plan_id=plan.id,
        to_plan_id=plan.id,
        amount_paise=100,
        status="paid",
    )
    db.add(upgrade)
    rows = [
        models.Notification(user_id=user.id, type="digest", status="sent"),
        models.ProgrammeWatch(user_id=user.id, programme_id=programme.id),
        models.SavedSearch(user_id=user.id, params={"q": "Python"}),
        models.Bookmark(user_id=user.id, opportunity_id=opportunity.id, status="applied"),
        models.DreamCompany(user_id=user.id, company_id=company.id),
        models.ResumeProfile(
            user_id=user.id, version=1, embedding=[0.1] * 1536, embedding_model="test"
        ),
        models.BugReport(
            user_id=user.id, category="other", message="Personal text", contact_email=user.email
        ),
    ]
    email_outbox.enqueue(
        db,
        to=user.email,
        user_id=user.id,
        kind="digest",
        identity=suffix,
        payload={"to": [user.email], "subject": "Private", "text": "Private"},
        now=datetime.now(UTC),
    )
    db.add_all(rows)
    # Unrelated data must survive the purge.
    db.add(models.SavedSearch(user_id=other.id, params={"q": "unrelated"}))
    db.commit()
    return other, subscription, upgrade


def test_purge_all_owned_data_and_keep_billing(client, db_session, user, outbound, external_calls):
    other, subscription, upgrade = seed_owned(db_session, user)
    user_id, email = user.id, user.email
    billing_before = {
        column.name: getattr(subscription, column.name)
        for column in models.Subscription.__table__.columns
    }
    upgrade_before = {
        column.name: getattr(upgrade, column.name)
        for column in models.SubscriptionUpgrade.__table__.columns
    }
    original_send = outbound.side_effect

    def confirmation_after_wipe(*args, **kwargs):
        assert args[0] == email
        assert user.email is None
        assert user.deleted_at is not None
        return True

    outbound.side_effect = confirmation_after_wipe
    response = client.post("/account/delete", headers=bearer(), json={"confirm": "DELETE"})
    outbound.side_effect = original_send
    assert response.status_code == 200
    assert response.json() == {"status": "deleted"}
    db_session.refresh(user)
    assert user.deleted_at is not None
    assert user.deletion_pending == []
    for column in deletion.PERSONAL_COLUMNS:
        assert getattr(user, column) is None, column
    for model in deletion.OWNED_MODELS:
        assert (
            db_session.scalar(
                select(func.count()).select_from(model).where(model.user_id == user_id)
            )
            == 0
        )
    db_session.refresh(other)
    assert other.referred_by is None
    assert other.email is not None
    assert db_session.scalar(
        select(models.SavedSearch.id).where(models.SavedSearch.user_id == other.id)
    )
    db_session.refresh(subscription)
    db_session.refresh(upgrade)
    assert {
        c.name: getattr(subscription, c.name) for c in models.Subscription.__table__.columns
    } == billing_before
    assert {
        c.name: getattr(upgrade, c.name) for c in models.SubscriptionUpgrade.__table__.columns
    } == upgrade_before
    outbound.assert_called_once()
    assert outbound.call_args.args[1] == "Your Aspirova account has been deleted"
    assert outbound.call_args.args[2] == ""  # Plain transactional mail only.
    assert [r.method for r in external_calls] == ["POST", "DELETE", "DELETE"]
    assert json.loads(external_calls[0].content)["prefix"] == str(user_id)
    assert json.loads(external_calls[1].content) == {"prefixes": [f"{user_id}/resume.pdf"]}
    assert external_calls[2].url.path == f"/auth/v1/admin/users/{user_id}"
    for request in external_calls:
        assert request.headers["Authorization"] == "Bearer test-service-key"
        assert request.headers["apikey"] == "test-service-key"


def test_all_user_foreign_keys_are_classified():
    # A future user-owned table must extend the purge and its integration fixture.
    references = {
        table.name
        for table in models.Base.metadata.tables.values()
        if any(fk.target_fullname == "users.id" for fk in table.foreign_keys)
    }
    assert references == {
        "users",
        "subscriptions",
        "subscription_upgrades",
        *(model.__tablename__ for model in deletion.OWNED_MODELS),
    }
    assert {c.name for c in models.User.__table__.columns} == {
        "id",
        "created_at",
        "deleted_at",
        "deletion_pending",
        *deletion.PERSONAL_COLUMNS,
    }


@pytest.mark.parametrize(
    "path", ["/account/me", "/bookmarks", "/saved-searches", "/account/export"]
)
def test_tombstone_rejects_verified_token_without_mirroring(client, db_session, user, path):
    user.email = None
    user.display_name = None
    user.deleted_at = datetime.now(UTC)
    db_session.commit()
    response = client.get(path, headers=bearer())
    assert response.status_code == 401
    assert response.json() == {"detail": "account_deleted"}
    db_session.refresh(user)
    assert user.email is None
    assert user.display_name is None
    assert (
        db_session.scalar(
            select(func.count()).select_from(models.User).where(models.User.id == user.id)
        )
        == 1
    )


def test_guard_wins_for_repeated_delete(client, db_session, user, external_calls, outbound):
    assert (
        client.post("/account/delete", headers=bearer(), json={"confirm": "DELETE"}).status_code
        == 200
    )
    again = client.post("/account/delete", headers=bearer(), json={"confirm": "DELETE"})
    assert again.status_code == 401
    assert again.json() == {"detail": "account_deleted"}
    assert deletion.tombstone_account(db_session, user.id) is None
    db_session.commit()
    assert len(external_calls) == 3
    outbound.assert_called_once()


@pytest.mark.parametrize("status", ["active", "trialing"])
@pytest.mark.parametrize("cancel_at_end", [False, True])
def test_subscription_policy(
    client, db_session, user, external_calls, outbound, status, cancel_at_end
):
    _, subscription, _ = seed_owned(db_session, user)
    subscription.status = status
    subscription.cancel_at_period_end = cancel_at_end
    db_session.commit()
    response = client.post("/account/delete", headers=bearer(), json={"confirm": "DELETE"})
    assert response.status_code == (200 if cancel_at_end else 409)
    db_session.refresh(user)
    if not cancel_at_end:
        assert response.json() == {"detail": "active_subscription"}
        assert user.deleted_at is None and user.email
        outbound.assert_not_called()
        assert external_calls == []


@pytest.mark.parametrize("status", ["active", "trialing"])
@pytest.mark.parametrize("kind", ["complimentary", "expired"])
def test_nonrenewing_subscription_does_not_block_deletion(
    client, db_session, user, external_calls, outbound, status, kind
):
    _, subscription, _ = seed_owned(db_session, user)
    subscription.status = status
    subscription.cancel_at_period_end = False
    if kind == "complimentary":
        subscription.razorpay_sub_id = None
        subscription.current_period_end = datetime.now(UTC) + timedelta(days=30)
    else:
        subscription.current_period_end = datetime.now(UTC) - timedelta(
            days=get_settings().subscription_grace_days + 1
        )
    db_session.commit()
    subscription_id = subscription.id
    response = client.post("/account/delete", headers=bearer(), json={"confirm": "DELETE"})
    assert response.status_code == 200
    assert response.json() == {"status": "deleted"}
    db_session.refresh(user)
    db_session.refresh(subscription)
    assert user.deleted_at is not None
    assert subscription.id == subscription_id
    assert subscription.status == status
    assert subscription.cancel_at_period_end is False
    outbound.assert_called_once()
    assert len(external_calls) == 3


@pytest.mark.parametrize(
    ("iat_age", "amr_ages", "expected"),
    [
        (0, [601], 403),  # Refresh must not renew an old sign-in.
        (3600, [0], 200),  # Fresh AMR takes precedence over old iat.
        (0, None, 200),  # Legacy token without AMR uses iat.
        (3600, [3600, 0], 200),  # Use the newest usable AMR timestamp.
        (0, [True, "invalid", None], 200),  # No usable AMR: fall back to iat.
        (0, [601, True, "invalid"], 403),  # Ignore invalid entries, not old AMR.
    ],
)
def test_signin_freshness_uses_amr_before_iat(
    client, db_session, user, external_calls, outbound, iat_age, amr_ages, expected
):
    now = int(time.time())
    claims = {}
    if amr_ages is not None:
        claims["amr"] = [
            {
                "method": "password",
                "timestamp": (
                    now - age if isinstance(age, int) and not isinstance(age, bool) else age
                ),
            }
            for age in amr_ages
        ]
    response = client.post(
        "/account/delete", headers=bearer(now - iat_age, **claims), json={"confirm": "DELETE"}
    )
    assert response.status_code == expected
    db_session.refresh(user)
    if expected == 403:
        assert response.json() == {"detail": "reauth_required"}
        assert user.deleted_at is None
        outbound.assert_not_called()
        assert external_calls == []
    else:
        assert response.json() == {"status": "deleted"}
        assert user.deleted_at is not None
        outbound.assert_called_once()


@pytest.mark.parametrize("age", [601, 3600])
def test_old_token_requires_reauthentication(client, user, outbound, age):
    response = client.post(
        "/account/delete", headers=bearer(int(time.time()) - age), json={"confirm": "DELETE"}
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "reauth_required"}
    assert user.deleted_at is None
    outbound.assert_not_called()


@pytest.mark.parametrize(
    "body",
    [{"confirm": "delete"}, {"confirm": " DELETE"}, {"confirm": "DELETE "}, {}, {"confirm": 1}],
)
def test_confirmation_is_exact(client, body, outbound):
    assert client.post("/account/delete", headers=bearer(), json=body).status_code == 422
    outbound.assert_not_called()


@pytest.mark.parametrize("payload", [{}, {"iat": "1"}, {"iat": True}, {"iat": 9_999_999_999}])
def test_invalid_freshness_claims(client, payload):
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    response = client.post(
        "/account/delete",
        headers={"Authorization": f"Bearer h.{encoded}.s"},
        json={"confirm": "DELETE"},
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "reauth_required"}


def test_delete_rate_limit(client, monkeypatch):
    from core.ratelimit import RateLimitResult

    async def denied(*args, **kwargs):
        assert kwargs["bucket"] == "account_delete"
        assert kwargs["max_requests"] == 5
        return RateLimitResult(allowed=False, retry_after_seconds=30)

    monkeypatch.setattr(account, "check_rate_limit", denied)
    response = client.post("/account/delete", headers=bearer(), json={"confirm": "DELETE"})
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "30"


def test_delete_requires_authentication(client, outbound):
    assert client.post("/account/delete", json={"confirm": "DELETE"}).status_code == 401
    outbound.assert_not_called()


@pytest.mark.parametrize("failed_step", ["storage_list", "storage_delete", "auth"])
def test_cleanup_failure_is_durable_and_script_retries(
    client, db_session, user, monkeypatch, failed_step
):
    fail = True
    calls = []

    def handler(request):
        calls.append(request)
        is_storage = request.url.path.startswith("/storage/")
        if fail and (
            (failed_step == "storage_list" and is_storage and request.method == "POST")
            or (failed_step == "storage_delete" and is_storage and request.method == "DELETE")
            or (failed_step == "auth" and not is_storage)
        ):
            return httpx.Response(503)
        if request.method == "POST":
            return httpx.Response(200, json=[{"id": "resume", "name": "resume.pdf"}])
        # Missing object / missing auth identity are both idempotent success.
        return httpx.Response(404)

    admin_mock(monkeypatch, handler)
    response = client.post("/account/delete", headers=bearer(), json={"confirm": "DELETE"})
    assert response.status_code == 200
    db_session.refresh(user)
    assert user.deleted_at is not None and user.email is None
    assert user.deletion_pending == (
        ["storage", "auth"] if failed_step.startswith("storage") else ["auth"]
    )
    calls.clear()
    fail = False
    assert finish_account_deletions(db_session) == 0
    db_session.refresh(user)
    assert user.deletion_pending == []
    if failed_step == "auth":
        assert len(calls) == 1  # Completed Storage step is not repeated.
    calls.clear()
    assert finish_account_deletions(db_session) == 0
    assert calls == []


def test_email_failure_does_not_block_purge(client, db_session, user, outbound, external_calls):
    outbound.side_effect = RuntimeError("mail unavailable")
    assert (
        client.post("/account/delete", headers=bearer(), json={"confirm": "DELETE"}).status_code
        == 200
    )
    db_session.refresh(user)
    assert user.deleted_at is not None and user.email is None


def test_database_failure_rolls_back_without_external_cleanup(
    client, db_session, user, monkeypatch, external_calls, outbound
):
    seed_owned(db_session, user)
    original_flush = db_session.flush

    def fail_flush(*args, **kwargs):
        # Read the loaded value directly: attribute access can autoflush and
        # re-enter this patched flush.
        if user.__dict__.get("deleted_at") is not None:
            raise RuntimeError("purge failed")
        return original_flush(*args, **kwargs)

    monkeypatch.setattr(db_session, "flush", fail_flush)
    with pytest.raises(RuntimeError, match="purge failed"):
        client.post("/account/delete", headers=bearer(), json={"confirm": "DELETE"})
    monkeypatch.setattr(db_session, "flush", original_flush)
    db_session.refresh(user)
    assert user.deleted_at is None and user.email
    for model in deletion.OWNED_MODELS:
        assert (
            db_session.scalar(
                select(func.count()).select_from(model).where(model.user_id == user.id)
            )
            == 1
        )
    assert external_calls == []
    outbound.assert_not_called()


def test_commit_failure_sends_no_confirmation_or_external_cleanup(
    client, db_session, user, monkeypatch, external_calls, outbound
):
    seed_owned(db_session, user)

    def fail_commit():
        raise RuntimeError("commit failed")

    monkeypatch.setattr(db_session, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="commit failed"):
        client.post("/account/delete", headers=bearer(), json={"confirm": "DELETE"})
    db_session.refresh(user)
    assert user.deleted_at is None and user.email
    outbound.assert_not_called()
    assert external_calls == []


@pytest.mark.parametrize(
    "sender", ["daily", "company", "instant", "closing", "saved", "weekly", "programme", "billing"]
)
@pytest.mark.parametrize("suppression", ["tombstone", "missing_email"])
def test_each_sender_excludes_tombstones_at_query_level(
    db_session, user, monkeypatch, outbound, sender, suppression
):
    # Keep a deliberate residual email and owned rows to ensure suppression is
    # from the SQL predicate, not just a side effect of the purge setting NULL.
    _, subscription, _ = seed_owned(db_session, user)
    if suppression == "tombstone":
        user.deleted_at = datetime.now(UTC)
    else:
        user.email = None
    db_session.commit()
    from core.mail_recipients import recipient_filters

    assert (
        db_session.scalar(
            select(models.User.id).where(models.User.id == user.id, *recipient_filters())
        )
        is None
    )

    # Assert no per-user work starts. Programme notices share the daily sender.
    def no_recipient(*args, **kwargs):
        raise AssertionError("A tombstone reached per-recipient work")

    monkeypatch.setattr(notifications, "can", no_recipient)
    monkeypatch.setattr(notifications, "collect_programme_watch_changes", no_recipient)
    monkeypatch.setattr(notifications, "wants", no_recipient)
    monkeypatch.setattr(weekly, "can", no_recipient)
    monkeypatch.setattr(searches, "saved_search_base_filters", no_recipient)
    senders = {
        "daily": notifications.send_daily_digests,
        "company": notifications.send_company_alerts,
        "instant": notifications.send_instant_alerts,
        "closing": notifications.send_closing_soon_alerts,
        "saved": searches.send_saved_search_alerts,
        "weekly": weekly.send_weekly_reports,
        "programme": notifications.send_daily_digests,
    }
    # Restrict fixture DB rows to the target by observing query results, rather
    # than relying on the throwaway database having no pre-existing users.
    from sqlalchemy import event

    seen_queries = []
    user_id = user.id

    def capture(orm_state):
        if orm_state.is_select:
            statement = orm_state.statement
            if "users.deleted_at" in str(statement):
                seen_queries.append(str(statement))
            orm_state.statement = statement.options(
                with_loader_criteria(models.User, models.User.id == user_id)
            )

    event.listen(db_session, "do_orm_execute", capture)
    try:
        if sender == "billing":
            payments._send_subscription_status_email(db_session, subscription, "active")
        else:
            senders[sender](db_session, now=datetime.now(UTC) + timedelta(days=1))
    finally:
        event.remove(db_session, "do_orm_execute", capture)
    assert seen_queries
    assert all(
        "users.deleted_at IS NULL" in query and "users.email IS NOT NULL" in query
        for query in seen_queries
    )
    assert not any(call.args[0] == user.email for call in outbound.call_args_list)


def test_admin_client_uses_server_service_key():
    # Constructing an HTTP client makes no requests.
    with deletion._admin_client() as client:
        assert str(client.base_url).rstrip("/") == "https://supabase.example.test"
        assert client.headers["Authorization"] == "Bearer test-service-key"
        assert client.headers["apikey"] == "test-service-key"


def test_guard_refreshes_a_stale_identity_map(client, db_session, user):
    db_session.execute(
        update(models.User)
        .where(models.User.id == user.id)
        .values(email=None, display_name=None, deleted_at=datetime.now(UTC))
        .execution_options(synchronize_session=False)
    )
    # The in-memory ORM instance is still live-looking; authentication must
    # reload the row under the lock instead of trusting this cached instance.
    assert user.deleted_at is None
    response = client.get("/account/me", headers=bearer())
    assert response.status_code == 401
    assert response.json() == {"detail": "account_deleted"}
    assert user.email is None and user.display_name is None


def test_missing_admin_config_keeps_retry_marker(client, db_session, user, monkeypatch):
    monkeypatch.setattr(get_settings(), "supabase_service_key", "")
    response = client.post("/account/delete", headers=bearer(), json={"confirm": "DELETE"})
    assert response.status_code == 200
    db_session.refresh(user)
    assert user.deletion_pending == ["storage", "auth"]
    assert finish_account_deletions(db_session) == 1


def test_referral_code_cannot_relink_a_tombstone(db_session, user):
    from core.referral import resolve_code

    code = user.invite_code
    user.deleted_at = datetime.now(UTC)
    db_session.commit()
    # Even a residual code on a tombstone cannot award a new referral.
    assert resolve_code(db_session, code) is None


def test_cleanup_is_after_commit(client, db_session, user, monkeypatch, outbound):
    committed = []
    original_commit = db_session.commit

    def commit():
        original_commit()
        committed.append(True)

    def cleanup(db, user_id):
        assert committed
        db.refresh(user)
        assert user.id == user_id
        assert user.deleted_at is not None and user.email is None
        assert user.deletion_pending == ["storage", "auth"]
        raise RuntimeError("unexpected cleanup failure")

    def confirmation_after_commit(*args, **kwargs):
        assert committed
        assert user.email is None
        assert user.deleted_at is not None
        return True

    monkeypatch.setattr(db_session, "commit", commit)
    monkeypatch.setattr(account, "finish_external_cleanup", cleanup)
    outbound.side_effect = confirmation_after_commit
    response = client.post("/account/delete", headers=bearer(), json={"confirm": "DELETE"})
    assert response.status_code == 200
    db_session.refresh(user)
    assert user.deletion_pending == ["storage", "auth"]
    outbound.assert_called_once()


def test_storage_cleanup_paginates_and_recurses(monkeypatch):
    user_id = uuid.uuid4()
    removed = []
    listings = []

    def handler(request):
        body = json.loads(request.content)
        if request.method == "DELETE":
            removed.extend(body["prefixes"])
            return httpx.Response(200, json=[])
        folder, offset = body["prefix"], body["offset"]
        listings.append((folder, offset))
        if folder == str(user_id) and offset == 0:
            return httpx.Response(
                200,
                json=[{"id": None, "name": "nested"}]
                + [{"id": str(i), "name": f"old-{i}.pdf"} for i in range(99)],
            )
        if folder == str(user_id):
            return httpx.Response(200, json=[{"id": "current", "name": "resume.pdf"}])
        return httpx.Response(200, json=[{"id": "nested", "name": "extra.pdf"}])

    admin_mock(monkeypatch, handler)
    with deletion._admin_client() as client:
        deletion._delete_resume_folder(client, user_id)
    assert (str(user_id), 100) in listings
    assert f"{user_id}/nested/extra.pdf" in removed
    assert f"{user_id}/resume.pdf" in removed
    assert len(removed) == 101
    assert all(path.startswith(f"{user_id}/") for path in removed)
