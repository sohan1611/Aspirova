"""ALERT-03: cross-source/sender identity against a throwaway Postgres."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event, select

import pipeline.notifications as notifications
import pipeline.saved_search_alerts as searches
from core import models
from core.alert_identity import (
    NEW_LISTING_EVENTS,
    already_notified,
    announcement_meta,
    role_key,
    version_key,
)
from crawlers.runner import _reopen_seen_inventory_listings
from tests import test_notifications as fixtures

db_session = fixtures.db_session
free_plan = fixtures.free_plan
pro_plan = fixtures.pro_plan

NOW = datetime(2030, 1, 1, 12, tzinfo=timezone.utc)


@pytest.fixture
def deliveries(monkeypatch):
    calls = []

    def deliver(to, subject, html, text, headers=None):
        calls.append({"to": to, "subject": subject, "html": html, "text": text})
        return True

    monkeypatch.setattr(notifications, "send_email", deliver)
    monkeypatch.setattr(searches, "send_email", deliver)
    monkeypatch.setattr("core.unsubscribe._signing_key", lambda: b"alert-identity-test-signing-key")
    monkeypatch.setattr(notifications, "_hackathon_digest_opportunities", lambda *args: [])
    return calls


def company(db):
    identity = uuid.uuid4().hex
    row = models.Company(
        slug=f"alert-id-{identity}", name="Identity Co", domain=f"{identity}.identity.test"
    )
    db.add(row)
    db.flush()
    return row


def duplicate_crawl(db, employer, **fields):
    values = {
        "title": "Software Engineer Intern",
        "country": "IN",
        "category": "internship",
        "first_seen_at": NOW - timedelta(hours=2),
        "last_seen_at": NOW,
        "status": "active",
    }
    values.update(fields)
    rows = []
    for source, url in (
        ("arbeitnow", "https://arbeitnow.com/jobs/role"),
        ("lever", f"https://careers.{employer.domain}/role"),
    ):
        row = models.Opportunity(
            slug=f"alert-id-{uuid.uuid4()}",
            company_id=employer.id,
            primary_source=source,
            apply_url=url,
            **values,
        )
        db.add(row)
        rows.append(row)
    rows[0].title = f" {values['title'].upper().replace(' ', '  ')} "
    db.flush()
    return rows


def reader(db, employer=None, *, paid=None):
    user = models.User(email=f"alert-id-{uuid.uuid4()}@example.com")
    db.add(user)
    db.flush()
    if employer:
        db.add(
            models.DreamCompany(
                user_id=user.id, company_id=employer.id, created_at=NOW - timedelta(days=10)
            )
        )
    if paid:
        db.add(models.Subscription(user_id=user.id, plan_id=paid.id, status="active"))
    search = models.SavedSearch(
        user_id=user.id,
        name="Intern roles",
        params={"category": "internship"},
        alerts_enabled=True,
        created_at=NOW - timedelta(days=5),
    )
    db.add(search)
    db.flush()
    return user


def ledger(db, user):
    return db.scalars(
        select(models.Notification).where(
            models.Notification.user_id == user.id,
            models.Notification.channel == "email",
            models.Notification.type.in_(NEW_LISTING_EVENTS),
            models.Notification.status == "sent",
        )
    ).all()


def run_senders(db, now, order):
    senders = {
        "company": notifications.send_company_alerts,
        "instant": notifications.send_instant_alerts,
        "search": searches.send_saved_search_alerts,
        "digest": notifications.send_daily_digests,
    }
    for name in order:
        senders[name](db, now=now)


@pytest.mark.parametrize("paid", [False, True], ids=["free", "pro"])
@pytest.mark.parametrize("first", ["company", "instant", "search", "digest"])
def test_duplicate_crawl_announced_once_across_all_senders_and_next_day(
    db_session, free_plan, pro_plan, deliveries, first, paid
):
    employer = company(db_session)
    board, direct = duplicate_crawl(db_session, employer)
    user = reader(db_session, employer, paid=pro_plan if paid else None)
    order = [first, *(name for name in ("company", "instant", "search", "digest") if name != first)]
    run_senders(db_session, NOW, order)
    run_senders(db_session, NOW + timedelta(days=1), order)
    emails = [email for email in deliveries if email["to"] == user.email]
    assert len(emails) == 1
    assert direct.apply_url in emails[0]["html"]
    assert board.apply_url not in emails[0]["html"]
    rows = ledger(db_session, user)
    assert len(rows) == 1
    assert rows[0].meta["role_keys"] == {str(direct.id): role_key(direct)}
    assert rows[0].meta["version_keys"] == {str(direct.id): "new"}

    # An actual full-inventory confirmation clears both source copies' closure
    # and persists the version boundary; first_seen_at intentionally stays old.
    closed_at = NOW + timedelta(days=2)
    for row in (board, direct):
        row.closed_at = closed_at
    db_session.flush()
    _reopen_seen_inventory_listings(db_session, [board.id, direct.id])
    db_session.expire_all()
    reopened_at = NOW + timedelta(days=4)
    # Pin the source confirmation clock (the SQL helper uses the DB clock).
    for row in (board, direct):
        row.meta = {**row.meta, "alert_reopened_at": reopened_at.isoformat()}
        row.last_seen_at = reopened_at
    db_session.flush()
    run_senders(db_session, reopened_at, order)
    run_senders(db_session, reopened_at + timedelta(days=1), order)
    assert len([email for email in deliveries if email["to"] == user.email]) == 2
    assert len(ledger(db_session, user)) == 2
    assert all(
        row.meta["version_keys"][str(direct.id)] == version_key(direct, "digest")
        for row in ledger(db_session, user)[1:]
    )


def test_closing_soon_duplicate_rows_and_changed_deadline(db_session, deliveries):
    employer = company(db_session)
    board, direct = duplicate_crawl(
        db_session, employer, deadline=NOW + timedelta(days=1), deadline_confidence="explicit"
    )
    user = reader(db_session)
    for row in (board, direct):
        db_session.add(models.Bookmark(user_id=user.id, opportunity_id=row.id, status="saved"))
    db_session.flush()
    notifications.send_closing_soon_alerts(db_session, now=NOW)
    notifications.send_closing_soon_alerts(db_session, now=NOW + timedelta(hours=1))
    for row in (board, direct):
        row.deadline += timedelta(days=1)
    db_session.flush()
    notifications.send_closing_soon_alerts(db_session, now=NOW + timedelta(hours=2))
    notifications.send_closing_soon_alerts(db_session, now=NOW + timedelta(hours=3))
    emails = [email for email in deliveries if email["to"] == user.email]
    assert len(emails) == 2
    assert all(
        direct.apply_url in email["html"] and board.apply_url not in email["html"]
        for email in emails
    )
    rows = db_session.scalars(
        select(models.Notification).where(
            models.Notification.user_id == user.id,
            models.Notification.type == "closing_soon",
        )
    ).all()
    assert len(rows) == 2
    assert {row.meta["version_keys"][str(direct.id)] for row in rows} == {
        "2030-01-02",
        "2030-01-03",
    }


def test_distinct_title_company_and_country_still_announced(db_session, free_plan, deliveries):
    first, second = company(db_session), company(db_session)
    user = reader(db_session, first)
    db_session.add(
        models.DreamCompany(
            user_id=user.id, company_id=second.id, created_at=NOW - timedelta(days=10)
        )
    )
    free_plan.features = {**free_plan.features, "dream_companies_limit": None}
    pairs = [
        duplicate_crawl(db_session, first),
        duplicate_crawl(db_session, first, title="Product Intern"),
        duplicate_crawl(db_session, second),
        duplicate_crawl(db_session, first, country="US"),
    ]
    notifications.send_company_alerts(db_session, now=NOW)
    rows = ledger(db_session, user)
    assert {row.opportunity_id for row in rows} == {pair[1].id for pair in pairs}
    assert len([email for email in deliveries if email["to"] == user.email]) == 1


@pytest.mark.parametrize("event_name", ["instant_alert", "digest", "saved_search_alert"])
@pytest.mark.parametrize("modern", [False, True], ids=["legacy-join", "snapshots"])
def test_channel_status_lookback_legacy_and_constant_query_count(db_session, event_name, modern):
    employer = company(db_session)
    board, direct = duplicate_crawl(db_session, employer)
    user = reader(db_session)
    metadata = {"hackathon_ids" if event_name == "digest" else "opportunity_ids": [board.id]}
    if modern:
        metadata.update(announcement_meta([board], event_name))
    row = models.Notification(
        user_id=user.id,
        type=event_name,
        opportunity_id=board.id if event_name == "instant_alert" else None,
        channel="in_app",
        status="sent",
        sent_at=NOW,
        meta=metadata,
    )
    db_session.add(row)
    db_session.flush()

    def check(**kwargs):
        return already_notified(
            db_session,
            user.id,
            [direct],
            events=NEW_LISTING_EVENTS,
            since=NOW - timedelta(days=7),
            **kwargs,
        )

    assert check() == set()
    assert check(channel="in_app") == {direct.id}
    row.channel = "email"
    row.status = "failed"
    db_session.flush()
    assert check() == set()
    row.status = "sent"
    row.sent_at = NOW - timedelta(days=8)
    db_session.flush()
    assert check() == set()
    row.sent_at = NOW
    db_session.flush()
    statements = []

    def count_queries(*args):
        statements.append(args[2])

    event.listen(db_session.bind, "before_cursor_execute", count_queries)
    try:
        assert check() == {direct.id}
    finally:
        event.remove(db_session.bind, "before_cursor_execute", count_queries)
    assert len(statements) <= 2


def test_digest_generic_and_hackathon_picks_prefer_employer_copy(
    db_session, free_plan, deliveries, monkeypatch
):
    employer = company(db_session)
    board, direct = duplicate_crawl(db_session, employer)
    # Make the board the newest row so the existing SQL rank selects it first.
    board.first_seen_at = NOW - timedelta(hours=1)
    user = reader(db_session)
    draft = notifications.preview_daily_digest(db_session, user, now=NOW)
    assert [o.id for o in draft.opportunities] == [direct.id]
    for row in (board, direct):
        row.category = "hackathon"
        row.deadline = NOW + timedelta(days=7)
        row.deadline_confidence = "explicit"
    db_session.flush()
    monkeypatch.setattr(notifications, "_hackathon_digest_opportunities", REAL_HACKATHON_SELECTOR)
    draft = notifications.preview_daily_digest(db_session, user, now=NOW)
    assert [o.id for o in draft.hackathons] == [direct.id]
    db_session.add(
        models.Notification(
            user_id=user.id,
            type="instant_alert",
            opportunity_id=board.id,
            channel="email",
            status="sent",
            sent_at=NOW,
        )
    )
    db_session.flush()
    assert notifications.preview_daily_digest(db_session, user, now=NOW).empty


REAL_HACKATHON_SELECTOR = notifications._hackathon_digest_opportunities


@pytest.mark.parametrize("kind", ["saved_closed", "saved_safety"])
def test_saved_listing_notices_remain_specific_to_each_saved_row(db_session, deliveries, kind):
    employer = company(db_session)
    board, direct = duplicate_crawl(
        db_session,
        employer,
        first_seen_at=NOW - timedelta(days=10),
        closed_at=NOW - timedelta(hours=30),
    )
    user = reader(db_session)
    for row in (board, direct):
        if kind == "saved_safety":
            row.status = "withdrawn"
            row.meta = {
                "safety": {
                    "kind": "scam",
                    "note": "A reported fee request.",
                    "source_url": "https://identity.test/safety",
                }
            }
        db_session.add(
            models.Bookmark(
                user_id=user.id,
                opportunity_id=row.id,
                status="saved",
                created_at=NOW - timedelta(days=4),
            )
        )
    db_session.add(
        models.Notification(
            user_id=user.id,
            opportunity_id=direct.id,
            type="instant_alert",
            channel="email",
            status="sent",
            sent_at=NOW - timedelta(days=2),
            meta=announcement_meta([direct], "instant_alert"),
        )
    )
    db_session.flush()
    notifications.send_closing_soon_alerts(db_session, now=NOW)
    rows = db_session.scalars(
        select(models.Notification).where(
            models.Notification.user_id == user.id,
            models.Notification.type == kind,
        )
    ).all()
    assert {row.opportunity_id for row in rows} == {board.id, direct.id}
    assert all(row.channel == "in_app" and row.meta["email_pending"] is False for row in rows)
    assert len([email for email in deliveries if email["to"] == user.email]) == 1


@pytest.mark.parametrize("fail_first", [False, True])
def test_saved_searches_share_one_index_and_only_successful_sends_suppress(
    db_session, deliveries, monkeypatch, fail_first
):
    employer = company(db_session)
    duplicate_crawl(db_session, employer)
    user = reader(db_session)
    db_session.add(
        models.SavedSearch(
            user_id=user.id,
            params={"category": "internship"},
            alerts_enabled=True,
            created_at=NOW - timedelta(days=5),
        )
    )
    db_session.flush()
    loads = []
    original_load = searches.load_sent_alert_index
    original_send = searches.send_email
    attempts = []

    def load(session, user_id, **kwargs):
        loads.append(user_id)
        return original_load(session, user_id, **kwargs)

    def deliver(to, *args, **kwargs):
        if to == user.email:
            attempts.append(True)
            if fail_first and len(attempts) == 1:
                return False
        return original_send(to, *args, **kwargs)

    monkeypatch.setattr(searches, "load_sent_alert_index", load)
    monkeypatch.setattr(searches, "send_email", deliver)
    searches.send_saved_search_alerts(db_session, now=NOW)
    assert loads.count(user.id) == 1
    assert len(attempts) == (2 if fail_first else 1)
    assert len(ledger(db_session, user)) == 1
    assert len([email for email in deliveries if email["to"] == user.email]) == 1
