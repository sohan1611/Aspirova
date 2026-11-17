"""ALERT-07: last-send category totals and a public, non-personal sample."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from api import digest
from api.auth import get_current_user
from api.deps import get_db
from api.main import app
from api.middleware import _cache_ttl_seconds
from core import models, ratelimit
from core.config import get_settings
from pipeline import notifications as worker

NOW = datetime(2031, 4, 1, 12, tzinfo=timezone.utc)


class FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW


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
def seeded(db_session, monkeypatch):
    suffix = uuid.uuid4().hex
    user = models.User(email=f"digest-api-{suffix}@example.com", display_name="Private reader")
    other = models.User(email=f"digest-other-{suffix}@example.com")
    company = models.Company(slug=f"digest-api-{suffix}", name="Example company")
    listings = [
        models.Opportunity(
            slug=f"digest-api-{suffix}-{index}",
            company=company,
            title=f"Real listing {index}",
            category=category,
            apply_url="https://example.com/apply",
            first_seen_at=NOW - timedelta(hours=1),
            last_seen_at=NOW,
            deadline=NOW + timedelta(days=10),
            deadline_confidence="explicit",
        )
        for index, category in enumerate(("internship", "job", "hackathon"))
    ]
    db_session.add_all([user, other, company, *listings])
    plan = db_session.scalar(select(models.Plan).where(models.Plan.key == "free"))
    if plan is None:
        plan = models.Plan(key="free", price_paise=0, features={})
        db_session.add(plan)
    plan.features = {**(plan.features or {}), "daily_digest": True}
    db_session.flush()

    monkeypatch.setattr(digest, "datetime", FrozenDateTime)
    monkeypatch.setattr(ratelimit, "_now", lambda: 1_000_010.0)
    monkeypatch.setattr(get_settings(), "rate_limit_backend", "memory")
    monkeypatch.setattr(get_settings(), "read_cache_l2_enabled", False)
    monkeypatch.setattr(worker, "_generic_recent_opportunities", lambda *args: listings[:2])
    monkeypatch.setattr(worker, "_hackathon_digest_opportunities", lambda *args: listings[2:])
    monkeypatch.setattr("core.unsubscribe._signing_key", lambda: b"digest-api-test-key")
    send = Mock(side_effect=AssertionError("A read endpoint must never send email"))
    collect = Mock(side_effect=AssertionError("A read endpoint must never collect watch changes"))
    monkeypatch.setattr(worker, "send_email", send)
    monkeypatch.setattr(worker, "collect_programme_watch_changes", collect)
    return {
        "user": user,
        "other": other,
        "listings": listings,
        "plan": plan,
        "send": send,
        "collect": collect,
    }


@pytest.fixture
def client(db_session, seeded):
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: seeded["user"]
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)


def _attempt(db, user, *, status="sent", sent_at=NOW, meta=None, kind="digest"):
    row = models.Notification(user_id=user.id, type=kind, status=status, sent_at=sent_at, meta=meta)
    db.add(row)
    db.flush()
    return row


def test_account_digest_status_is_null_without_ledger(client):
    assert client.get("/account/me").json()["digest_status"] is None


def test_account_digest_counts_categories_removed_and_programmes(client, db_session, seeded):
    listings = seeded["listings"]
    removed = models.Opportunity(
        slug=f"removed-{uuid.uuid4().hex}",
        title="Removed",
        category="job",
        apply_url="https://example.com",
    )
    db_session.add(removed)
    db_session.flush()
    removed_id = removed.id
    db_session.delete(removed)
    db_session.flush()
    _attempt(
        db_session,
        seeded["user"],
        meta={
            "opportunity_ids": [listings[0].id, listings[1].id, removed_id],
            "hackathon_ids": [listings[2].id],
            "programme_slugs": ["research-programme", "fellowship-programme"],
        },
    )
    status = client.get("/account/me").json()["digest_status"]
    assert status["last_sent_counts_by_category"] == {
        "internship": 1,
        "job": 1,
        "removed": 1,
        "hackathon": 1,
        "programme_update": 2,
    }
    assert status["last_sent_count"] == 4  # Existing count still excludes programme entries.
    assert status["last_sent_at"] == "2031-04-01T12:00:00Z"
    assert status["last_attempt_failed"] is False


def test_new_failed_attempt_keeps_last_sent_counts(client, db_session, seeded):
    user, listings = seeded["user"], seeded["listings"]
    _attempt(
        db_session,
        user,
        sent_at=NOW - timedelta(days=1),
        meta={"opportunity_ids": [listings[1].id]},
    )
    _attempt(
        db_session,
        user,
        meta={"opportunity_ids": [listings[0].id], "programme_slugs": ["programme"]},
    )
    before = client.get("/account/me").json()["digest_status"]
    assert before["last_sent_counts_by_category"] == {"internship": 1, "programme_update": 1}
    _attempt(
        db_session,
        user,
        status="failed",
        sent_at=None,
        meta={
            "opportunity_ids": [listings[1].id],
            "hackathon_ids": [listings[2].id],
        },
    )
    _attempt(db_session, seeded["other"], meta={"hackathon_ids": [listings[2].id]})
    _attempt(db_session, user, kind="weekly_report")
    after = client.get("/account/me").json()["digest_status"]
    assert after == {**before, "last_attempt_failed": True}


def test_legacy_sent_row_has_no_category_breakdown(client, db_session, seeded):
    _attempt(db_session, seeded["user"], meta=None)
    status = client.get("/account/me").json()["digest_status"]
    assert status["last_sent_counts_by_category"] == {}
    assert status["last_sent_count"] == 0 and status["last_attempt_failed"] is False


def test_failed_without_sent_digest_has_empty_counts(client, db_session, seeded):
    _attempt(
        db_session,
        seeded["user"],
        status="failed",
        sent_at=None,
        meta={"opportunity_ids": [seeded["listings"][0].id]},
    )
    status = client.get("/account/me").json()["digest_status"]
    assert status == {
        "last_sent_at": None,
        "last_sent_count": 0,
        "last_attempt_failed": True,
        "last_sent_counts_by_category": {},
    }


def test_public_sample_has_no_user_lookup_or_personal_fields_and_is_cached(
    client, db_session, seeded
):
    app.dependency_overrides[get_current_user] = lambda: pytest.fail(
        "Public sample must not authenticate"
    )
    statements = []

    def record(connection, cursor, statement, *args):
        statements.append(statement.lower())

    event.listen(db_session.get_bind(), "before_cursor_execute", record)
    try:
        response = client.get("/digest/sample")
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", record)
    assert response.status_code == 200
    assert response.headers["x-cache"] == "MISS"
    assert (
        response.headers["cache-control"]
        == "public, max-age=3600, s-maxage=21600, stale-while-revalidate=86400"
    )
    assert _cache_ttl_seconds("/digest/sample") == get_settings().long_cache_ttl_seconds
    body = response.json()
    assert body["date"] == NOW.date().isoformat()
    assert body["counts_by_category"] == {"internship": 1, "job": 1, "hackathon": 1}
    assert 0 < len(body["items"]) <= 6 and body["empty"] is False
    assert not any(
        "users" in sql or "notifications" in sql or "programme_watches" in sql for sql in statements
    )
    for private_value in (
        str(seeded["user"].id),
        seeded["user"].email,
        "Private reader",
        "unsubscribe",
        "sent_at",
        "subscribed",
    ):
        assert private_value not in response.text
    app.dependency_overrides[get_db] = lambda: pytest.fail("Cache hit must not query DB")
    cached = client.get("/digest/sample")
    assert cached.json() == body and cached.headers["x-cache"] == "HIT"
    seeded["send"].assert_not_called()


def test_public_sample_empty_and_uses_the_worker_global_selectors(client, seeded, monkeypatch):
    generic = Mock(return_value=[])
    hacks = Mock(return_value=[])
    monkeypatch.setattr(worker, "_generic_recent_opportunities", generic)
    monkeypatch.setattr(worker, "_hackathon_digest_opportunities", hacks)
    body = client.get("/digest/sample").json()
    assert body == {
        "date": NOW.date().isoformat(),
        "items": [],
        "counts_by_category": {},
        "empty": True,
    }
    args = generic.call_args.args
    assert args[1:] == (NOW - worker.DIGEST_WINDOW_DEFAULT, worker.DIGEST_GENERIC_SAMPLE_SIZE, NOW)
    assert hacks.call_args.args[1] == NOW


def test_public_top_six_keep_full_category_counts(client, seeded, monkeypatch):
    monkeypatch.setattr(
        worker, "_generic_recent_opportunities", lambda *args: seeded["listings"][:1] * 5
    )
    monkeypatch.setattr(
        worker, "_hackathon_digest_opportunities", lambda *args: seeded["listings"][2:] * 3
    )
    body = client.get("/digest/sample").json()
    assert len(body["items"]) == 6
    assert body["counts_by_category"] == {"internship": 5, "hackathon": 3}


def test_public_sample_date_is_ist_at_midnight(client, monkeypatch):
    class MidnightIST(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.replace(hour=19)  # 00:30 IST on 2 April; still 1 April UTC.

    monkeypatch.setattr(digest, "datetime", MidnightIST)
    body = client.get("/digest/sample").json()
    assert body["date"] == "2031-04-02"
