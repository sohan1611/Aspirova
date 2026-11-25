"""Real local Postgres + fake Resend HTTP; never read credentials or contact Resend."""

import base64
import hashlib
import hmac
import importlib.util
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core import email_client, email_outbox as outbox, models
from core.email_budget import sent_today
from core.email_events import apply_event
from scripts.delivery_outage_drill import FakeResend, fake_settings, isolated_delivery_database

NOW = datetime(2035, 1, 2, 12, tzinfo=timezone.utc)


@pytest.fixture
def delivery_db(monkeypatch):
    url = os.environ.get("DELIVERY_TEST_DATABASE_URL", os.environ.get("DATABASE_URL", ""))
    if not url:
        pytest.skip("Set DELIVERY_TEST_DATABASE_URL to an explicit localhost test database")
    settings = fake_settings()
    monkeypatch.setattr(outbox, "get_settings", lambda: settings)
    monkeypatch.setattr(email_client, "get_settings", lambda: settings)
    fake = FakeResend()
    monkeypatch.setattr(email_client.httpx, "post", fake)
    with isolated_delivery_database(url) as engine:
        with Session(engine) as db:
            user = models.User(email="private-reader@example.test")
            db.add(user)
            db.commit()
            yield db, user, fake, settings


def send(db, user, *, identity="test", kind="digest", now=NOW):
    return outbox.send(
        db,
        email_client.send_email,
        user.email,
        "Private subject",
        "<p>Private body</p>",
        "Private body",
        user_id=user.id,
        kind=kind,
        identity=identity,
        receipts=[{"meta": {"opportunity_ids": [123]}}],
        now=now,
    )


def row(db):
    return db.scalar(select(models.EmailOutbox).execution_options(populate_existing=True))


def assert_one_sent(db, fake):
    receipts = db.scalars(
        select(models.Notification).where(models.Notification.status == "sent")
    ).all()
    assert len(receipts) == len(fake.accepted) == 1
    assert len({r.outbox_id for r in receipts}) == 1
    assert all(payload == fake.calls[0][1] for _, payload in fake.calls)
    assert len({key for key, _ in fake.calls}) == 1


@pytest.mark.parametrize(
    "failure",
    [
        503,
        httpx.ReadTimeout("fake"),
        httpx.ConnectError("reset"),
        ConnectionResetError("reset"),
        429,
        "lost",
    ],
)
def test_transient_retry_same_key_exactly_once(delivery_db, failure):
    db, user, fake, _ = delivery_db
    fake.failures = [failure]
    assert not send(db, user)
    first = row(db)
    assert first.status == "queued"
    assert first.next_attempt_at > NOW
    if failure == 429:
        assert first.next_attempt_at >= NOW + timedelta(seconds=120)
    assert sent_today(db, NOW) == 1
    assert not outbox.attempt_delivery(db, first.id, now=NOW + timedelta(seconds=1))
    assert len(fake.calls) == 1
    assert outbox.attempt_delivery(db, first.id, now=NOW + timedelta(minutes=3))
    assert send(db, user, now=NOW + timedelta(minutes=4))  # same intent, no second HTTP
    assert outbox.attempt_delivery(db, first.id, now=NOW + timedelta(minutes=5))
    assert len(fake.calls) == 2
    assert sent_today(db, NOW) == 2
    assert_one_sent(db, fake)


def test_permanent_422_is_visible_and_never_retried(delivery_db):
    db, user, fake, _ = delivery_db
    fake.failures = [422]
    assert not send(db, user)
    item = row(db)
    assert item.status == "failed" and not item.retryable
    assert item.last_code == 422 and "Invalid" in item.last_error
    assert "private@" not in item.last_error and "re_fake-secret" not in item.last_error
    assert not send(db, user, now=NOW + timedelta(hours=1))
    assert len(fake.calls) == 1 and len(fake.accepted) == 0
    assert (
        db.scalar(
            select(func.count())
            .select_from(models.Notification)
            .where(models.Notification.status == "sent")
        )
        == 0
    )


def test_worker_crash_after_acceptance_recovers_expired_lease(delivery_db, monkeypatch):
    db, user, fake, _ = delivery_db

    def crash(*args, **kwargs):
        fake(*args, **kwargs)
        raise SystemExit("fake worker death after provider accepted")

    monkeypatch.setattr(email_client.httpx, "post", crash)
    with pytest.raises(SystemExit):
        send(db, user)
    db.rollback()  # losing the process rolls back only post-lease work
    item = row(db)
    assert item.status == "sending" and item.attempts == 1
    monkeypatch.setattr(email_client.httpx, "post", fake)
    assert not outbox.attempt_delivery(db, item.id, now=NOW + timedelta(seconds=1))
    assert outbox.attempt_delivery(db, item.id, now=NOW + timedelta(minutes=6))
    assert len(fake.calls) == 2
    assert db.get(models.EmailAttempt, (item.id, 1)).outcome == "unknown"
    assert_one_sent(db, fake)


