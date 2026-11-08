"""Tests for hackathon selection and the merged daily digest (pipeline/notifications.py).

send_email is monkeypatched, as in test_notifications.py - the logic under test
is selection and eligibility, never Resend's delivery.

The reputation regex gets the most attention here because it is the part most
likely to be wrong in a way nobody notices: a false positive quietly promotes an
unrelated event, and a false negative quietly drops a real IIT one. Both were
found by hand against production rows before this was written.
"""

import uuid
from collections import Counter
from datetime import datetime, time, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

import api.filters as filters_module
import pipeline.notifications as notifications_module
from core import models
from core.unsubscribe import unsubscribe_url, verify_token
from pipeline.notifications import (
    COMBINED_DIGEST_SUBJECT,
    DAILY_DIGEST_SUBJECT,
    HACKATHON_DIGEST_MAX_PER_SOURCE,
    HACKATHON_DIGEST_REPUTED_RESERVE,
    HACKATHON_DIGEST_SIZE,
    HACKATHON_DIGEST_SUBJECT,
    _hackathon_digest_opportunities,
    send_daily_digests,
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
    """send_daily_digests() gates on the free plan's daily_digest feature,
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
        deadline_confidence: str | None = None,
        first_seen_at: datetime | None = None,
        last_seen_at: datetime | None = None,
        meta: dict | None = None,
        primary_source: str | None = None,
    ) -> models.Opportunity:
        deadline = None if days_to_deadline is None else NOW + timedelta(days=days_to_deadline)
        opportunity = models.Opportunity(
            slug=f"hd-opp-{uuid.uuid4()}",
            company_id=company.id if company else None,
            title=title,
            category=category,
            status="active",
            apply_url="https://example.com/enter",
            first_seen_at=first_seen_at or NOW - timedelta(days=1),
            last_seen_at=last_seen_at or NOW - timedelta(hours=1),
            posted_at=NOW - timedelta(days=1),
            deadline=deadline,
            deadline_confidence=deadline_confidence
            or ("explicit" if deadline is not None else "unknown"),
            meta=meta,
            primary_source=primary_source,
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
    the feature would silently stop doing the one thing it exists for. The
    digest is deliberately shuffled, so a positional assertion would test the
    shuffle seed instead of the reputation rule.
    """
    real_iit = company_factory("Indian Institute of Technology (IIT), Bhubaneswar")
    competition_factory(real_iit, title="Real Reputed Event", days_to_deadline=25)

    lookalike = company_factory(organiser)
    competition_factory(lookalike, title="Lookalike Event", days_to_deadline=25)

    urgent = company_factory("Another College")
    for i in range(5):
        competition_factory(urgent, title=f"Urgent {i}", days_to_deadline=3 + i)

    # With only two slots, the real IIT and lookalike rows cannot both be
    # selected from the day-25 bucket. A substring false positive would spend
    # the reserve on the later-inserted lookalike and displace the real IIT row.
    picks = _hackathon_digest_opportunities(db_session, NOW, limit=2)
    _assert_isolated(picks)
    titles = _titles(picks)

    assert "Real Reputed Event" in titles
    assert "Lookalike Event" not in titles


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


def test_digest_requires_recent_last_seen_at(db_session, company_factory, competition_factory):
    stale_company = company_factory("Stale Digest College")
    fresh_company = company_factory("Fresh Digest College")
    competition_factory(
        stale_company,
        title="Taken Down Competition",
        days_to_deadline=5,
        last_seen_at=NOW - timedelta(hours=40),
    )
    competition_factory(
        fresh_company,
        title="Recently Seen Competition",
        days_to_deadline=6,
        last_seen_at=NOW - timedelta(hours=2),
    )

    picks = _hackathon_digest_opportunities(db_session, NOW, limit=10)
    _assert_isolated(picks)
    titles = _titles(picks)

    assert "Taken Down Competition" not in titles
    assert "Recently Seen Competition" in titles


def test_digest_requires_explicit_deadline_when_countdown_is_printed(
    db_session, company_factory, competition_factory
):
    inferred_company = company_factory("Inferred Date College")
    explicit_company = company_factory("Explicit Date College")
    no_deadline_company = company_factory("No Deadline College")
    competition_factory(
        inferred_company,
        title="Inferred Deadline Competition",
        days_to_deadline=5,
        deadline_confidence="inferred",
    )
    competition_factory(
        explicit_company,
        title="Explicit Deadline Competition",
        days_to_deadline=6,
        deadline_confidence="explicit",
    )
    competition_factory(
        no_deadline_company,
        title="No Stated Deadline Competition",
        days_to_deadline=None,
    )

    picks = _hackathon_digest_opportunities(db_session, NOW, limit=10)
    _assert_isolated(picks)
    titles = _titles(picks)

    assert "Inferred Deadline Competition" not in titles
    assert "Explicit Deadline Competition" in titles
    assert "No Stated Deadline Competition" in titles


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
    titles = _titles(picks)

    assert "Closing In A Week" in titles
    assert "Closing Today" not in titles


def test_digest_spreads_deadline_days_and_is_not_rendered_in_deadline_order(
    db_session, company_factory, competition_factory
):
    """Both halves of the reader's complaint: "2,3,4,5,6 ... give jumbled".

    The consecutive-run check covers the days chosen; the sorted-order check
    covers how they are rendered. A digest can satisfy one and still look
    machine-made: 2, 5, 9, 14, 21 read in ascending order is still a ladder.
    Both are deterministic here because the shuffle is seeded from NOW's date.
    """
    for day in range(2, 31):
        company = company_factory(f"Staircase College {day}")
        competition_factory(
            company,
            title=f"Staircase Event {day}",
            days_to_deadline=day,
            primary_source="unstop",
        )

    picks = _hackathon_digest_opportunities(db_session, NOW, limit=HACKATHON_DIGEST_SIZE)
    _assert_isolated(picks)
    chosen_days = _deadline_days(picks)
    sorted_days = sorted(chosen_days)

    assert len(picks) == HACKATHON_DIGEST_SIZE
    assert len(chosen_days) == len(set(chosen_days))
    assert sorted_days != list(range(sorted_days[0], sorted_days[0] + len(sorted_days)))
    assert chosen_days != sorted_days


def test_digest_selection_is_deterministic_for_the_same_utc_day(
    db_session, company_factory, competition_factory
):
    for day in range(2, 31):
        company = company_factory(f"Determinism College {day}")
        competition_factory(
            company,
            title=f"Determinism Event {day}",
            days_to_deadline=day,
            primary_source="devpost",
        )

    first = _hackathon_digest_opportunities(db_session, NOW, limit=HACKATHON_DIGEST_SIZE)
    second = _hackathon_digest_opportunities(db_session, NOW, limit=HACKATHON_DIGEST_SIZE)
    _assert_isolated(first)
    _assert_isolated(second)

    assert [opportunity.id for opportunity in first] == [opportunity.id for opportunity in second]


def test_structured_school_only_eligibility_is_excluded_and_strict_mode_is_ready(
    db_session, monkeypatch, company_factory, competition_factory
):
    fixtures = [
        ("School Only Event", ["School Students"], 2),
        ("Mixed Audience Event", ["School Students", "Undergraduate"], 5),
        ("Missing Eligibility Event", None, 8),
        ("Null Eligibility Event", None, 11),
        ("String Eligibility Event", "School Students", 14),
    ]
    for title, eligibility, day in fixtures:
        company = company_factory(f"{title} College")
        if title == "Missing Eligibility Event":
            meta = {}
        elif title == "Null Eligibility Event":
            meta = {"eligibility": None}
        else:
            meta = {"eligibility": eligibility}
        competition_factory(company, title=title, days_to_deadline=day, meta=meta)

    monkeypatch.setattr(filters_module, "SCHOOL_AUDIENCE_STRICT", False)
    default_titles = _titles(_hackathon_digest_opportunities(db_session, NOW, limit=10))

    assert "School Only Event" not in default_titles
    assert "Mixed Audience Event" in default_titles
    assert "Missing Eligibility Event" in default_titles
    assert "Null Eligibility Event" in default_titles
    assert "String Eligibility Event" in default_titles

    monkeypatch.setattr(filters_module, "SCHOOL_AUDIENCE_STRICT", True)
    strict_titles = _titles(_hackathon_digest_opportunities(db_session, NOW, limit=10))

    assert "School Only Event" not in strict_titles
    assert "Mixed Audience Event" not in strict_titles
    assert "Missing Eligibility Event" in strict_titles
    assert "Null Eligibility Event" in strict_titles
    assert "String Eligibility Event" in strict_titles


def test_digest_limits_dominant_source_when_other_sources_can_fill(
    db_session, company_factory, competition_factory
):
    for i in range(20):
        company = company_factory(f"Unstop Source College {i}")
        competition_factory(
            company,
            title=f"Unstop Source Event {i}",
            days_to_deadline=2 + i,
            primary_source="unstop",
        )
    for i in range(3):
        company = company_factory(f"Devpost Source College {i}")
        competition_factory(
            company,
            title=f"Devpost Source Event {i}",
            days_to_deadline=22 + i,
            primary_source="devpost",
        )

    picks = _hackathon_digest_opportunities(db_session, NOW, limit=HACKATHON_DIGEST_SIZE)
    _assert_isolated(picks)
    source_counts = Counter(opportunity.primary_source for opportunity in picks)

    assert len(picks) == HACKATHON_DIGEST_SIZE
    assert source_counts["unstop"] <= HACKATHON_DIGEST_MAX_PER_SOURCE
    assert source_counts["devpost"] >= 2


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
    assert len(_deadline_days(picks)) == len(set(_deadline_days(picks)))


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


@pytest.fixture
def digest_deliveries(monkeypatch):
    """Control the job pool while exercising the shared hackathon selector."""
    calls = []

    def fake_send(to, subject, html, text, headers=None):
        calls.append({"to": to, "subject": subject, "html": html, "text": text, "headers": headers})
        return True

    monkeypatch.setattr(notifications_module, "send_email", fake_send)
    monkeypatch.setattr(notifications_module, "_dream_company_opportunities", lambda *args: [])
    monkeypatch.setattr(notifications_module, "_generic_recent_opportunities", lambda *args: [])
    monkeypatch.setattr(
        "core.unsubscribe._signing_key", lambda: b"pinned-test-key-do-not-use-in-prod"
    )
    return calls


def _subscriber(db_session, preferences=None):
    user = models.User(
        email=f"hd-reader-{uuid.uuid4()}@example.com",
        notification_prefs=preferences,
    )
    db_session.add(user)
    db_session.flush()
    return user


def _digest_rows(db_session, user):
    return list(
        db_session.scalars(
            select(models.Notification).where(
                models.Notification.user_id == user.id,
                models.Notification.type == "digest",
            )
        )
    )


def test_jobs_and_hackathons_arrive_in_one_email(
    db_session, monkeypatch, company_factory, competition_factory, digest_deliveries
):
    company = company_factory("IIT Madras")
    hackathon = competition_factory(company, title="Merged Campus Sprint", days_to_deadline=9)
    job = competition_factory(company, title="Graduate Software Engineer", category="job")
    user = _subscriber(db_session)
    monkeypatch.setattr(
        notifications_module,
        "_dream_company_opportunities",
        lambda session, user_id, *args: [job] if user_id == user.id else [],
    )

    send_daily_digests(db_session, now=NOW)

    deliveries = [email for email in digest_deliveries if email["to"] == user.email]
    assert len(deliveries) == 1
    email = deliveries[0]
    assert email["subject"] == COMBINED_DIGEST_SUBJECT
    assert email["subject"] == "Your Aspirova daily digest + hackathons 🚀"
    assert job.title in email["html"] and hackathon.title in email["html"]
    assert ">View &amp; Apply</a>" in email["html"]
    assert ">View &amp; Enter</a>" in email["html"]
    rows = _digest_rows(db_session, user)
    assert len(rows) == 1 and rows[0].status == "sent"
    assert rows[0].meta == {"opportunity_ids": [job.id], "hackathon_ids": [hackathon.id]}


def test_hackathons_only_still_send_the_founder_subject(
    db_session, company_factory, competition_factory, digest_deliveries
):
    company = company_factory("IIT Delhi")
    hackathon = competition_factory(company, title="No Jobs Campus Sprint", days_to_deadline=9)
    user = _subscriber(db_session)

    send_daily_digests(db_session, now=NOW)

    deliveries = [email for email in digest_deliveries if email["to"] == user.email]
    assert len(deliveries) == 1
    assert deliveries[0]["subject"] == HACKATHON_DIGEST_SUBJECT
    assert deliveries[0]["subject"] == "Your Daily Dose of Hackathons 🚀"
    assert hackathon.title in deliveries[0]["html"]
    assert ">Daily digest</td>" in deliveries[0]["html"]
    assert _digest_rows(db_session, user)[0].meta == {
        "opportunity_ids": [],
        "hackathon_ids": [hackathon.id],
    }


def test_jobs_only_keep_the_daily_subject(
    db_session, monkeypatch, company_factory, competition_factory, digest_deliveries
):
    company = company_factory("Jobs Only Company")
    job = competition_factory(company, title="Student Product Intern", category="internship")
    user = _subscriber(db_session)
    monkeypatch.setattr(notifications_module, "_hackathon_digest_opportunities", lambda *args: [])
    monkeypatch.setattr(
        notifications_module,
        "_dream_company_opportunities",
        lambda session, user_id, *args: [job] if user_id == user.id else [],
    )

    send_daily_digests(db_session, now=NOW)

    deliveries = [email for email in digest_deliveries if email["to"] == user.email]
    assert len(deliveries) == 1
    assert deliveries[0]["subject"] == DAILY_DIGEST_SUBJECT == "Your Aspirova daily digest"
    assert "Hackathons &amp; competitions" not in deliveries[0]["html"]
    assert _digest_rows(db_session, user)[0].meta == {
        "opportunity_ids": [job.id],
        "hackathon_ids": [],
    }


@pytest.mark.parametrize("has_jobs", [True, False])
def test_legacy_hackathon_opt_out_suppresses_picks(
    db_session, monkeypatch, company_factory, competition_factory, digest_deliveries, has_jobs
):
    company = company_factory("IIT Kanpur")
    hackathon = competition_factory(company, title="Opted Out Campus Sprint", days_to_deadline=9)
    job = competition_factory(company, title="Student Analyst", category="job")
    user = _subscriber(db_session, {"hackathon_digest": False})
    monkeypatch.setattr(
        notifications_module,
        "_dream_company_opportunities",
        lambda session, user_id, *args: [job] if has_jobs and user_id == user.id else [],
    )

    result = send_daily_digests(db_session, now=NOW)

    deliveries = [email for email in digest_deliveries if email["to"] == user.email]
    if has_jobs:
        assert len(deliveries) == 1
        assert deliveries[0]["subject"] == DAILY_DIGEST_SUBJECT
        assert "Hackathons &amp; competitions" not in deliveries[0]["html"]
        assert hackathon.title not in deliveries[0]["html"] + deliveries[0]["text"]
        assert _digest_rows(db_session, user)[0].meta["hackathon_ids"] == []
    else:
        assert deliveries == [] and _digest_rows(db_session, user) == []
        assert result["skipped_empty"] >= 1


def test_daily_opt_out_stops_the_whole_email(
    db_session, company_factory, competition_factory, digest_deliveries
):
    company = company_factory("IIT Bombay")
    competition_factory(company, title="Daily Opt Out Sprint", days_to_deadline=9)
    user = _subscriber(db_session, {"daily_digest": False, "hackathon_digest": True})

    send_daily_digests(db_session, now=NOW)

    assert not [email for email in digest_deliveries if email["to"] == user.email]
    assert _digest_rows(db_session, user) == []


def test_both_empty_skip_without_a_notification(db_session, monkeypatch, digest_deliveries):
    user = _subscriber(db_session)
    monkeypatch.setattr(notifications_module, "_hackathon_digest_opportunities", lambda *args: [])

    result = send_daily_digests(db_session, now=NOW)

    assert set(result) == {"sent", "failed", "skipped_capped", "skipped_empty"}
    assert result["skipped_empty"] >= 1
    assert not [email for email in digest_deliveries if email["to"] == user.email]
    assert _digest_rows(db_session, user) == []


def test_second_run_on_the_same_day_is_capped(
    db_session, monkeypatch, company_factory, competition_factory, digest_deliveries
):
    company = company_factory("IIT Roorkee")
    hackathon = competition_factory(company, title="One Daily Email Sprint", days_to_deadline=9)
    user = _subscriber(db_session)
    monkeypatch.setattr(
        notifications_module, "_hackathon_digest_opportunities", lambda *args: [hackathon]
    )
    # Delivery rows use the wall clock. Keep the injected run on that UTC date.
    current = datetime.combine(datetime.now(timezone.utc).date(), time(12), tzinfo=timezone.utc)

    send_daily_digests(db_session, now=current)
    second = send_daily_digests(db_session, now=current + timedelta(minutes=1))

    assert len([email for email in digest_deliveries if email["to"] == user.email]) == 1
    assert second["skipped_capped"] >= 1
    assert len(_digest_rows(db_session, user)) == 1


def test_yesterdays_late_digest_does_not_suppress_today(
    db_session, monkeypatch, company_factory, competition_factory, digest_deliveries
):
    company = company_factory("IIT Guwahati")
    hackathon = competition_factory(company, title="Next UTC Day Sprint", days_to_deadline=9)
    user = _subscriber(db_session)
    monkeypatch.setattr(
        notifications_module, "_hackathon_digest_opportunities", lambda *args: [hackathon]
    )
    current = datetime.combine(datetime.now(timezone.utc).date(), time(10, 17), tzinfo=timezone.utc)
    db_session.add(
        models.Notification(
            user_id=user.id,
            type="digest",
            status="sent",
            sent_at=current - timedelta(hours=19, minutes=5),
        )
    )
    db_session.flush()

    send_daily_digests(db_session, now=current)

    assert len([email for email in digest_deliveries if email["to"] == user.email]) == 1


def test_selection_runs_once_and_each_reader_gets_their_own_daily_unsubscribe(
    db_session, monkeypatch, company_factory, competition_factory, digest_deliveries
):
    company = company_factory("IIT Madras")
    hackathon = competition_factory(company, title="Two Readers Sprint", days_to_deadline=9)
    users = [_subscriber(db_session), _subscriber(db_session)]
    original_selector = notifications_module._hackathon_digest_opportunities
    selections = []

    def select_once(session, now):
        selections.append(now)
        return original_selector(session, now)

    monkeypatch.setattr(notifications_module, "_hackathon_digest_opportunities", select_once)

    send_daily_digests(db_session, now=NOW)

    assert selections == [NOW]
    urls = []
    for user in users:
        deliveries = [email for email in digest_deliveries if email["to"] == user.email]
        assert len(deliveries) == 1
        email = deliveries[0]
        url = unsubscribe_url(user.id, "daily_digest")
        urls.append(url)
        assert email["headers"]["List-Unsubscribe"] == f"<{url}>"
        assert email["headers"]["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
        assert f'href="{url}"' in email["html"] and url in email["text"]
        assert ">Unsubscribe</a>" in email["html"]
        assert verify_token(url.split("token=", 1)[1]) == (str(user.id), "daily_digest")
        assert _digest_rows(db_session, user)[0].meta["hackathon_ids"] == [hackathon.id]
    assert len(set(urls)) == 2


def test_hackathon_already_in_the_job_list_is_not_appended_again(
    db_session, monkeypatch, company_factory, competition_factory, digest_deliveries
):
    company = company_factory("IIT Delhi")
    hackathon = competition_factory(company, title="Followed Company Sprint", days_to_deadline=9)
    user = _subscriber(db_session)
    monkeypatch.setattr(
        notifications_module,
        "_dream_company_opportunities",
        lambda session, user_id, *args: [hackathon] if user_id == user.id else [],
    )

    send_daily_digests(db_session, now=NOW)

    deliveries = [email for email in digest_deliveries if email["to"] == user.email]
    assert len(deliveries) == 1
    email = deliveries[0]
    assert email["subject"] == HACKATHON_DIGEST_SUBJECT
    assert email["html"].count(">View &amp; Enter</a>") == 1
    assert email["html"].count("Hackathons &amp; competitions") == 1
    assert _digest_rows(db_session, user)[0].meta == {
        "opportunity_ids": [hackathon.id],
        "hackathon_ids": [],
    }


def test_absent_preferences_mean_subscribed(db_session):
    user = _subscriber(db_session)
    assert notifications_module.wants(user, "daily_digest") is True
    assert notifications_module.wants(user, "hackathon_digest") is True
