"""Tests for the hackathon digest (pipeline/notifications.py).

send_email is monkeypatched, as in test_notifications.py - the logic under test
is selection and eligibility, never Resend's delivery.

The reputation regex gets the most attention here because it is the part most
likely to be wrong in a way nobody notices: a false positive quietly promotes an
unrelated event, and a false negative quietly drops a real IIT one. Both were
found by hand against production rows before this was written.
"""

import uuid
from datetime import datetime, time, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

import pipeline.notifications as notifications_module
from core import models
from pipeline.notifications import (
    HACKATHON_DIGEST_REPUTED_RESERVE,
    _hackathon_digest_opportunities,
    send_hackathon_digests,
)

# Far enough in the future that every real row in the database has expired, so
# the selection under test sees ONLY this module's fixtures. These tests run
# against a real database (there is no separate test instance), and with ~760
# live competitions an absolute assertion would otherwise be answered by
# production data. Max real deadline was 2027-11 when this was written;
# _assert_isolated below fails loudly if that ever stops being true, rather than
# letting a test pass for the wrong reason.
NOW = datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc)
_TEST_SLUG_PREFIX = "hd-opp-"


@pytest.fixture
def db_session(engine):
    """Transactional and rolled back, matching every other test module here -
    these tests run against a real database, so nothing may persist."""
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture(autouse=True)
def free_plan(db_session: Session):
    """send_hackathon_digests() gates on the free plan's daily_digest feature,
    so the plan has to exist for the sending tests to mean anything. Reuses the
    existing row rather than inserting a second one - plans.key is unique."""
    plan = db_session.scalar(select(models.Plan).where(models.Plan.key == "free"))
    if plan is None:
        plan = models.Plan(key="free", price_paise=0, billing=None, features={})
        db_session.add(plan)
        db_session.flush()
    plan.features = {**(plan.features or {}), "daily_digest": True}
    return plan


@pytest.fixture
def company_factory(db_session: Session):
    def _make(name: str) -> models.Company:
        company = models.Company(
            slug=f"hd-co-{uuid.uuid4()}",
            name=name,
            name_normalized=name.lower(),
        )
        db_session.add(company)
        db_session.flush()
        return company

    return _make


@pytest.fixture
def competition_factory(db_session: Session):
    def _make(
        company: models.Company | None,
        *,
        title: str,
        days_to_deadline: int | None = 7,
        category: str = "hackathon",
    ) -> models.Opportunity:
        deadline = None if days_to_deadline is None else NOW + timedelta(days=days_to_deadline)
        opportunity = models.Opportunity(
            slug=f"hd-opp-{uuid.uuid4()}",
            company_id=company.id if company else None,
            title=title,
            category=category,
            status="active",
            apply_url="https://example.com/enter",
            first_seen_at=NOW - timedelta(days=1),
            last_seen_at=NOW - timedelta(hours=1),
            posted_at=NOW - timedelta(days=1),
            deadline=deadline,
        )
        db_session.add(opportunity)
        db_session.flush()
        return opportunity

    return _make


def _titles(opportunities) -> set[str]:
    return {o.title for o in opportunities}


def _assert_isolated(picks) -> None:
    """Guard: every pick must be one of ours.

    If a real row ever survives to NOW, these assertions would start describing
    production instead of the fixtures - a silently meaningless test. Better to
    fail here and move NOW forward.
    """
    intruders = [o.slug for o in picks if not o.slug.startswith(_TEST_SLUG_PREFIX)]
    assert not intruders, f"real rows leaked into the test window: {intruders[:3]}"


# --------------------------------------------------------------- reputation


def test_reputed_organiser_is_reserved_even_when_others_close_sooner(
    db_session, company_factory, competition_factory
):
    """The whole point of the reserve: an IIT event must not lose to urgency.

    Without the reserve the three unknown events win every slot, because they
    close first - which is exactly what shipped in the generic digest.
    """
    iit = company_factory("Indian Institute of Technology (IIT), Bhubaneswar")
    unknown = company_factory("Some Local College of Engineering")

    competition_factory(iit, title="Agentic AI Hackathon", days_to_deadline=20)
    for i in range(4):
        competition_factory(unknown, title=f"Local Hack {i}", days_to_deadline=3 + i)

    picks = _hackathon_digest_opportunities(db_session, NOW, limit=3)
    _assert_isolated(picks)

    assert "Agentic AI Hackathon" in _titles(picks)
    assert HACKATHON_DIGEST_REPUTED_RESERVE >= 1


@pytest.mark.parametrize(
    "organiser",
    [
        "Indian Institute of Technology (IIT), Bhubaneswar",
        "IIT Delhi",
        "Indian Institute of Management (IIM), Indore",
        "Birla Institute of Technology & Science, Pilani Campus",
        "National Institute of Technology, Trichy",
    ],
)
def test_recognised_top_tier_organisers(
    db_session, company_factory, competition_factory, organiser
):
    reputed = company_factory(organiser)
    unknown = company_factory("Unknown Polytechnic")
    competition_factory(reputed, title="Reputed Event", days_to_deadline=25)
    for i in range(5):
        competition_factory(unknown, title=f"Filler {i}", days_to_deadline=3 + i)

    picks = _hackathon_digest_opportunities(db_session, NOW, limit=3)
    _assert_isolated(picks)

    assert "Reputed Event" in _titles(picks), f"{organiser} should count as top tier"