def test_budget_exhaustion_defers_without_losing_intents(delivery_db):
    db, user, fake, settings = delivery_db
    settings.email_daily_budget = 3
    settings.email_digest_reserve = 1
    for i in range(4):
        send(db, user, identity=i)
    assert len(fake.accepted) == 2
    assert outbox.status_counts(db) == {"queued": 2, "sent": 2}
    assert sent_today(db, NOW) == 2
    send(db, user, identity="reserve", kind="closing_soon")
    assert len(fake.accepted) == 3
    assert sent_today(db, NOW) == 3
    ids = list(
        db.scalars(select(models.EmailOutbox.id).where(models.EmailOutbox.status == "queued"))
    )
    for id_ in ids:
        assert outbox.attempt_delivery(db, id_, now=NOW + timedelta(days=1))
    assert len(fake.accepted) == 5
    assert (
        db.scalar(
            select(func.count())
            .select_from(models.Notification)
            .where(models.Notification.status == "sent")
        )
        == 5
    )
    assert sent_today(db, NOW + timedelta(days=1)) == 2


def test_retries_also_consume_the_budget(delivery_db):
    db, user, fake, settings = delivery_db
    settings.email_daily_budget = 2
    settings.email_digest_reserve = 0
    fake.failures = [503]
    assert not send(db, user)
    assert outbox.attempt_delivery(db, row(db).id, now=NOW + timedelta(minutes=3))
    assert not send(db, user, identity="second")
    assert sent_today(db, NOW) == 2 and len(fake.calls) == 2
    assert_one_sent(db, fake)


def test_max_attempts_dry_run_requeue_and_expired_uncertainty(delivery_db):
    db, user, fake, settings = delivery_db
    settings.email_max_attempts = 2
    fake.failures = [503, 503]
    send(db, user)
    outbox.attempt_delivery(db, row(db).id, now=NOW + timedelta(minutes=3))
    assert row(db).status == "dead"
    assert outbox.requeue_dead(db, now=NOW + timedelta(minutes=4)) == {"eligible": 1, "blocked": 0}
    assert row(db).status == "dead"  # dry run is the default
    outbox.requeue_dead(db, apply=True, now=NOW + timedelta(minutes=4))
    db.commit()
    assert outbox.attempt_delivery(db, row(db).id, now=NOW + timedelta(minutes=5))
    assert_one_sent(db, fake)

    fake.failures = ["lost"]
    send(db, user, identity="uncertain")
    uncertain = db.scalar(select(models.EmailOutbox).where(models.EmailOutbox.status == "queued"))
    assert not outbox.attempt_delivery(db, uncertain.id, now=NOW + timedelta(days=1))
    assert uncertain.status == "dead"
    assert outbox.requeue_dead(db, apply=True, now=NOW + timedelta(days=1))["blocked"] == 1
    assert len(fake.calls) == 4  # no request outside Resend's key lifetime


@pytest.mark.parametrize("event", ["bounced", "complained"])
def test_webhook_suppression_and_replay(delivery_db, event):
    db, user, fake, settings = delivery_db
    assert send(db, user)
    first = row(db)
    settings.email_daily_budget = 0
    assert not send(db, user, identity="queued")
    payload = {
        "type": "email." + event,
        "data": {
            "email_id": first.provider_id,
            "to": [user.email],
            "bounce": {"type": "Permanent"},
        },
    }
    assert apply_event(db, "verified-event", payload, now=NOW)
    db.commit()
    assert not apply_event(db, "verified-event", payload, now=NOW)
    db.commit()
    assert first.delivery_status == event
    assert db.scalar(select(func.count()).select_from(models.EmailSuppression)) == 1
    assert not send(db, user, identity="future", now=NOW + timedelta(days=1))
    assert outbox.status_counts(db) == {"failed": 1, "suppressed": 2}
    assert len(fake.calls) == 1
    assert_one_sent(db, fake)
    # An out-of-order delivered event cannot downgrade a complaint/bounce.
    payload["type"] = "email.delivered"
    apply_event(db, "late-delivered", payload, now=NOW)
    db.commit()
    assert first.delivery_status == event
    assert_one_sent(db, fake)


def test_tagged_webhook_reconciles_lost_response(delivery_db):
    db, user, fake, _ = delivery_db
    fake.failures = ["lost"]
    assert not send(db, user)
    item = row(db)
    apply_event(
        db,
        "accepted",
        {
            "type": "email.delivered",
            "data": {
                "email_id": fake.accepted[item.dedupe_key],
                "to": [user.email],
                "tags": {"outbox_key": item.dedupe_key.removeprefix("email/")},
            },
        },
        now=NOW,
    )
    db.commit()
    assert item.status == "sent" and item.delivery_status == "delivered"
    assert outbox.attempt_delivery(db, item.id, now=NOW + timedelta(minutes=3))
    assert len(fake.calls) == 1
    assert_one_sent(db, fake)


