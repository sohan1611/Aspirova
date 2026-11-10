"""Daily digest reliability (spec N-05).

Each digest covers listings first seen since the reader's previous successful
digest (24 hours for a first digest, never more than 72), nothing that appeared
in their digests during the last week is sent again, only listings the reader
can still act on are emailed, and the preview renders the same selection
without sending or recording anything.
"""

import uuid
from datetime import datetime, time, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import pipeline.notifications as notifications_module
from api.account import DIGEST_PREVIEW_PER_MINUTE
from api.auth import get_current_user
from api.deps import get_db
from api.main import app
from core import models
from pipeline.notifications import (
    DIGEST_WINDOW_MAX,
    _generic_recent_opportunities,
    _hackathon_digest_opportunities,
    preview_daily_digest,
    send_daily_digests,
)


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


# Captured before the stub below replaces it, for the test of the real selector.
REAL_HACKATHON_SELECTOR = _hackathon_digest_opportunities


@pytest.fixture
def sent_emails(monkeypatch):
    calls = []

    def _fake_send(to, subject, html, text, headers=None):
        calls.append({"to": to, "subject": subject, "html": html})
        return True

    monkeypatch.setattr(
        "core.unsubscribe._signing_key", lambda: b"pinned-test-key-do-not-use-in-prod"
    )
    monkeypatch.setattr(notifications_module, "send_email", _fake_send)
    # The shared hackathon picks come from whatever the database holds. Pin them
    # so only the rows a test creates can appear.
    monkeypatch.setattr(notifications_module, "_hackathon_digest_opportunities", lambda *args: [])
    return calls


@pytest.fixture
def free_plan(db_session: Session):
    plan = db_session.scalar(select(models.Plan).where(models.Plan.key == "free"))
    if plan is None:
        plan = models.Plan(key="free", price_paise=0, billing=None, features={})
        db_session.add(plan)
        db_session.flush()
    plan.features = {"daily_digest": True, "instant_alerts": False, "dream_companies_limit": 1}
    return plan


def _noon_today() -> datetime:
    """An injected run time whose previous-day digests never hit today's cap."""
    return datetime.combine(datetime.now(timezone.utc).date(), time(12), tzinfo=timezone.utc)


def _company(db: Session) -> models.Company:
    suffix = uuid.uuid4().hex
    company = models.Company(
        slug=f"digest-rel-{suffix}",
        name=f"Digest Reliability {suffix}",
        name_normalized=f"digest reliability {suffix}",
    )
    db.add(company)
    db.flush()
    return company


def _reader(db: Session, follows: models.Company | None = None) -> models.User:
    user = models.User(email=f"digest-rel-{uuid.uuid4()}@example.com")
    db.add(user)
    db.flush()
    if follows is not None:
        db.add(models.DreamCompany(user_id=user.id, company_id=follows.id))
        db.flush()
    return user


def _listing(db: Session, company: models.Company, *, first_seen_at: datetime, **fields):
    values = {
        "title": f"Digest reliability role {uuid.uuid4().hex[:10]}",
        "apply_url": "https://example.com/apply",
        "first_seen_at": first_seen_at,
        "last_seen_at": first_seen_at,
    }
    values.update(fields)
    row = models.Opportunity(slug=f"digest-rel-{uuid.uuid4()}", company_id=company.id, **values)
    db.add(row)
    db.flush()
    return row


def _past_digest(db, user, sent_at, *, opportunity_ids=(), hackathon_ids=(), status="sent"):
    db.add(
        models.Notification(
            user_id=user.id,
            type="digest",
            status=status,
            sent_at=sent_at,
            meta={"opportunity_ids": list(opportunity_ids), "hackathon_ids": list(hackathon_ids)},
        )
    )
    db.flush()


def _latest_digest_meta(db: Session, user: models.User) -> dict | None:
    row = db.scalar(
        select(models.Notification)
        .where(
            models.Notification.user_id == user.id,
            models.Notification.type == "digest",
            models.Notification.status == "sent",
        )
        .order_by(models.Notification.id.desc())
        .limit(1)
    )
    return row.meta if row else None


