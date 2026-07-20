"""Integration tests for daily saved-search alert delivery."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

import pipeline.saved_search_alerts as saved_search_alerts_module
from core import models
from pipeline.saved_search_alerts import send_saved_search_alerts


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
def sent_emails(monkeypatch):
    """Capture alert sends without calling Resend."""

    calls = []

    def _fake_send(to, subject, html, text):
        calls.append({"to": to, "subject": subject, "html": html, "text": text})
        return True

    monkeypatch.setattr(saved_search_alerts_module, "send_email", _fake_send)
    return calls


def _make_user(db_session: Session) -> models.User:
    user = models.User(email=f"saved-search-alert-{uuid.uuid4()}@example.com")
    db_session.add(user)
    db_session.flush()
    return user


def _make_company(db_session: Session) -> models.Company:
    suffix = uuid.uuid4().hex
    company = models.Company(
        slug=f"saved-search-alert-company-{suffix}",
        name=f"Saved Search Alert Company {suffix}",
        name_normalized=f"saved search alert company {suffix}",
    )
    db_session.add(company)
    db_session.flush()
    return company


def _make_opportunity(
    db_session: Session,
    company: models.Company,
    *,
    first_seen_at: datetime,
    title: str = "New internship",
) -> models.Opportunity:
    opportunity = models.Opportunity(
        slug=f"saved-search-alert-opportunity-{uuid.uuid4().hex}",
        company_id=company.id,
        title=title,
        category="internship",
        apply_url="https://example.com/apply",
        status="active",
        first_seen_at=first_seen_at,
        last_seen_at=first_seen_at,
    )
    db_session.add(opportunity)
    db_session.flush()
    return opportunity


def _make_saved_search(
    db_session: Session,
    user: models.User,
    *,
    created_at: datetime,
    last_alerted_at: datetime | None,
    alerts_enabled: bool = True,
    params: dict | None = None,
) -> models.SavedSearch:
    saved_search = models.SavedSearch(
        user_id=user.id,
        name="Internships",
        params=params if params is not None else {"category": "internship"},
        alerts_enabled=alerts_enabled,
        created_at=created_at,
        last_alerted_at=last_alerted_at,
    )
    db_session.add(saved_search)
    db_session.flush()
    return saved_search


def test_saved_search_alert_sends_new_match_and_records_notification(
    db_session, sent_emails
) -> None:
    now = datetime(2026, 7, 20, 12, tzinfo=timezone.utc)
    user = _make_user(db_session)
    company = _make_company(db_session)
    last_alerted_at = now - timedelta(days=1)
    saved_search = _make_saved_search(
        db_session,
        user,
        created_at=last_alerted_at - timedelta(days=1),
        last_alerted_at=last_alerted_at,
    )
    _make_opportunity(
        db_session,
        company,
        first_seen_at=now - timedelta(hours=1),
    )

    result = send_saved_search_alerts(db_session, now=now)

    emails_to_user = [email for email in sent_emails if email["to"] == user.email]
    assert len(emails_to_user) == 1
    assert result["searches"] >= 1
    assert result["emailed"] >= 1

    db_session.refresh(saved_search)
    assert saved_search.last_alerted_at == now
    notification = db_session.scalar(
        select(models.Notification).where(
            models.Notification.user_id == user.id,
            models.Notification.type == "saved_search_alert",
        )
    )
    assert notification is not None
    assert notification.status == "sent"
    assert notification.sent_at is not None


def test_saved_search_alert_leaves_last_alerted_at_when_no_new_matches(
    db_session, sent_emails
) -> None:
    now = datetime(2026, 7, 20, 12, tzinfo=timezone.utc)
    user = _make_user(db_session)
    company = _make_company(db_session)
    last_alerted_at = now - timedelta(days=1)
    # Unique FTS token so this saved search matches only its own seeded row,
    # never the real internships committed to the shared DB (which fall in the
    # same first_seen_at window and would otherwise trip the "no email" assert).
    token = f"ssalert{uuid.uuid4().hex}"
    saved_search = _make_saved_search(
        db_session,
        user,
        created_at=last_alerted_at - timedelta(days=1),
        last_alerted_at=last_alerted_at,
        params={"category": "internship", "q": token},
    )
    _make_opportunity(
        db_session,
        company,
        first_seen_at=last_alerted_at - timedelta(seconds=1),
        title=f"New internship {token}",
    )

    result = send_saved_search_alerts(db_session, now=now)

    assert not any(email["to"] == user.email for email in sent_emails)
    assert result["skipped_empty"] >= 1
    db_session.refresh(saved_search)
    assert saved_search.last_alerted_at == last_alerted_at
    assert (
        db_session.scalar(
            select(models.Notification.id).where(
                models.Notification.user_id == user.id,
                models.Notification.type == "saved_search_alert",
            )
        )
        is None
    )


def test_saved_search_alert_records_failed_delivery_and_advances_window(
    db_session, monkeypatch
) -> None:
    monkeypatch.setattr(saved_search_alerts_module, "send_email", lambda *args: False)
    now = datetime(2026, 7, 20, 12, tzinfo=timezone.utc)
    user = _make_user(db_session)
    company = _make_company(db_session)
    last_alerted_at = now - timedelta(days=1)
    saved_search = _make_saved_search(
        db_session,
        user,
        created_at=last_alerted_at - timedelta(days=1),
        last_alerted_at=last_alerted_at,
    )
    _make_opportunity(
        db_session,
        company,
        first_seen_at=now - timedelta(hours=1),
    )

    result = send_saved_search_alerts(db_session, now=now)

    assert result["emailed"] == 0
    db_session.refresh(saved_search)
    assert saved_search.last_alerted_at == now
    notification = db_session.scalar(
        select(models.Notification).where(
            models.Notification.user_id == user.id,
            models.Notification.type == "saved_search_alert",
        )
    )
    assert notification is not None
    assert notification.status == "failed"
    assert notification.sent_at is None


def test_saved_search_alert_defers_matches_after_the_run_cutoff(db_session, sent_emails) -> None:
    now = datetime(2026, 7, 20, 12, tzinfo=timezone.utc)
    user = _make_user(db_session)
    company = _make_company(db_session)
    last_alerted_at = now - timedelta(days=1)
    # Unique FTS token: isolates this assertion from the real internships in the
    # shared DB so only the seeded (future-dated) row is a candidate.
    token = f"ssalert{uuid.uuid4().hex}"
    saved_search = _make_saved_search(
        db_session,
        user,
        created_at=last_alerted_at - timedelta(days=1),
        last_alerted_at=last_alerted_at,
        params={"category": "internship", "q": token},
    )
    _make_opportunity(
        db_session,
        company,
        first_seen_at=now + timedelta(minutes=1),
        title=f"New internship {token}",
    )

    send_saved_search_alerts(db_session, now=now)

    assert not any(email["to"] == user.email for email in sent_emails)
    db_session.refresh(saved_search)
    assert saved_search.last_alerted_at == last_alerted_at

    send_saved_search_alerts(db_session, now=now + timedelta(minutes=2))

    assert sum(1 for email in sent_emails if email["to"] == user.email) == 1


def test_saved_search_alert_skips_disabled_search(db_session, sent_emails) -> None:
    now = datetime(2026, 7, 20, 12, tzinfo=timezone.utc)
    user = _make_user(db_session)
    company = _make_company(db_session)
    last_alerted_at = now - timedelta(days=1)
    saved_search = _make_saved_search(
        db_session,
        user,
        created_at=last_alerted_at - timedelta(days=1),
        last_alerted_at=last_alerted_at,
        alerts_enabled=False,
    )
    _make_opportunity(
        db_session,
        company,
        first_seen_at=now - timedelta(hours=1),
    )

    send_saved_search_alerts(db_session, now=now)

    assert not any(email["to"] == user.email for email in sent_emails)
    db_session.refresh(saved_search)
    assert saved_search.last_alerted_at == last_alerted_at
    assert (
        db_session.scalar(
            select(models.Notification.id).where(
                models.Notification.user_id == user.id,
                models.Notification.type == "saved_search_alert",
            )
        )
        is None
    )


def test_saved_search_alert_does_not_send_same_match_twice(db_session, sent_emails) -> None:
    now = datetime(2026, 7, 20, 12, tzinfo=timezone.utc)
    user = _make_user(db_session)
    company = _make_company(db_session)
    last_alerted_at = now - timedelta(days=1)
    saved_search = _make_saved_search(
        db_session,
        user,
        created_at=last_alerted_at - timedelta(days=1),
        last_alerted_at=last_alerted_at,
    )
    _make_opportunity(
        db_session,
        company,
        first_seen_at=now - timedelta(hours=1),
    )

    send_saved_search_alerts(db_session, now=now)
    send_saved_search_alerts(db_session, now=now)

    assert sum(1 for email in sent_emails if email["to"] == user.email) == 1
    db_session.refresh(saved_search)
    assert saved_search.last_alerted_at == now
    notifications = list(
        db_session.scalars(
            select(models.Notification).where(
                models.Notification.user_id == user.id,
                models.Notification.type == "saved_search_alert",
            )
        ).all()
    )
    assert len(notifications) == 1


def test_saved_search_alert_html_escapes_opportunity_title(db_session, sent_emails) -> None:
    now = datetime(2026, 7, 20, 12, tzinfo=timezone.utc)
    user = _make_user(db_session)
    company = _make_company(db_session)
    last_alerted_at = now - timedelta(days=1)
    # Unique FTS token keeps the seeded row the only match, so the real prod
    # internships in the window can't crowd it out of the top-10 alert list.
    token = f"ssalert{uuid.uuid4().hex}"
    _make_saved_search(
        db_session,
        user,
        created_at=last_alerted_at - timedelta(days=1),
        last_alerted_at=last_alerted_at,
        params={"category": "internship", "q": token},
    )
    _make_opportunity(
        db_session,
        company,
        first_seen_at=now - timedelta(hours=1),
        # Token first: the default FTS parser treats "<script>" as an HTML tag
        # and drops everything after it, so a trailing token would never index.
        title=f"{token} Research <script> & Development",
    )

    send_saved_search_alerts(db_session, now=now)

    email = next(email for email in sent_emails if email["to"] == user.email)
    assert "Research &lt;script&gt; &amp; Development" in email["html"]
    assert "Research <script>" not in email["html"]
