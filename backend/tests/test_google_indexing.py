"""Integration coverage for the stateful Google Indexing API notifier."""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from core import models
from scripts.notify_google_indexing import (
    notify_google_indexing,
    opportunity_url,
    select_closed_candidates,
    select_opened_candidates,
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


@pytest.fixture
def company(db_session: Session) -> models.Company:
    suffix = uuid.uuid4().hex
    company = models.Company(
        slug=f"google-indexing-company-{suffix}",
        name=f"Google Indexing Company {suffix}",
    )
    db_session.add(company)
    db_session.flush()
    return company


def _opportunity(
    db_session: Session,
    company: models.Company,
    *,
    name: str,
    category: str = "job",
    status: str = "active",
    closed_at: datetime | None = None,
    is_hidden: bool = False,
    country: str | None = "IN",
    is_remote: bool | None = False,
    description_raw: str | None = "A complete role description.",
    first_seen_at: datetime | None = None,
) -> models.Opportunity:
    suffix = uuid.uuid4().hex
    seen_at = first_seen_at or datetime.now(timezone.utc) + timedelta(days=3650)
    opportunity = models.Opportunity(
        slug=f"google-indexing-{name}-{suffix}",
        company_id=company.id,
        title=f"Google Indexing {name}",
        category=category,
        status=status,
        closed_at=closed_at,
        is_hidden=is_hidden,
        country=country,
        is_remote=is_remote,
        description_raw=description_raw,
        apply_url=f"https://example.com/{name}/{suffix}",
        posted_at=seen_at,
        first_seen_at=seen_at,
        last_seen_at=seen_at,
    )
    db_session.add(opportunity)
    db_session.flush()
    return opportunity


def _notification(
    db_session: Session,
    opportunity: models.Opportunity,
    *,
    reason: str,
    notified_at: datetime | None = None,
) -> models.GoogleIndexingNotification:
    row = models.GoogleIndexingNotification(
        opportunity_id=opportunity.id,
        url=opportunity_url("https://www.aspirova.org", opportunity.slug),
        reason=reason,
        notified_at=notified_at or datetime.now(timezone.utc),
    )
    db_session.add(row)
    db_session.flush()
    return row


def _selected_ids(candidates) -> set[int]:
    return {candidate.opportunity_id for candidate in candidates}


def _recorded_notifications(
    db_session: Session,
    opportunity_ids: list[int],
) -> set[tuple[int, str]]:
    return set(
        db_session.execute(
            select(
                models.GoogleIndexingNotification.opportunity_id,
                models.GoogleIndexingNotification.reason,
            ).where(models.GoogleIndexingNotification.opportunity_id.in_(opportunity_ids))
        ).all()
    )


@dataclass(frozen=True)
class FakeResponse:
    status_code: int
    text: str = ""


class FakeSender:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = iter(responses)
        self.calls: list[str] = []

    def __call__(self, url: str) -> FakeResponse:
        self.calls.append(url)
        return next(self.responses)


def test_opened_candidates_match_jobposting_eligibility(
    db_session: Session,
    company: models.Company,
) -> None:
    now = datetime.now(timezone.utc)
    eligible_job = _opportunity(db_session, company, name="eligible-job")
    eligible_internship = _opportunity(
        db_session,
        company,
        name="eligible-internship",
        category="internship",
    )
    blank_title = _opportunity(db_session, company, name="blank-title")
    blank_title.title = "  "
    blank_company = models.Company(
        slug=f"google-indexing-blank-company-{uuid.uuid4().hex}",
        name="  ",
    )
    db_session.add(blank_company)
    db_session.flush()
    excluded = [
        _opportunity(db_session, company, name="hackathon", category="hackathon"),
        _opportunity(db_session, company, name="closed", closed_at=now),
        _opportunity(db_session, company, name="hidden", is_hidden=True),
        _opportunity(
            db_session,
            company,
            name="stale",
            first_seen_at=now - timedelta(days=306),
        ),
        _opportunity(db_session, company, name="no-country", country=""),
        _opportunity(db_session, company, name="unknown-remote", is_remote=None),
        _opportunity(db_session, company, name="empty-description", description_raw="  "),
        _opportunity(db_session, company, name="inactive", status="expired"),
        blank_title,
        _opportunity(db_session, blank_company, name="blank-company"),
    ]
    db_session.flush()

    selected = _selected_ids(select_opened_candidates(db_session, limit=20))

    assert eligible_job.id in selected
    assert eligible_internship.id in selected
    assert not selected.intersection(opportunity.id for opportunity in excluded)


def test_opened_notification_prevents_repeat_offer(
    db_session: Session,
    company: models.Company,
) -> None:
    opportunity = _opportunity(db_session, company, name="already-opened")
    _notification(db_session, opportunity, reason="opened")

    selected = _selected_ids(select_opened_candidates(db_session, limit=20))

    assert opportunity.id not in selected


def test_closed_candidates_require_opened_and_are_idempotent(
    db_session: Session,
    company: models.Company,
) -> None:
    now = datetime.now(timezone.utc)
    old_notification_time = now - timedelta(days=1000)
    closed_with_opened = _opportunity(
        db_session,
        company,
        name="closed-with-opened",
        closed_at=now,
        first_seen_at=now - timedelta(days=100),
    )
    _notification(
        db_session,
        closed_with_opened,
        reason="opened",
        notified_at=old_notification_time,
    )
    closed_without_opened = _opportunity(
        db_session,
        company,
        name="closed-without-opened",
        closed_at=now,
    )
    already_closed = _opportunity(
        db_session,
        company,
        name="already-closed",
        closed_at=now,
    )
    _notification(db_session, already_closed, reason="opened")
    _notification(db_session, already_closed, reason="closed")
    hidden = _opportunity(
        db_session,
        company,
        name="hidden-after-open",
        is_hidden=True,
        first_seen_at=now - timedelta(days=200),
    )
    _notification(db_session, hidden, reason="opened", notified_at=old_notification_time)
    stale = _opportunity(
        db_session,
        company,
        name="stale-after-open",
        first_seen_at=now - timedelta(days=306),
    )
    _notification(db_session, stale, reason="opened", notified_at=old_notification_time)

    selected_candidates = select_closed_candidates(db_session, limit=20)
    selected_order = [candidate.opportunity_id for candidate in selected_candidates]
    selected = set(selected_order)

    assert closed_with_opened.id in selected
    assert hidden.id in selected
    assert stale.id in selected
    assert closed_without_opened.id not in selected
    assert already_closed.id not in selected
    assert selected_order.index(stale.id) < selected_order.index(hidden.id)
    assert selected_order.index(hidden.id) < selected_order.index(closed_with_opened.id)


def test_budget_sends_closures_before_newest_openings(
    db_session: Session,
    company: models.Company,
) -> None:
    now = datetime.now(timezone.utc)
    closed = _opportunity(db_session, company, name="budget-closed", closed_at=now)
    _notification(
        db_session,
        closed,
        reason="opened",
        notified_at=now - timedelta(days=1000),
    )
    newest_open = _opportunity(
        db_session,
        company,
        name="budget-newest-open",
        first_seen_at=now + timedelta(days=4000),
    )
    older_open = _opportunity(
        db_session,
        company,
        name="budget-older-open",
        first_seen_at=now + timedelta(days=3999),
    )
    sender = FakeSender([FakeResponse(200), FakeResponse(200)])

    result = notify_google_indexing(
        db_session,
        apply=True,
        limit=2,
        site_url="https://www.aspirova.org",
        sender=sender,
    )

    notifications = _recorded_notifications(
        db_session,
        [closed.id, newest_open.id, older_open.id],
    )
    assert result.sent_closed == 1
    assert result.sent_opened == 1
    assert sender.calls[0] == opportunity_url("https://www.aspirova.org", closed.slug)
    assert (closed.id, "closed") in notifications
    assert (newest_open.id, "opened") in notifications
    assert not any(item[0] == older_open.id for item in notifications)


def test_only_http_200_writes_a_notification(
    db_session: Session,
    company: models.Company,
) -> None:
    now = datetime.now(timezone.utc)
    failed = _opportunity(
        db_session,
        company,
        name="http-500",
        first_seen_at=now + timedelta(days=5000),
    )
    succeeded = _opportunity(
        db_session,
        company,
        name="http-200",
        first_seen_at=now + timedelta(days=4999),
    )
    sender = FakeSender([FakeResponse(500, "temporary failure"), FakeResponse(200)])

    result = notify_google_indexing(
        db_session,
        apply=True,
        limit=2,
        site_url="https://www.aspirova.org",
        sender=sender,
    )

    notifications = _recorded_notifications(db_session, [failed.id, succeeded.id])
    assert result.failures == 1
    assert result.exit_code == 0
    assert (failed.id, "opened") not in notifications
    assert (succeeded.id, "opened") in notifications


def test_http_429_stops_and_leaves_remaining_candidates_pending(
    db_session: Session,
    company: models.Company,
) -> None:
    now = datetime.now(timezone.utc)
    opportunities = [
        _opportunity(
            db_session,
            company,
            name=f"quota-{index}",
            first_seen_at=now + timedelta(days=6000 - index),
        )
        for index in range(3)
    ]
    sender = FakeSender([FakeResponse(429, "quota"), FakeResponse(200)])

    result = notify_google_indexing(
        db_session,
        apply=True,
        limit=3,
        site_url="https://www.aspirova.org",
        sender=sender,
    )

    assert result.stopped_on_quota is True
    assert result.exit_code == 0
    assert len(sender.calls) == 1
    assert _recorded_notifications(db_session, [item.id for item in opportunities]) == set()


def test_http_403_stops_with_nonzero_result(
    db_session: Session,
    company: models.Company,
) -> None:
    now = datetime.now(timezone.utc)
    opportunities = [
        _opportunity(
            db_session,
            company,
            name=f"forbidden-{index}",
            first_seen_at=now + timedelta(days=7000 - index),
        )
        for index in range(2)
    ]
    sender = FakeSender([FakeResponse(403, "forbidden"), FakeResponse(200)])

    result = notify_google_indexing(
        db_session,
        apply=True,
        limit=2,
        site_url="https://www.aspirova.org",
        sender=sender,
    )

    assert result.authorization_failed is True
    assert result.exit_code == 1
    assert len(sender.calls) == 1
    assert _recorded_notifications(db_session, [item.id for item in opportunities]) == set()


def test_dry_run_writes_nothing_and_never_calls_sender(
    db_session: Session,
    company: models.Company,
) -> None:
    opportunity = _opportunity(db_session, company, name="dry-run")
    sender = FakeSender([FakeResponse(200)])

    result = notify_google_indexing(
        db_session,
        apply=False,
        limit=1,
        site_url="https://www.aspirova.org",
        sender=sender,
    )

    assert result.sent_opened == 0
    assert result.sent_closed == 0
    assert sender.calls == []
    assert _recorded_notifications(db_session, [opportunity.id]) == set()


def test_opportunity_url_matches_encode_uri_component_semantics() -> None:
    assert opportunity_url("https://www.aspirova.org/", "job/a b!()") == (
        "https://www.aspirova.org/opportunity/job%2Fa%20b!()"
    )
