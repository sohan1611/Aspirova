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
    HACKATHON_DIGEST_SIZE,
    HACKATHON_DIGEST_MIN_GAP,
    HACKATHON_DIGEST_REPUTED_RESERVE,
    HACKATHON_DIGEST_SUBJECT,
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


def _deadline_days(opportunities) -> list[int]:
    return [(o.deadline - NOW).days for o in opportunities if o.deadline is not None]


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


def test_digest_prefers_distinct_deadline_days(db_session, company_factory, competition_factory):
    """A deep +2d pool must not monopolise the daily digest."""
    for i in range(6):
        company = company_factory(f"Same Day College {i}")
        competition_factory(company, title=f"Same Day Event {i}", days_to_deadline=2)
    for day in (3, 4, 5, 6):
        company = company_factory(f"Distinct Day College {day}")
        competition_factory(
            company,
            title=f"Distinct Day Event {day}",
            days_to_deadline=day,
        )

    picks = _hackathon_digest_opportunities(db_session, NOW, limit=HACKATHON_DIGEST_SIZE)
    _assert_isolated(picks)
    days = _deadline_days(picks)

    assert len(picks) == HACKATHON_DIGEST_SIZE
    assert len(days) == len(set(days))


def test_digest_falls_back_to_repeated_days_when_distinct_days_cannot_fill(
    db_session, company_factory, competition_factory
):
    """Diversity is a preference, not permission to shrink the email."""
    for i in range(HACKATHON_DIGEST_SIZE):
        company = company_factory(f"Limited Day College {i}")
        competition_factory(
            company,
            title=f"Limited Day Event {i}",
            days_to_deadline=2 if i < 3 else 3,
        )

    picks = _hackathon_digest_opportunities(db_session, NOW, limit=HACKATHON_DIGEST_SIZE)
    _assert_isolated(picks)
    days = _deadline_days(picks)

    assert len(picks) == HACKATHON_DIGEST_SIZE
    assert set(days) == {2, 3}