def test_overlapping_workers_do_not_double_send(delivery_db):
    db, user, fake, _ = delivery_db
    item = outbox.enqueue(
        db,
        to=user.email,
        kind="digest",
        identity="overlap",
        user_id=user.id,
        payload={"to": [user.email], "subject": "s", "text": "t"},
        receipts=[{}],
        now=NOW,
    )
    id_ = item.id
    db.commit()

    def worker(_):
        with Session(db.get_bind()) as other:
            return outbox.attempt_delivery(other, id_, now=NOW)

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(worker, range(2)))
    db.expire_all()
    assert len(fake.calls) == 1
    assert_one_sent(db, fake)


def test_signed_endpoint_admin_auth_and_public_output(delivery_db, monkeypatch):
    from api import delivery
    from api.deps import get_db
    from api.main import app

    db, user, fake, settings = delivery_db
    settings.delivery_admin_token = "fake-admin-token"
    secret = b"fake-webhook-signing-key"
    settings.resend_webhook_secret = "whsec_" + base64.b64encode(secret).decode()
    monkeypatch.setattr(delivery, "get_settings", lambda: settings)
    send(db, user)
    item = row(db)
    body = json.dumps(
        {
            "type": "email.bounced",
            "data": {
                "email_id": item.provider_id,
                "to": [user.email],
                "bounce": {"type": "Permanent"},
            },
        }
    )
    timestamp = str(int(time.time()))
    signature = base64.b64encode(
        hmac.new(secret, f"evt.{timestamp}.{body}".encode(), hashlib.sha256).digest()
    ).decode()
    app.dependency_overrides[get_db] = lambda: db
    try:
        client = TestClient(app)
        assert client.post("/email/webhook", content=body).status_code == 400
        headers = {
            "svix-id": "evt",
            "svix-timestamp": timestamp,
            "svix-signature": "v1," + signature,
        }
        assert client.post("/email/webhook", content=body, headers=headers).status_code == 200
        assert client.post("/email/webhook", content=body, headers=headers).status_code == 200
        assert client.get("/admin/delivery").status_code == 401
        response = client.get(
            "/admin/delivery", headers={"Authorization": "Bearer fake-admin-token"}
        )
        assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
        assert user.email not in response.text and "Private body" not in response.text
        assert "resend_api_key" not in response.text
        assert response.json()["suppression_count"] == 1
        assert client.get("/admin/delivery").status_code == 401
        assert client.get("/admin/delivery/view").status_code == 200
        assert_one_sent(db, fake)
    finally:
        app.dependency_overrides.clear()


def test_migration_round_trip(delivery_db):
    db, *_ = delivery_db
    path = Path(__file__).parents[1] / "migrations/versions/ab6c9d2e4f71_email_delivery_outbox.py"
    spec = importlib.util.spec_from_file_location("outbox_migration_test", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with db.get_bind().begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
            migration.upgrade()
    assert outbox.status_counts(db) == {}


def test_drill_refuses_remote_database():
    with pytest.raises(ValueError, match="localhost"):
        with isolated_delivery_database("postgresql+psycopg://fake:fake@remote.invalid/prod"):
            pytest.fail("Remote database must never be opened")


def test_quota_reservations_survive_personal_payload_purge(delivery_db):
    from sqlalchemy import delete

    db, user, fake, settings = delivery_db
    settings.email_daily_budget = 1
    settings.email_digest_reserve = 0
    assert send(db, user)
    db.execute(delete(models.EmailOutbox))  # account deletion cascades receipt/attempt PII
    db.commit()
    assert sent_today(db, NOW) == 1
    assert not send(db, user, identity="after-purge")
    assert len(fake.calls) == 1


def test_acceptance_commit_lost_replays_without_duplicate(delivery_db, monkeypatch):
    db, user, fake, _ = delivery_db
    commit = db.commit
    count = 0

    def fail_acceptance_commit():
        nonlocal count
        count += 1
        if count == 3:
            raise RuntimeError("fake DB failure after provider accepted")
        commit()

    monkeypatch.setattr(db, "commit", fail_acceptance_commit)
    with pytest.raises(RuntimeError):
        send(db, user)
    db.rollback()
    monkeypatch.setattr(db, "commit", commit)
    item = row(db)
    assert item.status == "sending"
    assert outbox.attempt_delivery(db, item.id, now=NOW + timedelta(minutes=6))
    assert_one_sent(db, fake)


def test_next_run_automatically_drains_transient_failures(delivery_db):
    db, user, fake, _ = delivery_db
    fake.failures = [503]
    assert not send(db, user)
    assert outbox.drain(db, now=NOW + timedelta(minutes=3)) == {"sent": 1}
    assert outbox.drain(db, now=NOW + timedelta(minutes=4)) == {"sent": 1}
    assert len(fake.calls) == 2
    assert_one_sent(db, fake)


def test_concurrent_workers_share_global_budget(delivery_db):
    db, user, fake, settings = delivery_db
    settings.email_daily_budget = 1
    settings.email_digest_reserve = 0
    other_user = models.User(email="another-private-reader@example.test")
    db.add(other_user)
    db.commit()
    ids = []
    for reader in (user, other_user):
        intent = outbox.enqueue(
            db,
            to=reader.email,
            kind="digest",
            identity="concurrent-budget",
            user_id=reader.id,
            payload={"to": [reader.email], "subject": "s", "text": "t"},
            receipts=[{}],
            now=NOW,
        )
        ids.append(intent.id)
    db.commit()

    def worker(id_):
        with Session(db.get_bind()) as session:
            return outbox.attempt_delivery(session, id_, now=NOW)

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(worker, ids))
    db.expire_all()
    assert sent_today(db, NOW) == 1
    assert outbox.status_counts(db) == {"sent": 1, "queued": 1}
    assert len(fake.calls) == 1
    # Different envelopes intentionally have different keys, one accepted only.
    assert (
        db.scalar(
            select(func.count())
            .select_from(models.Notification)
            .where(models.Notification.status == "sent")
        )
        == len(fake.accepted)
        == 1
    )