@pytest.mark.parametrize(
    "organiser",
    [
        # Real production rows that a naive substring match gets wrong.
        "KIIT School of Management",
        "Institute of Information Technology & Management (IITM), Delhi",
    ],
)
def test_lookalike_organisers_are_not_treated_as_top_tier(
    db_session, company_factory, competition_factory, organiser
):
    """KIIT contains 'IIT' and IITM contains 'IIT'. Neither is an IIT.

    If these matched, the reserve would spend its guaranteed slots on them and
    the feature would silently stop doing the one thing it exists for.
    """
    lookalike = company_factory(organiser)
    competition_factory(lookalike, title="Lookalike Event", days_to_deadline=25)

    urgent = company_factory("Another College")
    for i in range(5):
        competition_factory(urgent, title=f"Urgent {i}", days_to_deadline=3 + i)

    picks = _hackathon_digest_opportunities(db_session, NOW, limit=3)
    _assert_isolated(picks)

    # It may still appear on urgency, but never ahead of sooner deadlines.
    if "Lookalike Event" in _titles(picks):
        assert picks[0].title != "Lookalike Event"


def test_national_level_in_title_counts_without_a_known_organiser(
    db_session, company_factory, competition_factory
):
    """The signal lives in the title as often as the organiser."""
    small = company_factory("Small Private College")
    competition_factory(
        small, title="Brand Phoenix - National Level Challenge", days_to_deadline=25
    )
    other = company_factory("Other College")
    for i in range(5):
        competition_factory(other, title=f"Plain Event {i}", days_to_deadline=3 + i)

    picks = _hackathon_digest_opportunities(db_session, NOW, limit=3)
    _assert_isolated(picks)

    assert "Brand Phoenix - National Level Challenge" in _titles(picks)


# --------------------------------------------------------------- quality


def test_school_level_events_are_excluded(db_session, company_factory, competition_factory):
    """Aspirova's audience is college students; Unstop carries school quizzes."""
    iim = company_factory("Indian Institute of Management (IIM), Rohtak")
    competition_factory(iim, title="The Pi Quiz Juniors: 6th to 8th", days_to_deadline=5)
    competition_factory(iim, title="Class 9 Science Olympiad", days_to_deadline=5)

    picks = _hackathon_digest_opportunities(db_session, NOW, limit=10)
    _assert_isolated(picks)
    titles = _titles(picks)

    assert "The Pi Quiz Juniors: 6th to 8th" not in titles
    assert "Class 9 Science Olympiad" not in titles


def test_closed_events_are_never_selected(db_session, company_factory, competition_factory):
    """Stricter than the browse filter, which keeps a 14-day readable grace."""
    company = company_factory("Some Institute")
    competition_factory(company, title="Already Closed", days_to_deadline=-1)
    competition_factory(company, title="Still Open", days_to_deadline=6)

    picks = _hackathon_digest_opportunities(db_session, NOW, limit=10)
    _assert_isolated(picks)

    assert "Already Closed" not in _titles(picks)


def test_events_with_enough_runway_outrank_ones_closing_immediately(
    db_session, company_factory, competition_factory
):
    """Measured failure: every slot filled with events closing the same day."""
    a = company_factory("College A")
    b = company_factory("College B")
    competition_factory(a, title="Closing Today", days_to_deadline=0)
    competition_factory(b, title="Closing In A Week", days_to_deadline=7)

    picks = _hackathon_digest_opportunities(db_session, NOW, limit=2)
    _assert_isolated(picks)

    assert picks, "expected at least one pick"
    assert picks[0].title == "Closing In A Week"


def test_one_slot_per_organiser(db_session, company_factory, competition_factory):
    """A single institution posting five events must not take the whole email."""
    prolific = company_factory("Indian Institute of Technology (IIT), Bombay")
    for i in range(5):
        competition_factory(prolific, title=f"IIT Bombay Event {i}", days_to_deadline=5 + i)

    picks = _hackathon_digest_opportunities(db_session, NOW, limit=5)
    _assert_isolated(picks)
    from_prolific = [o for o in picks if o.company_id == prolific.id]

    assert len(from_prolific) <= 1


# --------------------------------------------------------------- sending


def test_opt_out_is_respected(db_session, monkeypatch, company_factory, competition_factory):
    sent: list[str] = []
    monkeypatch.setattr(
        notifications_module, "send_email", lambda to, *a, **k: sent.append(to) or True
    )

    company = company_factory("Indian Institute of Technology (IIT), Madras")
    competition_factory(company, title="Opt Out Test Event", days_to_deadline=9)

    opted_in = models.User(email=f"hd-in-{uuid.uuid4()}@example.com")
    opted_out = models.User(
        email=f"hd-out-{uuid.uuid4()}@example.com",
        notification_prefs={"hackathon_digest": False},
    )
    db_session.add_all([opted_in, opted_out])
    db_session.flush()

    send_hackathon_digests(db_session, now=NOW)

    assert opted_out.email not in sent


