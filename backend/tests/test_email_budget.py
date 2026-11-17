"""Worker budgets against throwaway Postgres; every delivery is fake."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from api.auth import get_current_user
from api.deps import get_db
from api.main import app
from core import models
from core.alert_identity import already_notified, announcement_meta
from core.config import get_settings
from core.email_budget import EmailBudget, sent_today
from pipeline import notifications as worker
from pipeline import saved_search_alerts, weekly_report

NOW = datetime(2035, 1, 2, 12, tzinfo=timezone.utc)


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
def setup(db_session, monkeypatch):
    """Limit worker recipients to this test, without replacing selection/ranking."""
    audience = []
    calls = []
    for module in (worker, saved_search_alerts, weekly_report):
        monkeypatch.setattr(module, "recipient_filters", lambda: (models.User.id.in_(audience),))
        monkeypatch.setattr(
            module,
            "send_email",
            lambda to, subject, html, text, **kwargs: calls.append((to, subject, text)) or True,
        )
    monkeypatch.setattr("core.unsubscribe._signing_key", lambda: b"email-budget-test-key")
    monkeypatch.setattr(worker, "_hackathon_digest_opportunities", lambda *args: [])
    monkeypatch.setattr(get_settings(), "email_daily_budget", 10)
    monkeypatch.setattr(get_settings(), "email_digest_reserve", 3)
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "")
    plan = db_session.scalar(select(models.Plan).where(models.Plan.key == "free"))
    if plan is None:
        plan = models.Plan(key="free", price_paise=0, features={})
        db_session.add(plan)
    plan.features = {
        "daily_digest": True,
        "instant_alerts": True,
        "weekly_report": True,
        "dream_companies_limit": None,
    }
    company = models.Company(slug=f"budget-{uuid.uuid4().hex}", name="Budget company")
    db_session.add(company)
    db_session.flush()
    return audience, calls, company


def reader(db, setup):
    user = models.User(email=f"budget-{uuid.uuid4().hex}@example.com")
    db.add(user)
    db.flush()
    setup[0].append(user.id)
    return user


def listing(db, setup, *, first_seen_at=NOW - timedelta(hours=6), **overrides):
    values = {
        "slug": f"budget-{uuid.uuid4().hex}",
        "title": "Software engineering internship",
        "company_id": setup[2].id,
        "category": "internship",
        "status": "active",
        "apply_url": "https://example.com/apply",
        "first_seen_at": first_seen_at,
        "last_seen_at": first_seen_at,
    }
    values.update(overrides)
    row = models.Opportunity(**values)
    db.add(row)
    db.flush()
    return row


def notification(db, user, *, kind="digest", status="sent", at=NOW, channel="email", meta=None):
    row = models.Notification(
        user_id=user.id, type=kind, status=status, sent_at=at, channel=channel, meta=meta
    )
    db.add(row)
    db.flush()
    return row


def search(db, user, *, created_at=NOW - timedelta(days=2), enabled=True):
    row = models.SavedSearch(
        user_id=user.id,
        params={"category": "internship"},
        alerts_enabled=enabled,
        created_at=created_at,
    )
    db.add(row)
    db.flush()
    return row


def test_sent_today_utc_boundary_and_statuses(db_session, setup):
    user = reader(db_session, setup)
    midnight = NOW.replace(hour=0)
    before = sent_today(db_session, NOW)
    notification(db_session, user, at=midnight - timedelta(microseconds=1))
    notification(db_session, user, at=midnight)
    notification(db_session, user, at=midnight + timedelta(microseconds=1))
    notification(db_session, user, channel="in_app")
    notification(db_session, user, status="failed")
    notification(db_session, user, status="deferred")
    notification(db_session, user, status="deferred", at=None)
    notification(db_session, user, at=None)
    # This local date is Jan 3, but the same Jan 2 UTC day.
    local_now = datetime(2035, 1, 3, 1, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    assert sent_today(db_session, local_now) - before == 2


def test_budget_snapshot_has_one_query(db_session, setup):
    statements = []

    def record(*args):
        statements.append(args[2])

    connection = db_session.connection()
    event.listen(connection, "before_cursor_execute", record)
    try:
        budget = EmailBudget.for_step(db_session, NOW)
        for _ in range(100):
            budget.can_send("digest")
            budget.remaining()
        budget.record_sent()
    finally:
        event.remove(connection, "before_cursor_execute", record)
    assert len(statements) == 1


def test_digest_activity_order_and_prior_day_deferrals_first(db_session, setup):
    users = [reader(db_session, setup) for _ in range(12)]
    for index, user in enumerate(users):
        search(db_session, user, created_at=NOW - timedelta(hours=index + 1), enabled=False)
        notification(db_session, user, at=NOW - timedelta(days=1), meta={})
    old_listing = listing(db_session, setup)
    result = worker.send_daily_digests(db_session, now=NOW)
    assert result["sent"] == 7
    assert result["skipped_budget"] == 5
    assert [call[0] for call in setup[1]] == [user.email for user in users[:7]]
    deferred = db_session.scalars(
        select(models.Notification).where(models.Notification.status == "deferred")
    ).all()
    assert {row.user_id for row in deferred} == {user.id for user in users[7:]}
    assert len(deferred) == 5
    assert all(row.sent_at is None and row.meta["reason"] == "budget" for row in deferred)
    # A fresh listing keeps the already-served readers eligible tomorrow too.
    next_company = models.Company(slug=f"budget-next-{uuid.uuid4().hex}", name="Next company")
    db_session.add(next_company)
    db_session.flush()
    listing(
        db_session,
        setup,
        first_seen_at=NOW + timedelta(hours=1),
        company_id=next_company.id,
        title="Data science internship",
    )
    setup[1].clear()
    tomorrow = NOW + timedelta(days=1)
    result = worker.send_daily_digests(db_session, now=tomorrow)
    assert result["sent"] == 7
    assert [call[0] for call in setup[1]][:5] == [user.email for user in users[7:]]
    for user in users[7:]:
        sent = db_session.scalar(
            select(models.Notification).where(
                models.Notification.user_id == user.id,
                models.Notification.status == "sent",
                models.Notification.sent_at == tomorrow,
                models.Notification.type == "digest",
            )
        )
        # Includes yesterday's listing, older than 24h now: deferral did not
        # replace their last successful digest or shorten its selection window.
        assert old_listing.id in sent.meta["opportunity_ids"]


def test_activity_count_then_last_success_then_id(db_session, setup):
    users = [reader(db_session, setup) for _ in range(4)]
    for user in users:
        search(db_session, user, created_at=NOW - timedelta(hours=1), enabled=False)
    search(db_session, users[0], created_at=NOW - timedelta(days=1), enabled=False)
    for user in users[1:]:
        notification(db_session, user, at=NOW - timedelta(days=2))
    # Same recent activity: count wins; then never-sent (if any), oldest send,
    # and finally UUID. A resolved deferral must not outrank any of these.
    notification(
        db_session,
        users[3],
        status="deferred",
        at=None,
        meta={"reason": "budget", "deferred_at": (NOW - timedelta(days=3)).isoformat()},
    )
    notification(db_session, users[3], at=NOW - timedelta(days=1))
    ordered = worker._digest_readers(db_session, NOW)
    assert [user.id for user in ordered] == [
        users[0].id,
        *sorted(user.id for user in users[1:3]),
        users[3].id,
    ]


def test_activity_includes_all_user_linked_sources(db_session, setup):
    users = [reader(db_session, setup) for _ in range(4)]
    opportunity = listing(db_session, setup)
    db_session.add(
        models.Bookmark(
            user_id=users[0].id,
            opportunity_id=opportunity.id,
            status="applied",
            created_at=NOW - timedelta(hours=1),
        )
    )
    search(db_session, users[1], created_at=NOW - timedelta(hours=2), enabled=False)
    programme = models.Programme(
        slug=f"budget-{uuid.uuid4().hex}",
        name="Budget programme",
        organiser="Example",
        category="fellowship",
        url="https://example.com/programme",
    )
    db_session.add(programme)
    db_session.flush()
    db_session.add(
        models.ProgrammeWatch(
            user_id=users[2].id,
            programme_id=programme.id,
            created_at=NOW - timedelta(hours=3),
            notified_at=NOW,
        )
    )
    db_session.add(
        models.DreamCompany(
            user_id=users[3].id,
            company_id=setup[2].id,
            created_at=NOW - timedelta(hours=4),
        )
    )
    assert [user.id for user in worker._digest_readers(db_session, NOW)] == [
        user.id for user in users
    ]


def test_empty_digest_does_not_defer_or_use_budget(db_session, setup, monkeypatch):
    reader(db_session, setup)
    monkeypatch.setattr(get_settings(), "email_daily_budget", 0)
    result = worker.send_daily_digests(db_session, now=NOW)
    assert result["skipped_empty"] == 1
    assert result["skipped_budget"] == 0
    assert not setup[1]
    assert db_session.scalar(select(models.Notification.id)) is None


def test_reserve_shared_by_closing_and_saved_search_then_stops(db_session, setup):
    users = [reader(db_session, setup) for _ in range(7)]
    listing(db_session, setup)
    assert worker.send_daily_digests(db_session, now=NOW)["sent"] == 7
    # A different listing is not suppressed by the digests' ALERT-03 history.
    closing = listing(
        db_session,
        setup,
        title="Product design internship",
        deadline=NOW + timedelta(days=2),
        deadline_confidence="explicit",
    )
    for user in users[:2]:
        db_session.add(models.Bookmark(user_id=user.id, opportunity_id=closing.id))
    searches = [search(db_session, user) for user in users[2:4]]
    db_session.flush()
    assert worker.send_closing_soon_alerts(db_session, now=NOW)["users_notified"] == 2
    assert saved_search_alerts.send_saved_search_alerts(db_session, now=NOW)["emailed"] == 1
    assert sent_today(db_session, NOW) == 10
    assert len(setup[1]) == 10
    db_session.refresh(searches[0])
    db_session.refresh(searches[1])
    pending = [row for row in searches if row.last_alerted_at is None]
    assert len(pending) == 1
    assert (
        db_session.scalar(
            select(models.Notification.id).where(
                models.Notification.user_id == pending[0].user_id,
                models.Notification.type == "saved_search_alert",
            )
        )
        is None
    )
    # Retry the remaining search with exactly the same cursor/window tomorrow.
    assert (
        saved_search_alerts.send_saved_search_alerts(db_session, now=NOW + timedelta(days=1))[
            "emailed"
        ]
        == 1
    )
    db_session.refresh(pending[0])
    assert pending[0].last_alerted_at == NOW + timedelta(days=1)


def test_deferred_rows_do_not_affect_any_sent_reader(db_session, setup):
    user = reader(db_session, setup)
    opportunity = listing(db_session, setup)
    notification(
        db_session,
        user,
        status="deferred",
        # Deliberately populated: the status predicate, not null sent_at alone,
        # must keep a deferral out of every successful-send reader.
        at=NOW,
        meta={
            "reason": "budget",
            "deferred_at": NOW.isoformat(),
            "opportunity_ids": [opportunity.id],
            **announcement_meta([opportunity], "digest"),
        },
    )
    assert not worker._already_sent_today(db_session, user.id, "digest", NOW)
    assert worker._digest_history(db_session, user.id, NOW).last_sent_at is None
    assert worker._digest_history(db_session, user.id, NOW).recent_ids == frozenset()
    assert (
        already_notified(
            db_session, user.id, [opportunity], events={"digest"}, since=NOW - timedelta(days=7)
        )
        == set()
    )
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        with TestClient(app) as client:
            assert client.get("/account/me").json()["digest_status"] is None
            sent_at = NOW - timedelta(days=1)
            notification(db_session, user, at=sent_at, meta={"opportunity_ids": [opportunity.id]})
            notification(db_session, user, status="failed", at=None)
            notification(
                db_session,
                user,
                status="deferred",
                at=None,
                meta={"reason": "budget", "deferred_at": NOW.isoformat()},
            )
            status = client.get("/account/me").json()["digest_status"]
            assert status["last_sent_count"] == 1
            assert status["last_attempt_failed"] is True
            assert worker._digest_history(db_session, user.id, NOW).last_sent_at == sent_at
            assert not worker._already_sent_today(db_session, user.id, "digest", NOW)
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.parametrize("instant_only", [False, True])
def test_company_alert_deferred_without_ledger_and_retried(
    db_session, setup, monkeypatch, instant_only
):
    user = reader(db_session, setup)
    db_session.add(
        models.DreamCompany(
            user_id=user.id, company_id=setup[2].id, created_at=NOW - timedelta(days=1)
        )
    )
    opportunity = listing(db_session, setup)
    monkeypatch.setattr(get_settings(), "email_daily_budget", 0)
    assert worker.send_company_alerts(db_session, now=NOW, instant_only=instant_only)["sent"] == 0
    assert db_session.scalar(select(models.Notification.id)) is None
    monkeypatch.setattr(get_settings(), "email_daily_budget", 1)
    assert worker.send_company_alerts(db_session, now=NOW, instant_only=instant_only)["sent"] == 1
    assert db_session.scalar(select(models.Notification.opportunity_id)) == opportunity.id


def test_weekly_deferral_is_not_a_delivery_or_generation(db_session, setup, monkeypatch):
    reader(db_session, setup)
    monkeypatch.setattr(get_settings(), "email_daily_budget", 0)

    def no_generation(*args, **kwargs):
        pytest.fail("A deferred report must not generate its introduction")

    monkeypatch.setattr(weekly_report, "_cohort_intro", no_generation)
    assert weekly_report.send_weekly_reports(db_session, now=NOW)["sent"] == 0
    assert db_session.scalar(select(models.Notification.id)) is None
    monkeypatch.setattr(get_settings(), "email_daily_budget", 1)
    monkeypatch.setattr(weekly_report, "_cohort_intro", lambda *args, **kwargs: None)
    assert weekly_report.send_weekly_reports(db_session, now=NOW)["sent"] == 1


def test_saved_notice_defers_email_but_keeps_in_app_and_pending(db_session, setup, monkeypatch):
    user = reader(db_session, setup)
    opportunity = listing(db_session, setup, status="withdrawn")
    db_session.add(models.Bookmark(user_id=user.id, opportunity_id=opportunity.id))
    monkeypatch.setattr(get_settings(), "email_daily_budget", 0)
    assert worker.send_closing_soon_alerts(db_session, now=NOW)["users_notified"] == 0
    row = db_session.scalar(select(models.Notification))
    assert row.channel == "in_app" and row.status == "sent"
    assert row.meta["email_pending"] is True
    assert "emailed_at" not in row.meta
    assert not setup[1]
    monkeypatch.setattr(get_settings(), "email_daily_budget", 1)
    assert worker.send_closing_soon_alerts(db_session, now=NOW)["users_notified"] == 1
    db_session.refresh(row)
    assert row.meta["email_pending"] is False
    assert sent_today(db_session, NOW) == 1
    assert worker.send_closing_soon_alerts(db_session, now=NOW)["users_notified"] == 0
    assert len(setup[1]) == 1
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        with TestClient(app) as client:
            response = client.get("/notifications").json()
            assert response["unread"] == 1
            assert [item["type"] for item in response["items"]] == ["saved_safety"]
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)


def test_deadline_email_defers_without_ledger_and_retries(db_session, setup, monkeypatch):
    user = reader(db_session, setup)
    opportunity = listing(
        db_session,
        setup,
        deadline=NOW + timedelta(days=2),
        deadline_confidence="explicit",
    )
    db_session.add(models.Bookmark(user_id=user.id, opportunity_id=opportunity.id))
    monkeypatch.setattr(get_settings(), "email_daily_budget", 0)
    assert worker.send_closing_soon_alerts(db_session, now=NOW)["users_notified"] == 0
    assert db_session.scalar(select(models.Notification.id)) is None
    monkeypatch.setattr(get_settings(), "email_daily_budget", 1)
    assert worker.send_closing_soon_alerts(db_session, now=NOW)["users_notified"] == 1
    assert len(setup[1]) == 1


@pytest.mark.parametrize(
    "sender",
    [
        worker.send_daily_digests,
        worker.send_company_alerts,
        worker.send_instant_alerts,
        worker.send_closing_soon_alerts,
        saved_search_alerts.send_saved_search_alerts,
        weekly_report.send_weekly_reports,
    ],
)
def test_each_step_logs_one_counts_only_summary(db_session, setup, caplog, sender):
    with caplog.at_level("INFO", logger="core.email_budget"):
        sender(db_session, now=NOW)
    records = [record for record in caplog.records if record.name == "core.email_budget"]
    assert [record.getMessage() for record in records] == [
        "email budget: sent_today=0 budget=10 remaining=10 deferred=0"
    ]