def test_http_date_retry_after_is_respected():
    assert outbox.backoff(1, "Tue, 02 Jan 2035 12:10:00 GMT", NOW) >= timedelta(minutes=10)


def test_unknown_async_failure_is_visible_without_resubmitting(delivery_db):
    db, user, fake, _ = delivery_db
    assert send(db, user)
    item = row(db)
    apply_event(
        db,
        "async-failed",
        {
            "type": "email.failed",
            "data": {
                "email_id": item.provider_id,
                "to": [user.email],
            },
        },
        now=NOW,
    )
    db.commit()
    assert item.status == "failed" and not item.retryable
    assert not outbox.attempt_delivery(db, item.id, now=NOW + timedelta(minutes=3))
    assert len(fake.calls) == 1
    assert_one_sent(db, fake)


def test_drill_rejects_connection_overrides():
    with pytest.raises(ValueError, match="overrides"):
        with isolated_delivery_database(
            "postgresql+psycopg://fake:fake@localhost/fake_test?host=remote.invalid"
        ):
            pytest.fail("Connection override must never be opened")


def test_recovery_and_webhooks_do_not_skip_saved_search_window(delivery_db):
    db, user, fake, _ = delivery_db
    search = models.SavedSearch(
        user_id=user.id,
        params={},
        alerts_enabled=True,
        created_at=NOW - timedelta(days=2),
        last_alerted_at=NOW - timedelta(days=1),
    )
    db.add(search)
    db.commit()
    fake.failures = [503]
    assert not outbox.send(
        db,
        email_client.send_email,
        user.email,
        "Matches",
        "",
        "Original matches",
        user_id=user.id,
        kind="saved_search_alert",
        identity="original-search-window",
        receipts=[{}],
        effects={"saved_search_id": search.id, "saved_search_cutoff": NOW.isoformat()},
        now=NOW,
    )
    assert search.last_alerted_at == NOW - timedelta(days=1)
    assert outbox.attempt_delivery(db, row(db).id, now=NOW + timedelta(hours=2))
    assert search.last_alerted_at == NOW
    item = row(db)
    for i, event in enumerate(("delivered", "bounced")):
        apply_event(
            db,
            f"search-event-{i}",
            {
                "type": "email." + event,
                "data": {
                    "email_id": item.provider_id,
                    "to": [user.email],
                    "bounce": {"type": "Permanent"},
                },
            },
            now=NOW + timedelta(days=i + 1),
        )
        db.commit()
        assert search.last_alerted_at == NOW
    assert_one_sent(db, fake)


def test_opt_out_before_retry_prevents_future_http(delivery_db):
    db, user, fake, _ = delivery_db
    fake.failures = [503]
    assert not send(db, user)
    user.notification_prefs = {"daily_digest": False}
    db.commit()
    assert outbox.drain(db, now=NOW + timedelta(minutes=3)) == {"suppressed": 1}
    assert len(fake.calls) == 1 and len(fake.accepted) == 0
    assert (
        db.scalar(
            select(func.count())
            .select_from(models.Notification)
            .where(models.Notification.status == "sent")
        )
        == 0
    )
