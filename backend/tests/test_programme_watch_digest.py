"""Calendar watch changes share the daily digest and survive failed delivery."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

import pipeline.notifications as notifications
from api.auth import get_current_user
from api.deps import get_db
from api.main import app
from core import email_outbox, models
from core.programme_watches import programme_signature
from pipeline.programme_watch_notifications import (
    ProgrammeWatchUpdate,
    programme_watch_updates,
    render_programme_watch_updates,
)

NOW = datetime(2031, 4, 1, 12, tzinfo=timezone.utc)


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
def deliveries(monkeypatch):
    calls = []

    def deliver(to, subject, html, text, headers=None):
        calls.append({"to": to, "subject": subject, "html": html, "text": text})
        return True

    monkeypatch.setattr(notifications, "send_email", deliver)
    monkeypatch.setattr(notifications, "_dream_company_opportunities", lambda *args: [])
    monkeypatch.setattr(notifications, "_generic_recent_opportunities", lambda *args: [])
    monkeypatch.setattr(notifications, "_hackathon_digest_opportunities", lambda *args: [])
    monkeypatch.setattr(notifications, "can", lambda *args: True)
    monkeypatch.setattr("core.unsubscribe._signing_key", lambda: b"watch-digest-test-key")
    return calls


@pytest.fixture
def watched(db_session):
    suffix = uuid.uuid4().hex
    reader = models.User(email=f"watch-digest-{suffix}@example.com")
    programme = models.Programme(
        slug=f"watch-digest-{suffix}",
        name=f"Research Programme {suffix}",
        organiser="Research Institute",
        category="research_internship",
        url="https://example.com/research",
    )
    edition = models.ProgrammeEdition(
        year=2031,
        status="expected",
        opens_at=NOW + timedelta(days=60),
        closes_at=NOW + timedelta(days=90),
    )
    programme.editions = [edition]
    db_session.add_all([reader, programme])
    db_session.flush()
    watch = models.ProgrammeWatch(
        user_id=reader.id,
        programme_id=programme.id,
        notified_signature=programme_signature(programme, now=NOW),
    )
    db_session.add(watch)
    db_session.flush()
    return reader, programme, edition, watch


def _watch_rows(db_session, reader):
    return list(
        db_session.scalars(
            select(models.Notification)
            .where(
                models.Notification.user_id == reader.id,
                models.Notification.type == "programme_watch",
            )
            .order_by(models.Notification.id)
        )
    )


def _emails(deliveries, reader):
    return [email for email in deliveries if email["to"] == reader.email]


def _announce(db_session, edition):
    edition.status = "announced"
    edition.verified_at = NOW
    db_session.flush()


def test_changed_programme_sends_one_entry_and_one_in_app_notification(
    db_session, deliveries, watched
):
    reader, programme, edition, watch = watched
    _announce(db_session, edition)

    notifications.send_daily_digests(db_session, now=NOW)

    emails = _emails(deliveries, reader)
    assert len(emails) == 1
    assert emails[0]["subject"] == notifications.DAILY_DIGEST_SUBJECT
    assert emails[0]["html"].count("Programmes you watch") == 1
    assert emails[0]["html"].count(f"/programme/{programme.slug}") == 1
    assert "official dates announced" in emails[0]["text"]
    rows = _watch_rows(db_session, reader)
    assert len(rows) == 1
    assert rows[0].channel == "in_app" and rows[0].status == "sent"
    assert rows[0].meta["email_pending"] is False
    assert rows[0].meta["programme_slug"] == programme.slug
    assert watch.notified_at == NOW

    notifications.send_daily_digests(db_session, now=NOW)
    notifications.send_daily_digests(db_session, now=NOW + timedelta(days=1))

    assert len(_emails(deliveries, reader)) == 1
    assert len(_watch_rows(db_session, reader)) == 1
    assert programme_watch_updates(db_session, reader, NOW) == []


def test_watching_current_state_never_sends_an_initial_alert(db_session, deliveries, watched):
    reader, _, _, watch = watched
    signature = watch.notified_signature

    notifications.send_daily_digests(db_session, now=NOW)

    assert _emails(deliveries, reader) == []
    assert _watch_rows(db_session, reader) == []
    assert watch.notified_signature == signature
    assert watch.notified_at is None


def test_watch_updates_and_jobs_share_one_email(db_session, deliveries, watched, monkeypatch):
    reader, programme, edition, _ = watched
    _announce(db_session, edition)
    company = models.Company(slug=f"watch-company-{uuid.uuid4().hex}", name="Research Company")
    listing = models.Opportunity(
        slug=f"watch-role-{uuid.uuid4().hex}",
        company=company,
        title="Research Intern",
        category="internship",
        apply_url="https://example.com/intern",
        first_seen_at=NOW,
        last_seen_at=NOW,
    )
    db_session.add_all([company, listing])
    db_session.flush()
    monkeypatch.setattr(notifications, "_generic_recent_opportunities", lambda *args: [listing])

    notifications.send_daily_digests(db_session, now=NOW)

    emails = _emails(deliveries, reader)
    assert len(emails) == 1
    assert listing.title in emails[0]["html"]
    assert emails[0]["html"].count(f"/programme/{programme.slug}") == 1
    digest = db_session.scalar(
        select(models.Notification).where(
            models.Notification.user_id == reader.id,
            models.Notification.type == "digest",
        )
    )
    assert digest.meta["opportunity_ids"] == [listing.id]
    assert digest.meta["programme_slugs"] == [programme.slug]


def test_daily_email_opt_out_still_gets_in_app_event(db_session, deliveries, watched):
    reader, _, edition, watch = watched
    reader.notification_prefs = {"daily_digest": False}
    _announce(db_session, edition)

    notifications.send_daily_digests(db_session, now=NOW)

    assert _emails(deliveries, reader) == []
    rows = _watch_rows(db_session, reader)
    assert len(rows) == 1 and rows[0].meta["email_pending"] is False
    assert watch.notified_at == NOW
    assert programme_watch_updates(db_session, reader, NOW) == []
    reader.notification_prefs = {"daily_digest": True}
    notifications.send_daily_digests(db_session, now=NOW + timedelta(days=1))
    assert _emails(deliveries, reader) == []


def test_watch_only_digest_available_without_plan_entitlement(
    db_session, deliveries, watched, monkeypatch
):
    reader, _, edition, _ = watched
    monkeypatch.setattr(notifications, "can", lambda *args: False)
    _announce(db_session, edition)

    notifications.send_daily_digests(db_session, now=NOW)

    emails = _emails(deliveries, reader)
    assert len(emails) == 1
    assert "1 programme update for programmes you watch" in emails[0]["text"]
    assert "0 new opportunities" not in emails[0]["text"]


def test_opt_out_cancels_an_older_failed_email_update(db_session, deliveries, watched, monkeypatch):
    reader, _, edition, _ = watched
    _announce(db_session, edition)
    transport = notifications.send_email
    monkeypatch.setattr(notifications, "send_email", lambda *args, **kwargs: False)
    notifications.send_daily_digests(db_session, now=NOW)
    assert _watch_rows(db_session, reader)[0].meta["email_pending"] is True
    reader.notification_prefs = {"daily_digest": False}

    notifications.send_daily_digests(db_session, now=NOW + timedelta(minutes=1))

    assert _watch_rows(db_session, reader)[0].meta["email_pending"] is False
    reader.notification_prefs = {"daily_digest": True}
    monkeypatch.setattr(notifications, "send_email", transport)
    notifications.send_daily_digests(db_session, now=NOW + timedelta(days=1))
    assert _emails(deliveries, reader) == []


@pytest.mark.parametrize("raises", [False, True])
def test_failed_digest_retries_pending_event_without_duplicate_notification(
    db_session, deliveries, watched, monkeypatch, raises
):
    reader, _, edition, _ = watched
    _announce(db_session, edition)
    transport = notifications.send_email

    def failed(*args, **kwargs):
        if raises:
            raise RuntimeError("simulated transport failure")
        return False

    monkeypatch.setattr(notifications, "send_email", failed)
    notifications.send_daily_digests(db_session, now=NOW)
    rows = _watch_rows(db_session, reader)
    assert len(rows) == 1 and rows[0].meta["email_pending"] is True

    monkeypatch.setattr(notifications, "send_email", transport)
    email_outbox.drain(db_session, now=NOW + timedelta(minutes=3), sender=transport)

    assert len(_emails(deliveries, reader)) == 1
    rows = _watch_rows(db_session, reader)
    assert len(rows) == 1 and rows[0].meta["email_pending"] is False


@pytest.mark.parametrize("withdrawn_status", ["expected", "discontinued"])
def test_withdrawn_official_window_cancels_retry_but_keeps_in_app_history(
    db_session, deliveries, watched, monkeypatch, withdrawn_status
):
    reader, _, edition, watch = watched
    _announce(db_session, edition)
    transport = notifications.send_email
    monkeypatch.setattr(notifications, "send_email", lambda *args, **kwargs: False)
    notifications.send_daily_digests(db_session, now=NOW)
    row = _watch_rows(db_session, reader)[0]
    snapshot = dict(row.meta)
    baseline = watch.notified_signature
    assert row.meta["email_pending"] is True
    edition.status = withdrawn_status
    db_session.flush()

    preview = notifications.preview_daily_digest(db_session, reader, now=NOW)

    assert preview.empty and preview.programme_updates == []
    assert row.meta == snapshot
    assert watch.notified_signature == baseline
    monkeypatch.setattr(notifications, "send_email", transport)

    email_outbox.drain(db_session, now=NOW + timedelta(minutes=3), sender=transport)
    notifications.send_daily_digests(db_session, now=NOW + timedelta(minutes=3))
    notifications.send_daily_digests(db_session, now=NOW + timedelta(days=1))

    assert _emails(deliveries, reader) == []
    rows = _watch_rows(db_session, reader)
    assert len(rows) == 1
    assert rows[0].meta == {**snapshot, "email_pending": False}


def test_retry_preserves_immutable_payload_without_rewriting_in_app_snapshot(
    db_session, deliveries, watched, monkeypatch
):
    reader, _, edition, _ = watched
    _announce(db_session, edition)
    transport = notifications.send_email
    monkeypatch.setattr(notifications, "send_email", lambda *args, **kwargs: False)
    notifications.send_daily_digests(db_session, now=NOW)
    row = _watch_rows(db_session, reader)[0]
    original_opening = row.meta["opens_at"]
    edition.opens_at += timedelta(days=4)
    payload = db_session.scalar(select(models.EmailOutbox.payload))
    db_session.flush()

    preview = notifications.preview_daily_digest(db_session, reader, now=NOW)

    assert preview.programme_updates == []  # the queued intent owns this notice
    assert row.meta["opens_at"] == original_opening
    monkeypatch.setattr(notifications, "send_email", transport)

    email_outbox.drain(db_session, now=NOW + timedelta(minutes=3), sender=transport)

    assert len(_emails(deliveries, reader)) == 1
    assert _emails(deliveries, reader)[0]["text"] == payload["text"]
    assert len(_watch_rows(db_session, reader)) == 1
    assert row.meta["opens_at"] == original_opening
    assert row.meta["email_pending"] is False


def test_change_after_daily_cap_waits_until_next_digest(db_session, deliveries, watched):
    reader, _, edition, _ = watched
    db_session.add(
        models.Notification(user_id=reader.id, type="digest", status="sent", sent_at=NOW)
    )
    _announce(db_session, edition)

    notifications.send_daily_digests(db_session, now=NOW + timedelta(minutes=1))
    assert _emails(deliveries, reader) == []
    rows = _watch_rows(db_session, reader)
    assert len(rows) == 1 and rows[0].meta["email_pending"] is True

    notifications.send_daily_digests(db_session, now=NOW + timedelta(days=1))
    assert len(_emails(deliveries, reader)) == 1
    assert len(_watch_rows(db_session, reader)) == 1


def test_official_deadline_removal_is_emailed_without_repeating_withdrawn_date(
    db_session, deliveries, watched
):
    reader, programme, edition, watch = watched
    _announce(db_session, edition)
    watch.notified_signature = programme_signature(programme, now=NOW)
    edition.closes_at = None
    db_session.flush()

    notifications.send_daily_digests(db_session, now=NOW)

    email = _emails(deliveries, reader)[0]
    assert "official deadline changed" in email["text"]
    assert "Deadline: Not announced" in email["text"]
    rows = _watch_rows(db_session, reader)
    assert len(rows) == 1
    assert rows[0].meta["event"] == "deadline_changed"
    assert rows[0].meta["closes_at"] is None
    assert rows[0].meta["email_pending"] is False


def test_preview_includes_current_change_without_advancing_watch(db_session, deliveries, watched):
    reader, programme, edition, watch = watched
    baseline = watch.notified_signature
    _announce(db_session, edition)

    draft = notifications.preview_daily_digest(db_session, reader, now=NOW)

    assert not draft.empty and len(draft.programme_updates) == 1
    assert programme.name in draft.html
    assert watch.notified_signature == baseline
    assert watch.notified_at is None
    assert _watch_rows(db_session, reader) == []
    assert _emails(deliveries, reader) == []


def test_pending_changes_coalesce_to_one_entry_per_programme(
    db_session, deliveries, watched, monkeypatch
):
    reader, programme, edition, _ = watched
    _announce(db_session, edition)
    transport = notifications.send_email
    monkeypatch.setattr(notifications, "send_email", lambda *args, **kwargs: False)
    notifications.send_daily_digests(db_session, now=NOW)
    original = db_session.scalar(select(models.EmailOutbox.payload))
    edition.closes_at += timedelta(days=7)
    db_session.flush()
    monkeypatch.setattr(notifications, "send_email", transport)

    email_outbox.drain(db_session, now=NOW + timedelta(minutes=3), sender=transport)
    notifications.send_daily_digests(db_session, now=NOW + timedelta(minutes=3))

    email = _emails(deliveries, reader)[0]
    assert email["html"].count(f"/programme/{programme.slug}") == 1
    assert email["text"] == original["text"]
    rows = _watch_rows(db_session, reader)
    assert len(rows) == 2
    assert sum(bool(row.meta["email_pending"]) for row in rows) == 1
    notifications.send_daily_digests(db_session, now=NOW + timedelta(days=1))
    assert "official deadline changed" in _emails(deliveries, reader)[-1]["text"]
    assert all(row.meta["email_pending"] is False for row in rows)


def test_unwatch_discards_pending_digest_entry(db_session, deliveries, watched, monkeypatch):
    reader, _, edition, watch = watched
    _announce(db_session, edition)
    monkeypatch.setattr(notifications, "send_email", lambda *args, **kwargs: False)
    notifications.send_daily_digests(db_session, now=NOW)
    db_session.delete(watch)
    db_session.flush()

    email_outbox.drain(db_session, now=NOW + timedelta(minutes=3), sender=notifications.send_email)
    assert programme_watch_updates(db_session, reader, NOW) == []
    assert _emails(deliveries, reader) == []
    assert db_session.scalar(select(models.EmailOutbox.status)) == "suppressed"


def test_month_precision_dates_never_render_a_day():
    update = ProgrammeWatchUpdate(
        {
            "programme_name": "Month-only call",
            "programme_slug": "month-only",
            "programme_url": "https://example.com/official",
            "event": "announced",
            "opens_at": "2031-06",
            "closes_at": "2031-07",
            "opens_precision": "month",
            "closes_precision": "month",
        }
    )

    html, text = render_programme_watch_updates([update])

    for content in (html, text):
        assert "Opens: Jun 2031" in content
        assert "Deadline: Jul 2031" in content
        assert "1 Jun" not in content and "31 Jul" not in content


def test_watch_notification_api_has_actionable_copy_and_programme_link(
    db_session, deliveries, watched
):
    reader, programme, edition, _ = watched
    _announce(db_session, edition)
    notifications.send_daily_digests(db_session, now=NOW)
    overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: reader
    try:
        with TestClient(app) as client:
            response = client.get("/notifications")
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(overrides)

    assert response.status_code == 200
    item = next(item for item in response.json()["items"] if item["type"] == "programme_watch")
    assert item["title"] == "Official dates announced"
    assert programme.name in item["body"]
    assert item["programme_slug"] == programme.slug
    assert item["opportunity_slug"] is None
