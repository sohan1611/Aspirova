"""Integration tests for pipeline/notifications.py (Doc 03 sec 4.3, Doc
handoffs/PHASE-2-HANDOFF.md sec 5). send_email is monkeypatched with a
fake recorder - no real Resend account exists yet (a manual prerequisite,
Doc handoffs/PHASE-2-HANDOFF.md sec 10), and the whole point of these
tests is the worker's OWN logic (eligibility, frequency caps,
suppression), not Resend's delivery.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

import pipeline.notifications as notifications_module
from core import models
from core.db import make_engine
from pipeline.notifications import send_daily_digests, send_instant_alerts


@pytest.fixture
def db_session():
    engine = make_engine()
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
    """Fake send_email - records (to, subject) and always succeeds unless
    the test explicitly makes it fail."""
    calls = []

    def _fake_send(to, subject, html, text):
        calls.append({"to": to, "subject": subject})
        return True

    monkeypatch.setattr(notifications_module, "send_email", _fake_send)
    return calls


@pytest.fixture
def free_plan(db_session: Session):
    # Same reasoning as tests/test_gating.py's fixture: reuse whatever
    # "free" plan already exists (core/gating.py hardcodes that lookup
    # key) rather than insert a second one and violate plans.key's unique
    # constraint.
    plan = db_session.scalar(select(models.Plan).where(models.Plan.key == "free"))
    if plan is None:
        plan = models.Plan(key="free", price_paise=0, billing=None, features={})
        db_session.add(plan)
        db_session.flush()
    plan.features = {"daily_digest": True, "instant_alerts": False}
    return plan


@pytest.fixture
def pro_plan(db_session: Session):
    plan = models.Plan(
        key=f"pro-notif-test-{uuid.uuid4()}",
        price_paise=4900,
        billing="monthly",
        features={"daily_digest": True, "instant_alerts": True},
    )
    db_session.add(plan)
    db_session.flush()
    return plan


@pytest.fixture
def source_and_company(db_session: Session):
    source = models.Source(slug=f"notif-test-src-{uuid.uuid4()}", name="Test", type="ats")
    company = models.Company(
        slug=f"notif-test-co-{uuid.uuid4()}",
        name="Notif Test Co",
        name_normalized="notif test co",
    )
    db_session.add_all([source, company])
    db_session.flush()
    return source, company


def _make_user(db_session: Session) -> models.User:
    user = models.User(email=f"notif-test-{uuid.uuid4()}@example.com")
    db_session.add(user)
    db_session.flush()
    return user


def _make_opportunity(
    db_session: Session, company: models.Company, *, first_seen_at: datetime
) -> models.Opportunity:
    opp = models.Opportunity(
        slug=f"notif-test-opp-{uuid.uuid4()}",
        company_id=company.id,
        title="Test Opportunity",
        apply_url="https://example.com/apply",
        first_seen_at=first_seen_at,
        last_seen_at=first_seen_at,
    )
    db_session.add(opp)
    db_session.flush()
    return opp


def test_free_user_gets_generic_digest_when_no_dream_companies(
    db_session, sent_emails, free_plan, source_and_company
) -> None:
    _source, company = source_and_company
    user = _make_user(db_session)
    _make_opportunity(db_session, company, first_seen_at=datetime.now(timezone.utc))

    result = send_daily_digests(db_session)

    assert result["sent"] >= 1
    assert any(e["to"] == user.email for e in sent_emails)


def test_digest_respects_frequency_cap(
    db_session, sent_emails, free_plan, source_and_company
) -> None:
    _source, company = source_and_company
    _make_user(db_session)
    _make_opportunity(db_session, company, first_seen_at=datetime.now(timezone.utc))

    send_daily_digests(db_session)
    first_send_count = len(sent_emails)
    send_daily_digests(db_session)  # immediately again - should be capped

    assert len(sent_emails) == first_send_count


def test_digest_prefers_dream_company_matches_over_generic(
    db_session, sent_emails, free_plan, source_and_company
) -> None:
    _source, company = source_and_company
    user = _make_user(db_session)
    now = datetime.now(timezone.utc)
    dream_opp = _make_opportunity(db_session, company, first_seen_at=now)
    db_session.add(models.DreamCompany(user_id=user.id, company_id=company.id))
    db_session.flush()

    send_daily_digests(db_session)

    notification = db_session.scalar(
        select(models.Notification).where(
            models.Notification.user_id == user.id, models.Notification.type == "digest"
        )
    )
    assert notification.meta["opportunity_ids"] == [dream_opp.id]


def test_digest_excludes_already_instant_alerted_opportunities(
    db_session, sent_emails, free_plan, source_and_company
) -> None:
    _source, company = source_and_company
    user = _make_user(db_session)
    now = datetime.now(timezone.utc)
    opp = _make_opportunity(db_session, company, first_seen_at=now)
    db_session.add(models.DreamCompany(user_id=user.id, company_id=company.id))
    db_session.add(
        models.Notification(
            user_id=user.id,
            type="instant_alert",
            opportunity_id=opp.id,
            status="sent",
            sent_at=now,
        )
    )
    db_session.flush()

    send_daily_digests(db_session)

    notification = db_session.scalar(
        select(models.Notification).where(
            models.Notification.user_id == user.id, models.Notification.type == "digest"
        )
    )
    # The dream-company match was already instant-alerted, so it must not
    # reappear in the digest - either nothing is sent (skipped_empty) or a
    # generic fallback is used, but never opp.id again.
    if notification is not None:
        assert opp.id not in notification.meta["opportunity_ids"]


def test_digest_skipped_when_plan_does_not_grant_it(
    db_session, sent_emails, source_and_company
) -> None:
    _source, company = source_and_company
    no_digest_plan = models.Plan(
        key=f"no-digest-test-{uuid.uuid4()}", price_paise=0, billing=None, features={}
    )
    db_session.add(no_digest_plan)
    db_session.flush()
    user = _make_user(db_session)
    db_session.add(models.Subscription(user_id=user.id, plan_id=no_digest_plan.id, status="active"))
    _make_opportunity(db_session, company, first_seen_at=datetime.now(timezone.utc))
    db_session.flush()

    send_daily_digests(db_session)

    assert not any(e["to"] == user.email for e in sent_emails)


def test_instant_alert_sent_for_entitled_user_with_dream_company_match(
    db_session, sent_emails, pro_plan, source_and_company
) -> None:
    # Real dream_companies/users may already exist in the shared dev DB
    # (send_instant_alerts scans globally, by design) - assert this test's
    # own user was covered, not an exact global count.
    _source, company = source_and_company
    user = _make_user(db_session)
    db_session.add(models.Subscription(user_id=user.id, plan_id=pro_plan.id, status="active"))
    _make_opportunity(db_session, company, first_seen_at=datetime.now(timezone.utc))
    db_session.add(models.DreamCompany(user_id=user.id, company_id=company.id))
    db_session.flush()

    result = send_instant_alerts(db_session)

    assert result["sent"] >= 1
    assert any(e["to"] == user.email for e in sent_emails)


def test_instant_alert_not_sent_for_user_without_entitlement(
    db_session, sent_emails, free_plan, source_and_company
) -> None:
    _source, company = source_and_company
    user = _make_user(db_session)
    _make_opportunity(db_session, company, first_seen_at=datetime.now(timezone.utc))
    db_session.add(models.DreamCompany(user_id=user.id, company_id=company.id))
    db_session.flush()

    send_instant_alerts(db_session)

    assert not any(e["to"] == user.email for e in sent_emails)


def test_instant_alert_suppressed_on_second_run(
    db_session, sent_emails, pro_plan, source_and_company
) -> None:
    _source, company = source_and_company
    user = _make_user(db_session)
    db_session.add(models.Subscription(user_id=user.id, plan_id=pro_plan.id, status="active"))
    _make_opportunity(db_session, company, first_seen_at=datetime.now(timezone.utc))
    db_session.add(models.DreamCompany(user_id=user.id, company_id=company.id))
    db_session.flush()

    send_instant_alerts(db_session)
    sends_to_user_after_first = sum(1 for e in sent_emails if e["to"] == user.email)
    send_instant_alerts(db_session)
    sends_to_user_after_second = sum(1 for e in sent_emails if e["to"] == user.email)

    # Real dream_companies/users may already exist in the shared dev DB
    # (send_instant_alerts scans globally, by design), so exact global
    # counts aren't asserted - only that THIS user/opportunity pair was
    # suppressed on the second run, not double-sent.
    assert sends_to_user_after_first == 1
    assert sends_to_user_after_second == 1


def test_instant_alert_ignores_opportunities_outside_lookback_window(
    db_session, sent_emails, pro_plan, source_and_company
) -> None:
    _source, company = source_and_company
    user = _make_user(db_session)
    db_session.add(models.Subscription(user_id=user.id, plan_id=pro_plan.id, status="active"))
    old_time = datetime.now(timezone.utc) - timedelta(hours=10)
    _make_opportunity(db_session, company, first_seen_at=old_time)
    db_session.add(models.DreamCompany(user_id=user.id, company_id=company.id))
    db_session.flush()

    send_instant_alerts(db_session)

    assert not any(e["to"] == user.email for e in sent_emails)


def test_failed_send_records_failed_status_not_sent(
    db_session, monkeypatch, pro_plan, source_and_company
) -> None:
    monkeypatch.setattr(notifications_module, "send_email", lambda to, subject, html, text: False)
    _source, company = source_and_company
    user = _make_user(db_session)
    db_session.add(models.Subscription(user_id=user.id, plan_id=pro_plan.id, status="active"))
    _make_opportunity(db_session, company, first_seen_at=datetime.now(timezone.utc))
    db_session.add(models.DreamCompany(user_id=user.id, company_id=company.id))
    db_session.flush()

    result = send_instant_alerts(db_session)

    assert result["failed"] == 1
    notification = db_session.scalar(
        select(models.Notification).where(models.Notification.user_id == user.id)
    )
    assert notification.status == "failed"
    assert notification.sent_at is None