def test_window_starts_at_the_previous_digest_so_nothing_repeats(
    db_session, sent_emails, free_plan
):
    now = _noon_today()
    company = _company(db_session)
    user = _reader(db_session, company)
    _listing(db_session, company, first_seen_at=now - timedelta(hours=20))
    after = _listing(db_session, company, first_seen_at=now - timedelta(hours=10))
    # Yesterday's run went out late, at 18:00. A fixed 24-hour window would send
    # the listing first seen at 16:00 a second time.
    _past_digest(db_session, user, now - timedelta(hours=18))

    send_daily_digests(db_session, now=now)

    assert _latest_digest_meta(db_session, user)["opportunity_ids"] == [after.id]


def test_a_skipped_day_is_picked_up_by_the_next_digest(db_session, sent_emails, free_plan):
    now = _noon_today()
    company = _company(db_session)
    user = _reader(db_session, company)
    missed = _listing(db_session, company, first_seen_at=now - timedelta(hours=40))
    _past_digest(db_session, user, now - timedelta(hours=50))

    send_daily_digests(db_session, now=now)

    assert _latest_digest_meta(db_session, user)["opportunity_ids"] == [missed.id]


def test_window_never_reaches_back_more_than_72_hours(db_session, sent_emails, free_plan):
    now = _noon_today()
    company = _company(db_session)
    user = _reader(db_session, company)
    _listing(db_session, company, first_seen_at=now - DIGEST_WINDOW_MAX - timedelta(hours=2))
    inside = _listing(
        db_session, company, first_seen_at=now - DIGEST_WINDOW_MAX + timedelta(hours=2)
    )
    _past_digest(db_session, user, now - timedelta(days=6))

    send_daily_digests(db_session, now=now)

    assert _latest_digest_meta(db_session, user)["opportunity_ids"] == [inside.id]


def test_first_digest_covers_the_last_24_hours(db_session, sent_emails, free_plan):
    now = _noon_today()
    company = _company(db_session)
    user = _reader(db_session, company)
    _listing(db_session, company, first_seen_at=now - timedelta(hours=30))
    fresh = _listing(db_session, company, first_seen_at=now - timedelta(hours=2))

    send_daily_digests(db_session, now=now)

    assert _latest_digest_meta(db_session, user)["opportunity_ids"] == [fresh.id]


def test_a_listing_from_a_recent_digest_is_not_sent_again(db_session, sent_emails, free_plan):
    now = _noon_today()
    company = _company(db_session)
    user = _reader(db_session, company)
    # first_seen_at after the last digest, as when a closed row is reopened.
    repeated = _listing(db_session, company, first_seen_at=now - timedelta(hours=3))
    new = _listing(db_session, company, first_seen_at=now - timedelta(hours=2))
    _past_digest(db_session, user, now - timedelta(hours=30), opportunity_ids=[repeated.id])

    send_daily_digests(db_session, now=now)

    assert _latest_digest_meta(db_session, user)["opportunity_ids"] == [new.id]


def test_closed_hidden_and_past_deadline_listings_are_not_emailed(
    db_session, sent_emails, free_plan
):
    now = _noon_today()
    company = _company(db_session)
    user = _reader(db_session, company)
    seen = now - timedelta(hours=2)
    open_row = _listing(db_session, company, first_seen_at=seen)
    future = _listing(db_session, company, first_seen_at=seen, deadline=now + timedelta(days=3))
    _listing(db_session, company, first_seen_at=seen, closed_at=now - timedelta(hours=1))
    _listing(db_session, company, first_seen_at=seen, deadline=now - timedelta(minutes=1))
    _listing(db_session, company, first_seen_at=seen, is_hidden=True)

    send_daily_digests(db_session, now=now)

    assert set(_latest_digest_meta(db_session, user)["opportunity_ids"]) == {
        open_row.id,
        future.id,
    }


def test_generic_fallback_applies_the_same_guards(db_session):
    now = _noon_today()
    rows = {}
    for name, extra in [
        ("open", {}),
        ("sent", {}),
        ("closed", {"closed_at": now - timedelta(hours=1)}),
        ("hidden", {"is_hidden": True}),
    ]:
        rows[name] = _listing(
            db_session,
            _company(db_session),
            first_seen_at=now - timedelta(hours=1),
            category="internship",
            title=f"Software Engineering Intern {name} {uuid.uuid4().hex[:8]}",
            **extra,
        )

    picked = {
        o.id
        for o in _generic_recent_opportunities(
            db_session, now - timedelta(hours=2), 500, now, frozenset({rows["sent"].id})
        )
    }

    assert rows["open"].id in picked
    assert not picked & {rows["sent"].id, rows["closed"].id, rows["hidden"].id}