def test_reputed_reserved_pick_wins_when_fill_collides_on_deadline_day(
    db_session, company_factory, competition_factory
):
    """A same-day filler must move on instead of displacing the reserve."""
    iit = company_factory("Indian Institute of Technology (IIT), Delhi")
    competition_factory(iit, title="IIT Same Day Reserve", days_to_deadline=5)

    same_day = company_factory("Plain Same Day College")
    competition_factory(same_day, title="Plain Same Day Fill", days_to_deadline=5)
    for day in (6, 7, 8):
        company = company_factory(f"Later Distinct College {day}")
        competition_factory(
            company,
            title=f"Later Distinct Event {day}",
            days_to_deadline=day,
        )

    picks = _hackathon_digest_opportunities(db_session, NOW, limit=3)
    _assert_isolated(picks)
    titles = _titles(picks)

    assert "IIT Same Day Reserve" in titles
    assert "Plain Same Day Fill" not in titles
    assert _deadline_days(picks) == [5, 6, 7]


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
    captured: list[tuple[str, dict | None]] = []

    def _fake_send(to, subject, html, text, headers=None):
        captured.append((subject, headers))
        return True

    monkeypatch.setattr(notifications_module, "send_email", _fake_send)

    company = company_factory("Indian Institute of Technology (IIT), Roorkee")
    competition_factory(company, title="Header Test Event", days_to_deadline=9)
    user = models.User(email=f"hd-hdr-{uuid.uuid4()}@example.com")
    db_session.add(user)
    db_session.flush()

    send_hackathon_digests(db_session, now=datetime.now(timezone.utc))

    assert captured, "expected at least one send"
    subject, headers = captured[0]
    assert headers, "bulk mail must carry List-Unsubscribe"
    assert headers["List-Unsubscribe"].startswith("<http")
    assert headers["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"

    # Subject and headers are asserted together on purpose. They are set in one
    # call and were lost independently once already: this rename branch was cut
    # before List-Unsubscribe existed, so rebasing it produced a conflict where
    # taking either side silently dropped the other - the branch's side would
    # have shipped the new subject with no headers, reinstating the exact Gmail
    # accept-then-discard bug that PR #101 fixed.
    assert subject == HACKATHON_DIGEST_SUBJECT
    assert subject == "Your Daily Dose of Hackathons \U0001f680"


# --------------------------------------------------- visible unsubscribe link


def test_body_carries_a_visible_unsubscribe_link(
    db_session, monkeypatch, company_factory, competition_factory
):
    """The List-Unsubscribe header is only rendered as a control by clients that
    support it. Everyone else needs a link they can see, and the alternative to
    finding one is the spam button - which costs domain reputation far more than
    an unsubscribe does.
    """
    monkeypatch.setattr(
        "core.unsubscribe._signing_key", lambda: b"pinned-test-key-do-not-use-in-prod"
    )
    captured: list[tuple[str, str]] = []

    def _fake_send(to, subject, html, text, headers=None):
        captured.append((html, text))
        return True

    monkeypatch.setattr(notifications_module, "send_email", _fake_send)

    company = company_factory("IIT Kanpur")
    competition_factory(company, title="Visible Link Event", days_to_deadline=9)
    user = models.User(email=f"hd-vis-{uuid.uuid4()}@example.com")
    db_session.add(user)
    db_session.flush()

    send_hackathon_digests(db_session, now=datetime.now(timezone.utc))

    assert captured, "expected at least one send"
    html, text = captured[0]
    assert ">Unsubscribe</a>" in html
    assert "/notifications/unsubscribe?token=" in html
    assert "/notifications/unsubscribe?token=" in text, "plain-text part needs it too"


def test_each_recipient_gets_their_own_unsubscribe_token(
    db_session, monkeypatch, company_factory, competition_factory
):
    """The body used to be rendered ONCE outside the recipient loop and shared.
    That is correct only while the body is identical for everybody - the moment
    it carries a per-user token, one shared render hands every reader the same
    link, and the first person to click unsubscribes somebody else.
    """
    monkeypatch.setattr(
        "core.unsubscribe._signing_key", lambda: b"pinned-test-key-do-not-use-in-prod"
    )
    captured: list[str] = []

    def _fake_send(to, subject, html, text, headers=None):
        captured.append(html)
        return True

    monkeypatch.setattr(notifications_module, "send_email", _fake_send)

    company = company_factory("IIT Madras")
    competition_factory(company, title="Two Reader Event", days_to_deadline=9)
    for _ in range(2):
        db_session.add(models.User(email=f"hd-two-{uuid.uuid4()}@example.com"))
    db_session.flush()

    send_hackathon_digests(db_session, now=datetime.now(timezone.utc))

    assert len(captured) >= 2, "need two recipients to compare"
    tokens = {body.split("unsubscribe?token=")[1].split('"')[0] for body in captured}
    assert len(tokens) == len(captured), "every recipient must get a distinct token"


# --------------------------------------------------- spacing from the daily digest


def test_skipped_when_the_daily_digest_just_went_out(
    db_session, monkeypatch, company_factory, competition_factory
):
    """These shipped as consecutive steps of one workflow and arrived ~60s
    apart. Scheduling alone cannot fix it - GitHub's cron drifts by hours here -
    so the gap is enforced per user at send time.
    """
    monkeypatch.setattr(notifications_module, "send_email", lambda *a, **k: True)

    company = company_factory("IIT Bombay")
    competition_factory(company, title="Gap Event", days_to_deadline=9)
    user = models.User(email=f"hd-gap-{uuid.uuid4()}@example.com")
    db_session.add(user)
    db_session.flush()

    now = datetime.now(timezone.utc)
    db_session.add(
        models.Notification(
            user_id=user.id,
            type="digest",
            status="sent",
            sent_at=now - timedelta(minutes=1),
        )
    )
    db_session.flush()

    result = send_hackathon_digests(db_session, now=now)

    assert result["skipped_too_soon"] >= 1
    assert not _sent_hackathon_to(db_session, user.id)


def test_sends_once_the_gap_has_elapsed(
    db_session, monkeypatch, company_factory, competition_factory
):
    """Skipped is deferred, not dropped. A later cron slot must still deliver,
    otherwise the gap silently cancels the hackathon digest on any day the daily
    one is late."""
    monkeypatch.setattr(notifications_module, "send_email", lambda *a, **k: True)

    company = company_factory("IIT Kharagpur")
    competition_factory(company, title="Later Slot Event", days_to_deadline=9)
    user = models.User(email=f"hd-later-{uuid.uuid4()}@example.com")
    db_session.add(user)
    db_session.flush()

    now = datetime.now(timezone.utc)
    db_session.add(
        models.Notification(
            user_id=user.id,
            type="digest",
            status="sent",
            sent_at=now - HACKATHON_DIGEST_MIN_GAP - timedelta(minutes=5),
        )
    )
    db_session.flush()

    result = send_hackathon_digests(db_session, now=now)

    assert result["skipped_too_soon"] == 0
    assert _sent_hackathon_to(db_session, user.id)


def test_gap_also_recognises_the_daily_digest_under_its_other_type_name(
    db_session, monkeypatch, company_factory, competition_factory
):
    """The worker records the daily digest as `digest`, but `daily_digest` is
    the specified name and both appear in api/notifications.py. Checking only
    one would let the other slip through and land the emails together again."""
    monkeypatch.setattr(notifications_module, "send_email", lambda *a, **k: True)

    company = company_factory("IIT Roorkee")
    competition_factory(company, title="Alias Event", days_to_deadline=9)
    user = models.User(email=f"hd-alias-{uuid.uuid4()}@example.com")
    db_session.add(user)
    db_session.flush()

    now = datetime.now(timezone.utc)
    db_session.add(
        models.Notification(
            user_id=user.id,
            type="daily_digest",
            status="sent",
            sent_at=now - timedelta(minutes=1),
        )
    )
    db_session.flush()

    assert send_hackathon_digests(db_session, now=now)["skipped_too_soon"] >= 1


def _sent_hackathon_to(session, user_id) -> bool:
    return (
        session.scalar(
            select(models.Notification.id).where(
                models.Notification.user_id == user_id,
                models.Notification.type == "hackathon_digest",
                models.Notification.status == "sent",
            )
        )
        is not None
    )