def test_absent_preference_means_subscribed(db_session, company_factory, competition_factory):
    """New users get it without having to opt in - 'every user, every day'."""
    user = models.User(email=f"hd-default-{uuid.uuid4()}@example.com")
    db_session.add(user)
    db_session.flush()

    assert notifications_module.wants(user, "hackathon_digest") is True


def test_running_twice_sends_only_once(
    db_session, monkeypatch, company_factory, competition_factory
):
    """The digest workflow now has FOUR cron entries, because GitHub's scheduler
    delayed one run by 11 hours and dropped the next entirely. That is only safe
    because a second run inside the frequency cap sends nothing.

    If the cap is ever removed or the notification type renamed, this fails -
    which is the point. Without it, four crons means four emails per user.

    Uses the real clock rather than this module's far-future NOW: the cap is
    checked against the injected `now`, but _record_notification() stamps
    sent_at from datetime.now() and ignores it. Those agree in production and
    only diverge under an injected clock, so testing the cap needs a realistic
    one - the assertion below counts only this test's own user, so real rows
    being selectable does not affect it.
    """
    sent: list[str] = []
    monkeypatch.setattr(
        notifications_module, "send_email", lambda to, *a, **k: sent.append(to) or True
    )

    real_now = datetime.now(timezone.utc)
    company = company_factory("Indian Institute of Technology (IIT), Kanpur")
    competition_factory(company, title="Idempotency Test Event", days_to_deadline=9)

    user = models.User(email=f"hd-once-{uuid.uuid4()}@example.com")
    db_session.add(user)
    db_session.flush()

    send_hackathon_digests(db_session, now=real_now)
    second = send_hackathon_digests(db_session, now=real_now + timedelta(hours=1))

    assert sent.count(user.email) == 1, "a retry inside the cap must not re-send"
    assert second["skipped_capped"] >= 1


def test_a_late_send_yesterday_does_not_suppress_today(
    db_session, monkeypatch, company_factory, competition_factory
):
    """The exact production failure this cap replaced.

    A digest sent late at 15:12 UTC pushed the old rolling 20h window to 11:12
    the next day, so the morning run at 10:17 skipped all 11 users and nobody
    received that day's email. A rolling window ratchets: each late send pushes
    the next later or kills it. A calendar-day cap cannot.

    Times are pinned rather than derived from the clock: "19 hours ago" lands on
    yesterday or today depending on when the suite runs, which would make this
    pass or fail by time of day.
    """
    sent: list[str] = []
    monkeypatch.setattr(
        notifications_module, "send_email", lambda to, *a, **k: sent.append(to) or True
    )

    today = datetime.now(timezone.utc).date()
    run_at = datetime.combine(today, time(10, 17), tzinfo=timezone.utc)
    sent_yesterday_late = run_at - timedelta(hours=19, minutes=5)
    assert sent_yesterday_late.date() != run_at.date(), "fixture must span midnight"

    company = company_factory("Indian Institute of Technology (IIT), Guwahati")
    competition_factory(company, title="Ratchet Test Event", days_to_deadline=9)

    user = models.User(email=f"hd-ratchet-{uuid.uuid4()}@example.com")
    db_session.add(user)
    db_session.flush()
    db_session.add(
        models.Notification(
            user_id=user.id,
            type="hackathon_digest",
            opportunity_id=None,
            status="sent",
            sent_at=sent_yesterday_late,
        )
    )
    db_session.flush()

    send_hackathon_digests(db_session, now=run_at)

    assert user.email in sent, "yesterday's late send must not suppress today - this is the ratchet"


def test_digest_carries_the_list_unsubscribe_header(
    db_session, monkeypatch, company_factory, competition_factory
):
    """Gmail requires List-Unsubscribe on bulk mail and will accept-then-discard
    without it - which is what happened here: Resend reported `delivered` for
    every recipient while the message was in nobody's mailbox, spam included.

    Asserted at the send boundary rather than in core/unsubscribe, because the
    failure mode is the wiring coming undone, not the token being wrong.
    """
    monkeypatch.setattr(
        "core.unsubscribe._signing_key", lambda: b"pinned-test-key-do-not-use-in-prod"
    )
    captured: list[dict | None] = []

    def _fake_send(to, subject, html, text, headers=None):
        captured.append(headers)
        return True

    monkeypatch.setattr(notifications_module, "send_email", _fake_send)

    company = company_factory("Indian Institute of Technology (IIT), Roorkee")
    competition_factory(company, title="Header Test Event", days_to_deadline=9)
    user = models.User(email=f"hd-hdr-{uuid.uuid4()}@example.com")
    db_session.add(user)
    db_session.flush()

    send_hackathon_digests(db_session, now=datetime.now(timezone.utc))

    assert captured, "expected at least one send"
    headers = captured[0]
    assert headers, "bulk mail must carry List-Unsubscribe"
    assert headers["List-Unsubscribe"].startswith("<http")
    assert headers["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
