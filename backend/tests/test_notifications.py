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
from pipeline.notifications import (
    send_closing_soon_alerts,
    send_company_alerts,
    send_daily_digests,
    send_instant_alerts,
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
def sent_emails(monkeypatch):
    """Fake send_email - records (to, subject) and always succeeds unless
    the test explicitly makes it fail."""
    calls = []

    def _fake_send(to, subject, html, text, headers=None):
        # `headers` carries List-Unsubscribe, which Gmail requires on bulk mail.
        # Recorded rather than ignored so a test can assert it is present.
        calls.append({"to": to, "subject": subject, "html": html, "text": text, "headers": headers})
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
    plan.features = {"daily_digest": True, "instant_alerts": False, "dream_companies_limit": 1}
    return plan


@pytest.fixture
def pro_plan(db_session: Session):
    plan = models.Plan(
        key=f"pro-notif-test-{uuid.uuid4()}",
        price_paise=4900,
        billing="monthly",
        features={"daily_digest": True, "instant_alerts": True, "dream_companies_limit": None},
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
    db_session: Session,
    company: models.Company,
    *,
    first_seen_at: datetime,
    deadline: datetime | None = None,
    posted_at: datetime | None = None,
    category: str | None = None,
    title: str = "Test Opportunity",
    title_normalized: str | None = None,
) -> models.Opportunity:
    opp = models.Opportunity(
        slug=f"notif-test-opp-{uuid.uuid4()}",
        company_id=company.id,
        title=title,
        title_normalized=title_normalized,
        category=category,
        apply_url="https://example.com/apply",
        posted_at=posted_at,
        deadline=deadline,
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


def test_digest_html_escapes_crawled_opportunity_title(db_session, source_and_company) -> None:
    _source, company = source_and_company
    opportunity = _make_opportunity(
        db_session,
        company,
        first_seen_at=datetime.now(timezone.utc),
    )
    opportunity.title = "Research <script> & Development"

    html, _text = notifications_module._render_digest([opportunity])

    assert "Research &lt;script&gt; &amp; Development" in html
    assert ">View &amp; Apply</a>" in html
    assert ">Daily digest</td>" in html
    assert "Research <script>" not in html
    assert "Aspirova" in html
    assert "/account?section=notifications" in html


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
    assert "hackathon_ids" in notification.meta


def test_dream_company_digest_allows_multiple_roles_from_same_company(
    db_session, sent_emails, free_plan, source_and_company
) -> None:
    _source, company = source_and_company
    user = _make_user(db_session)
    now = datetime(2030, 1, 1, 12, tzinfo=timezone.utc)
    older = _make_opportunity(
        db_session,
        company,
        first_seen_at=now - timedelta(minutes=2),
        title="Dream Company Backend Intern",
    )
    newer = _make_opportunity(
        db_session,
        company,
        first_seen_at=now - timedelta(minutes=1),
        title="Dream Company Product Intern",
    )
    db_session.add(models.DreamCompany(user_id=user.id, company_id=company.id))
    db_session.flush()

    send_daily_digests(db_session, now=now)

    notification = db_session.scalar(
        select(models.Notification).where(
            models.Notification.user_id == user.id, models.Notification.type == "digest"
        )
    )
    assert notification.meta == {"opportunity_ids": [newer.id, older.id], "hackathon_ids": []}


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


def test_digest_excludes_stale_dream_company_matches(
    db_session, sent_emails, free_plan, source_and_company
) -> None:
    _source, company = source_and_company
    user = _make_user(db_session)
    now = datetime(2030, 1, 1, 12, tzinfo=timezone.utc)
    stale = _make_opportunity(
        db_session,
        company,
        first_seen_at=now - timedelta(minutes=30),
        posted_at=now - timedelta(days=366),
        category="job",
    )
    db_session.add(models.DreamCompany(user_id=user.id, company_id=company.id))
    db_session.flush()

    result = send_daily_digests(db_session, now=now)

    assert stale.deadline is None
    assert not any(email["to"] == user.email for email in sent_emails)
    assert result["skipped_empty"] >= 1


def test_generic_digest_prioritizes_student_quality_and_keeps_unranked_companies(
    db_session: Session,
) -> None:
    suffix = uuid.uuid4().hex
    now = datetime(2030, 1, 1, 12, tzinfo=timezone.utc)
    since = now - timedelta(hours=1)
    ranked_one = models.Company(
        slug=f"notif-quality-ranked-one-{suffix}",
        name=f"Digest Quality Ranked One {suffix}",
        prestige_rank=1,
    )
    ranked_two = models.Company(
        slug=f"notif-quality-ranked-two-{suffix}",
        name=f"Digest Quality Ranked Two {suffix}",
        prestige_rank=2,
    )
    ranked_five = models.Company(
        slug=f"notif-quality-ranked-five-{suffix}",
        name=f"Digest Quality Ranked Five {suffix}",
        prestige_rank=5,
    )
    unranked = models.Company(
        slug=f"notif-quality-unranked-{suffix}",
        name=f"Digest Quality Unranked {suffix}",
    )

    old_future_deadline_internship = models.Opportunity(
        slug=f"notif-quality-old-future-internship-{suffix}",
        title="Backend Intern",
        title_normalized="backend intern",
        company=ranked_two,
        category="internship",
        apply_url=f"https://example.com/notif-quality/old-future/{suffix}",
        posted_at=now - timedelta(days=500),
        deadline=now + timedelta(days=10),
        first_seen_at=now - timedelta(minutes=12),
        last_seen_at=now,
        status="active",
    )
    ranked_internship = models.Opportunity(
        slug=f"notif-quality-ranked-internship-{suffix}",
        title="Software Engineering Intern",
        title_normalized="software engineering intern",
        company=ranked_five,
        category="internship",
        apply_url=f"https://example.com/notif-quality/ranked-internship/{suffix}",
        posted_at=now - timedelta(days=10),
        first_seen_at=now - timedelta(minutes=10),
        last_seen_at=now,
        status="active",
    )
    unranked_internship = models.Opportunity(
        slug=f"notif-quality-unranked-internship-{suffix}",
        title="Product Intern",
        title_normalized="product intern",
        company=unranked,
        category="internship",
        apply_url=f"https://example.com/notif-quality/unranked-internship/{suffix}",
        posted_at=now - timedelta(days=5),
        first_seen_at=now - timedelta(minutes=1),
        last_seen_at=now,
        status="active",
    )
    newer_ranked_job = models.Opportunity(
        slug=f"notif-quality-newer-job-{suffix}",
        title="Software Engineer",
        title_normalized="software engineer",
        company=ranked_one,
        category="job",
        apply_url=f"https://example.com/notif-quality/newer-job/{suffix}",
        posted_at=now - timedelta(days=5),
        first_seen_at=now - timedelta(minutes=2),
        last_seen_at=now,
        status="active",
    )
    older_ranked_job = models.Opportunity(
        slug=f"notif-quality-older-job-{suffix}",
        title="Backend Engineer",
        title_normalized="backend engineer",
        company=ranked_one,
        category="job",
        apply_url=f"https://example.com/notif-quality/older-job/{suffix}",
        posted_at=now - timedelta(days=5),
        first_seen_at=now - timedelta(minutes=20),
        last_seen_at=now,
        status="active",
    )
    senior_job = models.Opportunity(
        slug=f"notif-quality-senior-{suffix}",
        title="Senior Staff Engineer",
        title_normalized="senior staff engineer",
        company=ranked_one,
        category="job",
        apply_url=f"https://example.com/notif-quality/senior/{suffix}",
        posted_at=now - timedelta(days=5),
        first_seen_at=now - timedelta(minutes=1),
        last_seen_at=now,
        status="active",
    )
    stale_internship = models.Opportunity(
        slug=f"notif-quality-stale-{suffix}",
        title="Stale Intern",
        title_normalized="stale intern",
        company=ranked_one,
        category="internship",
        apply_url=f"https://example.com/notif-quality/stale/{suffix}",
        posted_at=now - timedelta(days=500),
        first_seen_at=now,
        last_seen_at=now,
        status="active",
    )
    competition = models.Opportunity(
        slug=f"notif-quality-competition-{suffix}",
        title="Fresh Competition",
        title_normalized="fresh competition",
        company=ranked_one,
        category="competition",
        apply_url=f"https://example.com/notif-quality/competition/{suffix}",
        posted_at=now - timedelta(days=5),
        first_seen_at=now,
        last_seen_at=now,
        status="active",
    )
    db_session.add_all(
        [
            ranked_one,
            ranked_two,
            ranked_five,
            unranked,
            old_future_deadline_internship,
            ranked_internship,
            unranked_internship,
            newer_ranked_job,
            older_ranked_job,
            senior_job,
            stale_internship,
            competition,
        ]
    )
    db_session.flush()

    opportunities = notifications_module._generic_recent_opportunities(
        db_session,
        since,
        limit=5,
        now=now,
    )

    assert [opportunity.slug for opportunity in opportunities] == [
        old_future_deadline_internship.slug,
        ranked_internship.slug,
        unranked_internship.slug,
        newer_ranked_job.slug,
    ]
    assert len({opportunity.company_id for opportunity in opportunities}) == len(opportunities)
    assert senior_job.slug not in {opportunity.slug for opportunity in opportunities}
    assert older_ranked_job.slug not in {opportunity.slug for opportunity in opportunities}
    assert stale_internship.slug not in {opportunity.slug for opportunity in opportunities}
    assert competition.slug not in {opportunity.slug for opportunity in opportunities}


def test_generic_digest_reserves_ranked_company_jobs_over_unranked_internships(
    db_session: Session,
) -> None:
    suffix = uuid.uuid4().hex
    now = datetime(2030, 1, 1, 12, tzinfo=timezone.utc)
    since = now - timedelta(hours=1)
    ranked_one = models.Company(
        slug=f"notif-reserve-ranked-one-{suffix}",
        name=f"Digest Reserve Ranked One {suffix}",
        prestige_rank=10,
    )
    ranked_two = models.Company(
        slug=f"notif-reserve-ranked-two-{suffix}",
        name=f"Digest Reserve Ranked Two {suffix}",
        prestige_rank=20,
    )
    ranked_job_one = models.Opportunity(
        slug=f"notif-reserve-ranked-job-one-{suffix}",
        title="Software Engineer",
        title_normalized="software engineer",
        company=ranked_one,
        category="job",
        apply_url=f"https://example.com/notif-reserve/ranked-job-one/{suffix}",
        posted_at=now - timedelta(days=5),
        first_seen_at=now - timedelta(minutes=20),
        last_seen_at=now,
        status="active",
    )
    ranked_job_two = models.Opportunity(
        slug=f"notif-reserve-ranked-job-two-{suffix}",
        title="Backend Engineer",
        title_normalized="backend engineer",
        company=ranked_two,
        category="job",
        apply_url=f"https://example.com/notif-reserve/ranked-job-two/{suffix}",
        posted_at=now - timedelta(days=5),
        first_seen_at=now - timedelta(minutes=19),
        last_seen_at=now,
        status="active",
    )
    unranked_internships = []
    for index in range(5):
        company = models.Company(
            slug=f"notif-reserve-unranked-{index}-{suffix}",
            name=f"Digest Reserve Unranked {index} {suffix}",
        )
        unranked_internships.append(
            models.Opportunity(
                slug=f"notif-reserve-unranked-internship-{index}-{suffix}",
                title="Software Engineering Intern",
                title_normalized="software engineering intern",
                company=company,
                category="internship",
                apply_url=f"https://example.com/notif-reserve/unranked-{index}/{suffix}",
                posted_at=now - timedelta(days=5),
                first_seen_at=now - timedelta(minutes=index + 1),
                last_seen_at=now,
                status="active",
            )
        )
    db_session.add_all([ranked_one, ranked_two, ranked_job_one, ranked_job_two])
    db_session.add_all(unranked_internships)
    db_session.flush()

    opportunities = notifications_module._generic_recent_opportunities(
        db_session,
        since,
        limit=5,
        now=now,
    )

    slugs = [opportunity.slug for opportunity in opportunities]
    assert ranked_job_one.slug in slugs
    assert ranked_job_two.slug in slugs
    assert len([slug for slug in slugs if "unranked-internship" in slug]) == 3
    assert len({opportunity.company_id for opportunity in opportunities}) == len(opportunities)
    assert slugs == [
        unranked_internships[0].slug,
        unranked_internships[1].slug,
        unranked_internships[2].slug,
        ranked_job_one.slug,
        ranked_job_two.slug,
    ]


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
    db_session.add(
        models.DreamCompany(
            user_id=user.id,
            company_id=company.id,
            created_at=datetime.now(timezone.utc) - timedelta(days=7),
        )
    )
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
    db_session.add(
        models.DreamCompany(
            user_id=user.id,
            company_id=company.id,
            created_at=datetime.now(timezone.utc) - timedelta(days=7),
        )
    )
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
    db_session.add(
        models.DreamCompany(
            user_id=user.id,
            company_id=company.id,
            created_at=datetime.now(timezone.utc) - timedelta(days=7),
        )
    )
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


def test_instant_alert_includes_opportunity_first_seen_ten_hours_ago(
    db_session, sent_emails, pro_plan, source_and_company
) -> None:
    _source, company = source_and_company
    user = _make_user(db_session)
    db_session.add(models.Subscription(user_id=user.id, plan_id=pro_plan.id, status="active"))
    old_time = datetime.now(timezone.utc) - timedelta(hours=10)
    _make_opportunity(db_session, company, first_seen_at=old_time)
    db_session.add(
        models.DreamCompany(
            user_id=user.id,
            company_id=company.id,
            created_at=datetime.now(timezone.utc) - timedelta(days=7),
        )
    )
    db_session.flush()

    send_instant_alerts(db_session)

    assert any(e["to"] == user.email for e in sent_emails)


def test_instant_alert_excludes_stale_dream_company_matches(
    db_session, sent_emails, pro_plan, source_and_company
) -> None:
    _source, company = source_and_company
    user = _make_user(db_session)
    now = datetime(2030, 1, 1, 12, tzinfo=timezone.utc)
    db_session.add(models.Subscription(user_id=user.id, plan_id=pro_plan.id, status="active"))
    stale = _make_opportunity(
        db_session,
        company,
        first_seen_at=now - timedelta(minutes=30),
        posted_at=now - timedelta(days=366),
        category="job",
    )
    db_session.add(
        models.DreamCompany(
            user_id=user.id,
            company_id=company.id,
            created_at=datetime.now(timezone.utc) - timedelta(days=7),
        )
    )
    db_session.flush()

    send_instant_alerts(db_session, now=now)

    assert stale.deadline is None
    assert not any(e["to"] == user.email for e in sent_emails)


def test_failed_send_records_failed_status_not_sent(
    db_session, monkeypatch, pro_plan, source_and_company
) -> None:
    monkeypatch.setattr(
        notifications_module, "send_email", lambda to, subject, html, text, headers=None: False
    )
    _source, company = source_and_company
    user = _make_user(db_session)
    db_session.add(models.Subscription(user_id=user.id, plan_id=pro_plan.id, status="active"))
    _make_opportunity(db_session, company, first_seen_at=datetime.now(timezone.utc))
    db_session.add(
        models.DreamCompany(
            user_id=user.id,
            company_id=company.id,
            created_at=datetime.now(timezone.utc) - timedelta(days=7),
        )
    )
    db_session.flush()

    result = send_instant_alerts(db_session)

    assert result["failed"] >= 1
    notification = db_session.scalar(
        select(models.Notification).where(models.Notification.user_id == user.id)
    )
    assert notification.status == "failed"
    assert notification.sent_at is None


def _follow(session, user, company, now, roles=None, **kwargs):
    follow = models.DreamCompany(
        user_id=user.id,
        company_id=company.id,
        roles=roles or [],
        created_at=kwargs.pop("created_at", now - timedelta(days=4)),
        **kwargs,
    )
    session.add(follow)
    session.flush()
    return follow


def _alert_rows(session, user):
    return list(
        session.scalars(
            select(models.Notification).where(
                models.Notification.user_id == user.id, models.Notification.type == "instant_alert"
            )
        ).all()
    )


@pytest.mark.parametrize("roles", [["software"], []], ids=["software", "all-domains"])
@pytest.mark.parametrize(
    "title,expected",
    [
        ("Senior Software Engineer", False),
        ("Sr. Software Engineer", False),
        ("Staff Software Engineer", False),
        ("Staff+ Software Engineer, Backend", False),
        ("Principal Software Engineer", False),
        ("Director of Software Engineering", False),
        ("Software VP", False),
        ("Head of Software", False),
        ("Software Engineer - New Grad (2027 Start)", True),
        ("Member of Technical Staff - New Grad (2027 Start)", True),
        ("Member of Technical Staff", True),
        ("Senior Software Engineer, Master's New Graduate | 0-2 Years Experience", True),
        ("Software Engineering Manager", True),
        ("Lead Software Engineer", True),
    ],
)
def test_company_alert_clearly_senior_job_rule(
    db_session, sent_emails, free_plan, source_and_company, roles, title, expected
):
    now = datetime.now(timezone.utc)
    _, company = source_and_company
    user = _make_user(db_session)
    _follow(db_session, user, company, now, roles)
    opportunity = _make_opportunity(
        db_session, company, first_seen_at=now - timedelta(hours=1), title=title, category="job"
    )
    assert opportunity.title_normalized is None

    send_company_alerts(db_session, now=now)

    emails = [email for email in sent_emails if email["to"] == user.email]
    rows = _alert_rows(db_session, user)
    assert len(emails) == int(expected)
    assert {row.opportunity_id for row in rows} == ({opportunity.id} if expected else set())
    assert all(row.status == "sent" for row in rows)


@pytest.mark.parametrize(
    "title",
    [
        "Associate Product Manager",
        "Marketing Executive",
        "Staff Accountant",
        "Staff Auditor",
        "Staff Writer",
        "Staff Nurse",
    ],
)
def test_all_domain_company_alert_keeps_entry_level_job_titles(
    db_session, sent_emails, free_plan, source_and_company, title
):
    now = datetime.now(timezone.utc)
    _, company = source_and_company
    user = _make_user(db_session)
    _follow(db_session, user, company, now)
    opportunity = _make_opportunity(
        db_session, company, first_seen_at=now - timedelta(hours=1), title=title, category="job"
    )

    send_company_alerts(db_session, now=now)

    assert len([email for email in sent_emails if email["to"] == user.email]) == 1
    assert {row.opportunity_id for row in _alert_rows(db_session, user)} == {opportunity.id}


@pytest.mark.parametrize("roles", [["software"], []], ids=["software", "all-domains"])
@pytest.mark.parametrize("category", ["internship", "scholarship", None])
def test_company_alert_senior_title_is_kept_outside_job_category(
    db_session, sent_emails, free_plan, source_and_company, roles, category
):
    now = datetime.now(timezone.utc)
    _, company = source_and_company
    user = _make_user(db_session)
    _follow(db_session, user, company, now, roles)
    opportunity = _make_opportunity(
        db_session,
        company,
        first_seen_at=now - timedelta(hours=1),
        title="Senior Software Engineer",
        category=category,
    )

    send_company_alerts(db_session, now=now)

    assert opportunity.category == category
    assert len([email for email in sent_emails if email["to"] == user.email]) == 1
    assert {row.opportunity_id for row in _alert_rows(db_session, user)} == {opportunity.id}


@pytest.mark.parametrize("roles", [["software"], []], ids=["software", "all-domains"])
def test_digest_and_weekly_follow_matches_exclude_clearly_senior_jobs(
    db_session, source_and_company, roles
):
    from pipeline.weekly_report import _recent_dream_company_matches

    now = datetime.now(timezone.utc)
    _, company = source_and_company
    user = _make_user(db_session)
    _follow(db_session, user, company, now, roles)
    _make_opportunity(
        db_session,
        company,
        first_seen_at=now - timedelta(hours=1),
        title="Senior Software Engineer",
        category="job",
    )
    early_career = _make_opportunity(
        db_session,
        company,
        first_seen_at=now - timedelta(hours=2),
        title="Software Engineer - New Grad",
        category="job",
    )
    since = now - timedelta(days=1)

    digest = notifications_module._dream_company_opportunities(db_session, user.id, since, now)
    weekly = _recent_dream_company_matches(db_session, user.id, since, now)

    assert [opportunity.id for opportunity in digest] == [early_career.id]
    assert [opportunity.id for opportunity in weekly] == [early_career.id]


@pytest.mark.parametrize(
    "roles,expected",
    [
        (["software"], {"Software Engineer Intern"}),
        (
            [],
            {
                "Software Engineer Intern",
                "Sales Intern",
                "Mechanical Engineering Intern",
                "Researcher Intern",
            },
        ),
        (["software", "sales"], {"Software Engineer Intern", "Sales Intern"}),
        (["engineering"], {"Mechanical Engineering Intern"}),
        (["research"], {"Researcher Intern"}),
    ],
)
def test_company_alert_domains_and_company_isolation(
    db_session, sent_emails, free_plan, source_and_company, roles, expected
):
    now = datetime.now(timezone.utc)
    _, company = source_and_company
    other = models.Company(slug=f"alert-other-{uuid.uuid4()}", name="Other")
    db_session.add(other)
    db_session.flush()
    user = _make_user(db_session)
    _follow(db_session, user, company, now, roles)
    opportunities = [
        _make_opportunity(db_session, company, first_seen_at=now - timedelta(hours=1), title=title)
        for title in [
            "Software Engineer Intern",
            "Sales Intern",
            "Mechanical Engineering Intern",
            "Researcher Intern",
        ]
    ]
    other_opp = _make_opportunity(db_session, other, first_seen_at=now, title="Software Intern")
    send_company_alerts(db_session, now=now)
    rows = _alert_rows(db_session, user)
    titles = {o.title for o in opportunities if o.id in {row.opportunity_id for row in rows}}
    assert titles == expected
    assert other_opp.id not in {row.opportunity_id for row in rows}
    assert len([email for email in sent_emails if email["to"] == user.email]) == 1


def test_company_alert_groups_companies_records_beyond_cap_and_deduplicates(
    db_session, sent_emails, pro_plan, source_and_company
):
    now = datetime.now(timezone.utc)
    _, company = source_and_company
    other = models.Company(slug=f"alert-group-{uuid.uuid4()}", name="Other")
    db_session.add(other)
    db_session.flush()
    user = _make_user(db_session)
    db_session.add(models.Subscription(user_id=user.id, plan_id=pro_plan.id, status="active"))
    opportunities = []
    for followed in [company, other]:
        _follow(db_session, user, followed, now)
        opportunities.extend(
            _make_opportunity(
                db_session,
                followed,
                first_seen_at=now - timedelta(hours=1),
                title=f"Software Intern {index}",
                category="internship",
            )
            for index in range(6)
        )
    send_company_alerts(db_session, now=now)
    emails = [email for email in sent_emails if email["to"] == user.email]
    assert len(emails) == 1
    assert emails[0]["html"].count(">View &amp; Apply</a>") == 8
    assert emails[0]["headers"]["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert {row.opportunity_id for row in _alert_rows(db_session, user)} == {
        o.id for o in opportunities
    }
    send_company_alerts(db_session, now=now)
    assert len([email for email in sent_emails if email["to"] == user.email]) == 1
    assert len(_alert_rows(db_session, user)) == 12


@pytest.mark.parametrize(
    "age_hours,follow_age_hours,expected",
    [(2, 1, False), (73, 100, False), (10, 24, True), (-1, 24, False), (1, 1, False)],
)
def test_company_alert_time_guards(
    db_session, sent_emails, free_plan, source_and_company, age_hours, follow_age_hours, expected
):
    now = datetime.now(timezone.utc)
    _, company = source_and_company
    user = _make_user(db_session)
    _follow(db_session, user, company, now, created_at=now - timedelta(hours=follow_age_hours))
    _make_opportunity(db_session, company, first_seen_at=now - timedelta(hours=age_hours))
    send_company_alerts(db_session, now=now)
    assert bool([email for email in sent_emails if email["to"] == user.email]) is expected


def test_free_company_alert_daily_cap_and_next_utc_day(
    db_session, sent_emails, free_plan, source_and_company
):
    now = datetime.now(timezone.utc).replace(hour=23, minute=50)
    _, company = source_and_company
    user = _make_user(db_session)
    _follow(db_session, user, company, now)
    first = _make_opportunity(db_session, company, first_seen_at=now - timedelta(hours=1))
    send_instant_alerts(db_session, now=now)
    assert not [email for email in sent_emails if email["to"] == user.email]
    send_company_alerts(db_session, now=now)
    second = _make_opportunity(db_session, company, first_seen_at=now)
    send_company_alerts(db_session, now=now)
    assert len([email for email in sent_emails if email["to"] == user.email]) == 1
    assert {row.opportunity_id for row in _alert_rows(db_session, user)} == {first.id}
    send_company_alerts(db_session, now=now + timedelta(minutes=20))
    assert len([email for email in sent_emails if email["to"] == user.email]) == 2
    assert {row.opportunity_id for row in _alert_rows(db_session, user)} == {first.id, second.id}


def test_paid_company_alert_not_daily_capped(db_session, sent_emails, pro_plan, source_and_company):
    now = datetime.now(timezone.utc)
    _, company = source_and_company
    user = _make_user(db_session)
    db_session.add(models.Subscription(user_id=user.id, plan_id=pro_plan.id, status="active"))
    _follow(db_session, user, company, now)
    _make_opportunity(db_session, company, first_seen_at=now - timedelta(hours=1))
    send_instant_alerts(db_session, now=now)
    _make_opportunity(db_session, company, first_seen_at=now)
    send_company_alerts(db_session, now=now)
    assert len([email for email in sent_emails if email["to"] == user.email]) == 2


def test_downgraded_user_only_oldest_follow_is_served(
    db_session, sent_emails, free_plan, source_and_company
):
    now = datetime.now(timezone.utc)
    _, company = source_and_company
    other = models.Company(slug=f"alert-downgrade-{uuid.uuid4()}", name="Other")
    db_session.add(other)
    db_session.flush()
    user = _make_user(db_session)
    _follow(db_session, user, company, now, created_at=now - timedelta(days=2))
    _follow(db_session, user, other, now, created_at=now - timedelta(days=1))
    expected = _make_opportunity(db_session, company, first_seen_at=now - timedelta(hours=1))
    _make_opportunity(db_session, other, first_seen_at=now - timedelta(hours=1))
    send_company_alerts(db_session, now=now)
    assert {row.opportunity_id for row in _alert_rows(db_session, user)} == {expected.id}


def test_opted_out_company_alert_is_not_sent(
    db_session, sent_emails, free_plan, source_and_company
):
    now = datetime.now(timezone.utc)
    _, company = source_and_company
    user = _make_user(db_session)
    user.notification_prefs = {"instant_alerts": False}
    _follow(db_session, user, company, now)
    _make_opportunity(db_session, company, first_seen_at=now)
    send_company_alerts(db_session, now=now)
    assert not [email for email in sent_emails if email["to"] == user.email]
    assert _alert_rows(db_session, user) == []


@pytest.mark.parametrize("raises", [False, True])
def test_failed_company_alert_retries_all_rows(
    db_session, sent_emails, free_plan, source_and_company, monkeypatch, raises
):
    now = datetime.now(timezone.utc)
    _, company = source_and_company
    user = _make_user(db_session)
    _follow(db_session, user, company, now)
    opportunity = _make_opportunity(db_session, company, first_seen_at=now)
    db_session.commit()
    original = notifications_module.send_email

    def fail(*args, **kwargs):
        if raises:
            raise RuntimeError("simulated email failure")
        return False

    monkeypatch.setattr(notifications_module, "send_email", fail)
    send_company_alerts(db_session, now=now)
    rows = _alert_rows(db_session, user)
    assert len(rows) == 1 and rows[0].status == "failed" and rows[0].sent_at is None
    monkeypatch.setattr(notifications_module, "send_email", original)
    send_company_alerts(db_session, now=now)
    assert {row.status for row in _alert_rows(db_session, user)} == {"sent", "failed"}
    assert all(row.opportunity_id == opportunity.id for row in _alert_rows(db_session, user))
    assert len([email for email in sent_emails if email["to"] == user.email]) == 1


def test_digest_and_weekly_follow_matches_respect_domains(
    db_session, sent_emails, free_plan, source_and_company
):
    from pipeline.weekly_report import _recent_dream_company_matches

    now = datetime.now(timezone.utc)
    _, company = source_and_company
    user = _make_user(db_session)
    _follow(db_session, user, company, now, ["software"])
    software = _make_opportunity(
        db_session, company, first_seen_at=now, title="Software Engineer Intern"
    )
    _make_opportunity(db_session, company, first_seen_at=now, title="Sales Intern")
    since = now - timedelta(days=1)
    assert [
        o.id
        for o in notifications_module._dream_company_opportunities(db_session, user.id, since, now)
    ] == [software.id]
    assert [o.id for o in _recent_dream_company_matches(db_session, user.id, since, now)] == [
        software.id
    ]
    send_daily_digests(db_session, now=now)
    digest = db_session.scalar(
        select(models.Notification).where(
            models.Notification.user_id == user.id, models.Notification.type == "digest"
        )
    )
    assert digest.meta["opportunity_ids"] == [software.id]


@pytest.mark.parametrize(
    "excluded", ["hidden", "closed", "experienced", "school", "deadline", "retired"]
)
def test_company_alert_excludes_unusable_listings(
    db_session, sent_emails, free_plan, source_and_company, excluded
):
    now = datetime.now(timezone.utc)
    _, company = source_and_company
    user = _make_user(db_session)
    _follow(db_session, user, company, now)
    opportunity = _make_opportunity(db_session, company, first_seen_at=now)
    if excluded == "hidden":
        opportunity.is_hidden = True
    elif excluded == "closed":
        opportunity.status = "closed"
    elif excluded == "experienced":
        from core.eligibility import ELIGIBLE_EXPERIENCED_ONLY_META_KEY

        opportunity.meta = {ELIGIBLE_EXPERIENCED_ONLY_META_KEY: True}
    elif excluded == "school":
        opportunity.meta = {"eligibility": ["School Students"]}
    elif excluded == "deadline":
        opportunity.deadline = now - timedelta(seconds=1)
    else:
        opportunity.closed_at = now - timedelta(days=15)
    db_session.flush()
    send_company_alerts(db_session, now=now)
    assert _alert_rows(db_session, user) == []
    assert not [email for email in sent_emails if email["to"] == user.email]


def test_closing_soon_alert_includes_only_bookmarked_opportunities_in_window(
    db_session, sent_emails, source_and_company
) -> None:
    _source, company = source_and_company
    now = datetime(2026, 7, 11, 12, tzinfo=timezone.utc)
    user = _make_user(db_session)
    closing_soon = _make_opportunity(
        db_session,
        company,
        first_seen_at=now,
        deadline=now + timedelta(days=2),
    )
    closing_later = _make_opportunity(
        db_session,
        company,
        first_seen_at=now,
        deadline=now + timedelta(days=10),
    )
    already_closed = _make_opportunity(
        db_session,
        company,
        first_seen_at=now,
        deadline=now - timedelta(hours=1),
    )
    not_bookmarked = _make_opportunity(
        db_session,
        company,
        first_seen_at=now,
        deadline=now + timedelta(days=1),
    )
    inactive = _make_opportunity(
        db_session,
        company,
        first_seen_at=now,
        deadline=now + timedelta(days=1),
    )
    inactive.status = "closed"
    db_session.add_all(
        [
            models.Bookmark(user_id=user.id, opportunity_id=closing_soon.id),
            models.Bookmark(user_id=user.id, opportunity_id=closing_later.id),
            models.Bookmark(user_id=user.id, opportunity_id=already_closed.id),
            models.Bookmark(user_id=user.id, opportunity_id=inactive.id),
        ]
    )
    db_session.flush()

    result = send_closing_soon_alerts(db_session, now=now)

    emails_to_user = [email for email in sent_emails if email["to"] == user.email]
    assert len(emails_to_user) == 1
    assert emails_to_user[0]["subject"] == "'Test Opportunity' closes in 2 days"
    assert closing_soon.deadline.strftime("%d %b %Y") in emails_to_user[0]["html"]
    assert closing_soon.apply_url in emails_to_user[0]["html"]
    assert result["users_notified"] >= 1
    assert result["opportunities"] >= 1

    notification_rows = list(
        db_session.scalars(
            select(models.Notification).where(
                models.Notification.user_id == user.id,
                models.Notification.type == "closing_soon",
            )
        ).all()
    )
    assert len(notification_rows) == 1
    assert notification_rows[0].opportunity_id == closing_soon.id
    excluded_ids = {closing_later.id, already_closed.id, not_bookmarked.id, inactive.id}
    assert excluded_ids.isdisjoint(row.opportunity_id for row in notification_rows)
    assert notification_rows[0].status == "sent"
    assert notification_rows[0].sent_at is not None


def test_closing_soon_alert_is_deduplicated_per_opportunity(
    db_session, sent_emails, source_and_company
) -> None:
    _source, company = source_and_company
    now = datetime(2026, 7, 11, 12, tzinfo=timezone.utc)
    user = _make_user(db_session)
    opportunity = _make_opportunity(
        db_session,
        company,
        first_seen_at=now,
        deadline=now + timedelta(days=2),
    )
    db_session.add(models.Bookmark(user_id=user.id, opportunity_id=opportunity.id))
    db_session.flush()

    send_closing_soon_alerts(db_session, now=now)
    send_closing_soon_alerts(db_session, now=now)

    assert sum(1 for email in sent_emails if email["to"] == user.email) == 1
    notifications = list(
        db_session.scalars(
            select(models.Notification).where(
                models.Notification.user_id == user.id,
                models.Notification.opportunity_id == opportunity.id,
                models.Notification.type == "closing_soon",
            )
        ).all()
    )
    assert len(notifications) == 1


def test_closing_soon_keeps_old_listing_with_future_deadline(
    db_session, sent_emails, source_and_company
) -> None:
    _source, company = source_and_company
    now = datetime(2030, 1, 1, 12, tzinfo=timezone.utc)
    user = _make_user(db_session)
    opportunity = _make_opportunity(
        db_session,
        company,
        first_seen_at=now,
        posted_at=now - timedelta(days=500),
        deadline=now + timedelta(days=2),
    )
    db_session.add(models.Bookmark(user_id=user.id, opportunity_id=opportunity.id))
    db_session.flush()

    send_closing_soon_alerts(db_session, now=now)

    assert any(email["to"] == user.email for email in sent_emails)


def test_closing_soon_alert_respects_notification_preference(
    db_session, sent_emails, source_and_company
) -> None:
    _source, company = source_and_company
    now = datetime(2026, 7, 11, 12, tzinfo=timezone.utc)
    user = _make_user(db_session)
    user.notification_prefs = {"closing_soon": False}
    opportunity = _make_opportunity(
        db_session,
        company,
        first_seen_at=now,
        deadline=now + timedelta(days=2),
    )
    db_session.add(models.Bookmark(user_id=user.id, opportunity_id=opportunity.id))
    db_session.flush()

    send_closing_soon_alerts(db_session, now=now)

    assert not any(email["to"] == user.email for email in sent_emails)
    assert (
        db_session.scalar(
            select(models.Notification.id).where(
                models.Notification.user_id == user.id,
                models.Notification.type == "closing_soon",
            )
        )
        is None
    )


def test_closing_soon_failed_send_records_failed_status(
    db_session, monkeypatch, source_and_company
) -> None:
    monkeypatch.setattr(notifications_module, "send_email", lambda to, subject, html, text: False)
    _source, company = source_and_company
    now = datetime(2026, 7, 11, 12, tzinfo=timezone.utc)
    user = _make_user(db_session)
    opportunity = _make_opportunity(
        db_session,
        company,
        first_seen_at=now,
        deadline=now + timedelta(days=2),
    )
    db_session.add(models.Bookmark(user_id=user.id, opportunity_id=opportunity.id))
    db_session.flush()

    result = send_closing_soon_alerts(db_session, now=now)

    notification = db_session.scalar(
        select(models.Notification).where(
            models.Notification.user_id == user.id,
            models.Notification.opportunity_id == opportunity.id,
            models.Notification.type == "closing_soon",
        )
    )
    assert result["failed"] >= 1
    assert notification.status == "failed"
    assert notification.sent_at is None


@pytest.mark.parametrize("status", ["applied", "interviewing", "offer", "archived"])
def test_closing_soon_sends_saved_and_skips_other_stages(
    db_session, sent_emails, source_and_company, status
) -> None:
    _source, company = source_and_company
    now = datetime.now(timezone.utc)
    user = _make_user(db_session)
    saved = _make_opportunity(
        db_session,
        company,
        first_seen_at=now,
        deadline=now + timedelta(days=2),
        title="Still saved",
    )
    progressed = _make_opportunity(
        db_session,
        company,
        first_seen_at=now,
        deadline=now + timedelta(days=1),
        title="Already handled",
    )
    db_session.add_all(
        [
            models.Bookmark(user_id=user.id, opportunity_id=saved.id, status="saved"),
            models.Bookmark(user_id=user.id, opportunity_id=progressed.id, status=status),
        ]
    )
    db_session.flush()

    send_closing_soon_alerts(db_session, now=now)

    emails = [email for email in sent_emails if email["to"] == user.email]
    assert len(emails) == 1
    assert saved.title in emails[0]["text"]
    assert progressed.title not in emails[0]["text"]
    notified_ids = set(
        db_session.scalars(
            select(models.Notification.opportunity_id).where(
                models.Notification.user_id == user.id,
                models.Notification.type == "closing_soon",
            )
        )
    )
    assert notified_ids == {saved.id}