def test_a_hackathon_pick_is_not_repeated_within_a_week(
    db_session, sent_emails, free_plan, monkeypatch
):
    now = _noon_today()
    seen, fresh = (
        _listing(
            db_session,
            _company(db_session),
            first_seen_at=now - timedelta(days=2),
            category="hackathon",
            title=f"Campus hackathon {label} {uuid.uuid4().hex[:8]}",
        )
        for label in ("seen", "fresh")
    )
    selections = []

    def picks(session, run_now, limit=5, exclude_ids=frozenset()):
        selections.append(exclude_ids)
        return [h for h in (seen, fresh) if h.id not in exclude_ids][:limit]

    monkeypatch.setattr(notifications_module, "_hackathon_digest_opportunities", picks)
    returning = _reader(db_session)
    newcomer = _reader(db_session)
    _past_digest(db_session, returning, now - timedelta(hours=30), hackathon_ids=[seen.id])

    send_daily_digests(db_session, now=now)

    assert _latest_digest_meta(db_session, returning)["hackathon_ids"] == [fresh.id]
    assert _latest_digest_meta(db_session, newcomer)["hackathon_ids"] == [seen.id, fresh.id]
    # The shared picks are still chosen once per run.
    assert selections.count(frozenset()) == 1


def test_real_hackathon_selector_skips_excluded_and_closed_rows(db_session):
    now = _noon_today()

    def hackathon(label, **extra):
        return _listing(
            db_session,
            _company(db_session),
            first_seen_at=now - timedelta(hours=1),
            category="hackathon",
            primary_source=f"digest-rel-src-{uuid.uuid4().hex[:8]}",
            title=f"Inter college hackathon {label} {uuid.uuid4().hex[:8]}",
            **extra,
        )

    open_row = hackathon("open")
    excluded = hackathon("excluded")
    closed = hackathon("closed", closed_at=now - timedelta(minutes=5))

    picked = {o.id for o in REAL_HACKATHON_SELECTOR(db_session, now, 200, frozenset({excluded.id}))}

    assert open_row.id in picked
    assert excluded.id not in picked and closed.id not in picked


def test_preview_matches_the_digest_and_sends_nothing(db_session, sent_emails, free_plan):
    now = datetime.now(timezone.utc)
    company = _company(db_session)
    user = _reader(db_session, company)
    listing = _listing(db_session, company, first_seen_at=now - timedelta(hours=1))

    draft = preview_daily_digest(db_session, user, now=now)

    assert [o.id for o in draft.opportunities] == [listing.id]
    assert draft.subject and listing.title in draft.html
    assert sent_emails == []
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(models.Notification)
            .where(models.Notification.user_id == user.id)
        )
        == 0
    )


@pytest.fixture
def account_client(db_session):
    holder: dict[str, models.User] = {}
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: holder["user"]
    try:
        yield TestClient(app), holder
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)


def test_account_reports_the_last_digest_and_serves_a_private_preview(
    account_client, db_session, sent_emails, free_plan
):
    client, holder = account_client
    now = datetime.now(timezone.utc)
    company = _company(db_session)
    holder["user"] = user = _reader(db_session, company)

    assert client.get("/account/me").json()["digest_status"] is None

    listing = _listing(db_session, company, first_seen_at=now - timedelta(hours=1))
    response = client.get("/account/digest-preview")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["listing_count"] == 1 and listing.title in body["html"]
    assert sent_emails == []

    _past_digest(
        db_session, user, now - timedelta(days=1), opportunity_ids=[1, 2], hackathon_ids=[3]
    )
    status = client.get("/account/me").json()["digest_status"]
    assert status["last_sent_count"] == 3 and status["last_attempt_failed"] is False
    assert status["last_sent_at"] is not None

    _past_digest(db_session, user, None, status="failed")
    status = client.get("/account/me").json()["digest_status"]
    assert status["last_attempt_failed"] is True and status["last_sent_count"] == 3


def test_digest_preview_is_rate_limited_per_reader(
    account_client, db_session, sent_emails, free_plan
):
    client, holder = account_client
    holder["user"] = _reader(db_session)

    for _ in range(DIGEST_PREVIEW_PER_MINUTE):
        assert client.get("/account/digest-preview").status_code == 200
    limited = client.get("/account/digest-preview")

    assert limited.status_code == 429
    assert "retry-after" in limited.headers
