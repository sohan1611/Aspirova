import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from api import middleware
from api.deps import get_db
from api.filters import is_stale_opportunity
from api.main import app
from core import models
from core.eligibility import ELIGIBLE_EXPERIENCED_ONLY_META_KEY


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
def client(db_session: Session, monkeypatch):
    monkeypatch.setattr(middleware, "get_redis", lambda: None)
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def feed_rows(db_session: Session):
    suffix = str(uuid.uuid4())
    seen_at = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    location_token = f"Filterville-{suffix}"
    company_a = models.Company(
        slug=f"feed-filter-alpha-{suffix}",
        name=f"Feed Filter Alpha {suffix}",
    )
    company_b = models.Company(
        slug=f"feed-filter-beta-{suffix}",
        name=f"Feed Filter Beta {suffix}",
    )
    opportunities = [
        models.Opportunity(
            slug=f"feed-filter-alpha-internship-{suffix}",
            title="Alpha internship",
            company=company_a,
            category="internship",
            location=f"{location_token}, North",
            apply_url=f"https://example.com/feed-filter/alpha-internship/{suffix}",
            status="active",
            last_seen_at=seen_at,
        ),
        models.Opportunity(
            slug=f"feed-filter-alpha-job-{suffix}",
            title="Alpha job",
            company=company_a,
            category="job",
            location=f"Elsewhere-{suffix}",
            apply_url=f"https://example.com/feed-filter/alpha-job/{suffix}",
            status="active",
            last_seen_at=seen_at,
        ),
        models.Opportunity(
            slug=f"feed-filter-beta-internship-{suffix}",
            title="Beta internship",
            company=company_b,
            category="internship",
            location=f"{location_token}, South",
            apply_url=f"https://example.com/feed-filter/beta-internship/{suffix}",
            status="active",
            last_seen_at=seen_at,
        ),
    ]
    db_session.add_all([company_a, company_b, *opportunities])
    db_session.flush()
    return company_a, company_b, opportunities, location_token, suffix


def test_feed_company_slug_and_name_filters_narrow_results(client: TestClient, feed_rows) -> None:
    company_a, _company_b, opportunities, _location_token, suffix = feed_rows
    expected_slugs = {opportunities[0].slug, opportunities[1].slug}

    by_slug = client.get("/feed", params={"company": company_a.slug, "limit": 10}).json()
    by_name = client.get("/feed", params={"company": f"Alpha {suffix}", "limit": 10}).json()

    assert by_slug["total"] == 2
    assert {item["slug"] for item in by_slug["items"]} == expected_slugs
    assert by_name["total"] == 2
    assert {item["slug"] for item in by_name["items"]} == expected_slugs


def test_feed_company_filter_accepts_repeated_values_as_or(
    client: TestClient,
    feed_rows,
) -> None:
    company_a, company_b, opportunities, _location_token, _suffix = feed_rows

    body = client.get(
        "/feed",
        params=[
            ("company", company_a.slug),
            ("company", company_b.slug),
            ("limit", "10"),
        ],
    ).json()

    assert body["total"] == 3
    assert {item["slug"] for item in body["items"]} == {
        opportunity.slug for opportunity in opportunities
    }


def test_feed_location_filter_narrows_results(client: TestClient, feed_rows) -> None:
    _company_a, _company_b, opportunities, location_token, _suffix = feed_rows

    body = client.get("/feed", params={"location": location_token, "limit": 10}).json()

    assert body["total"] == 2
    assert {item["slug"] for item in body["items"]} == {
        opportunities[0].slug,
        opportunities[2].slug,
    }


def test_feed_location_filter_accepts_repeated_values_as_or(
    client: TestClient,
    feed_rows,
) -> None:
    _company_a, _company_b, opportunities, location_token, _suffix = feed_rows

    body = client.get(
        "/feed",
        params=[
            ("location", f"{location_token}, North"),
            ("location", f"{location_token}, South"),
            ("limit", "10"),
        ],
    ).json()

    assert body["total"] == 2
    assert {item["slug"] for item in body["items"]} == {
        opportunities[0].slug,
        opportunities[2].slug,
    }


def test_feed_blank_company_and_location_filters_are_ignored(client: TestClient, feed_rows) -> None:
    baseline = client.get("/feed", params={"limit": 1}).json()
    blank_filters = client.get(
        "/feed",
        params={"company": "   ", "location": "\t ", "limit": 1},
    ).json()

    assert blank_filters == baseline


def test_feed_early_experience_filter_excludes_senior_titles(
    client: TestClient,
    db_session: Session,
) -> None:
    suffix = uuid.uuid4().hex
    seen_at = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    location_token = f"EarlyCareerFilterville-{suffix}"
    company = models.Company(
        slug=f"early-career-filter-company-{suffix}",
        name=f"Early Career Filter Company {suffix}",
    )
    senior = models.Opportunity(
        slug=f"early-career-filter-senior-{suffix}",
        title="Senior Software Engineer",
        title_normalized="senior software engineer",
        company=company,
        category="job",
        location=location_token,
        apply_url=f"https://example.com/early-career-filter/senior/{suffix}",
        status="active",
        last_seen_at=seen_at,
    )
    engineer = models.Opportunity(
        slug=f"early-career-filter-engineer-{suffix}",
        title="Software Engineer",
        title_normalized="software engineer",
        company=company,
        category="job",
        location=location_token,
        apply_url=f"https://example.com/early-career-filter/engineer/{suffix}",
        status="active",
        last_seen_at=seen_at,
    )
    internship = models.Opportunity(
        slug=f"early-career-filter-internship-{suffix}",
        title="Software Engineering Intern",
        title_normalized="software engineering intern",
        company=company,
        category="internship",
        location=location_token,
        apply_url=f"https://example.com/early-career-filter/internship/{suffix}",
        status="active",
        last_seen_at=seen_at,
    )
    db_session.add_all([company, senior, engineer, internship])
    db_session.flush()

    all_levels = client.get(
        "/feed",
        params={"location": location_token, "limit": 10},
    ).json()
    early_career = client.get(
        "/feed",
        params={"experience": "early", "location": location_token, "limit": 10},
    ).json()
    seeded_slugs = {senior.slug, engineer.slug, internship.slug}
    all_level_slugs = {item["slug"] for item in all_levels["items"]}
    early_career_slugs = {item["slug"] for item in early_career["items"]}

    assert seeded_slugs <= all_level_slugs
    assert early_career_slugs & seeded_slugs == {engineer.slug, internship.slug}


def test_feed_early_experience_filter_excludes_new_senior_terms_and_keeps_student_titles(
    client: TestClient,
    db_session: Session,
) -> None:
    suffix = uuid.uuid4().hex
    seen_at = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    location_token = f"SeniorTermFilterville-{suffix}"
    company = models.Company(
        slug=f"senior-term-filter-company-{suffix}",
        name=f"Senior Term Filter Company {suffix}",
    )
    senior_titles = [
        "Vice President, Mid Market Sales",
        "Chief Operating Officer",
        "Field CTO",
        "Commercial Counsel",
        "President, Student Programs",
        "Chief Talent Officer",
        "CTO, Platform",
        "CEO Office Associate",
        "COO Operations",
        "CFO Strategy",
        "CXO Program",
        "Legal Counsel",
    ]
    student_titles = [
        "Software Engineer Intern",
        "New Grad Software Engineer",
        "Associate Product Analyst",
        "Data Science Intern",
        "User Escalation Specialist",
        "Business Consultant Intern",
        "Partner Solutions Engineer",
        "Graduate HR Partner",
        "Business Partner Analyst",
    ]
    senior_opportunities = [
        models.Opportunity(
            slug=f"senior-term-filter-senior-{index}-{suffix}",
            title=title,
            title_normalized=title.casefold(),
            company=company,
            category="job",
            location=location_token,
            apply_url=f"https://example.com/senior-term-filter/senior/{index}/{suffix}",
            status="active",
            last_seen_at=seen_at,
        )
        for index, title in enumerate(senior_titles)
    ]
    student_opportunities = [
        models.Opportunity(
            slug=f"senior-term-filter-student-{index}-{suffix}",
            title=title,
            title_normalized=title.casefold(),
            company=company,
            category="internship" if "intern" in title.casefold() else "job",
            location=location_token,
            apply_url=f"https://example.com/senior-term-filter/student/{index}/{suffix}",
            status="active",
            last_seen_at=seen_at,
        )
        for index, title in enumerate(student_titles)
    ]
    db_session.add_all([company, *senior_opportunities, *student_opportunities])
    db_session.flush()

    all_levels = client.get(
        "/feed",
        params={"location": location_token, "limit": 100},
    ).json()
    early_career = client.get(
        "/feed",
        params={"experience": "early", "location": location_token, "limit": 100},
    ).json()
    senior_slugs = {opportunity.slug for opportunity in senior_opportunities}
    student_slugs = {opportunity.slug for opportunity in student_opportunities}
    all_level_slugs = {item["slug"] for item in all_levels["items"]}
    early_career_slugs = {item["slug"] for item in early_career["items"]}

    assert senior_slugs <= all_level_slugs
    assert student_slugs <= all_level_slugs
    assert senior_slugs.isdisjoint(early_career_slugs)
    assert student_slugs <= early_career_slugs


def test_feed_default_student_sort_prioritizes_internships_and_early_roles(
    client: TestClient,
    db_session: Session,
) -> None:
    suffix = uuid.uuid4().hex
    seen_at = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    location_token = f"StudentFirstFilterville-{suffix}"
    company = models.Company(
        slug=f"student-first-filter-company-{suffix}",
        name=f"Student First Filter Company {suffix}",
    )
    internship = models.Opportunity(
        slug=f"student-first-filter-internship-{suffix}",
        title="Software Engineering Intern",
        title_normalized="software engineering intern",
        company=company,
        category="internship",
        location=location_token,
        apply_url=f"https://example.com/student-first-filter/internship/{suffix}",
        primary_source="greenhouse",
        status="active",
        last_seen_at=seen_at - timedelta(minutes=2),
    )
    engineer = models.Opportunity(
        slug=f"student-first-filter-engineer-{suffix}",
        title="Software Engineer",
        title_normalized="software engineer",
        company=company,
        category="job",
        location=location_token,
        apply_url=f"https://example.com/student-first-filter/engineer/{suffix}",
        primary_source="greenhouse",
        status="active",
        last_seen_at=seen_at - timedelta(minutes=1),
    )
    senior = models.Opportunity(
        slug=f"student-first-filter-senior-{suffix}",
        title="Senior Staff Engineer",
        title_normalized="senior staff engineer",
        company=company,
        category="job",
        location=location_token,
        apply_url=f"https://example.com/student-first-filter/senior/{suffix}",
        primary_source="greenhouse",
        status="active",
        last_seen_at=seen_at,
    )
    db_session.add_all([company, internship, engineer, senior])
    db_session.flush()

    params = {"location": location_token, "limit": 10}
    student_default = client.get("/feed", params=params).json()
    recent = client.get("/feed", params={**params, "sort": "recent"}).json()
    seeded_slugs = {internship.slug, engineer.slug, senior.slug}

    assert [item["slug"] for item in student_default["items"] if item["slug"] in seeded_slugs] == [
        internship.slug,
        engineer.slug,
        senior.slug,
    ]
    assert [item["slug"] for item in recent["items"] if item["slug"] in seeded_slugs] == [
        senior.slug,
        engineer.slug,
        internship.slug,
    ]


def test_feed_location_scope_excludes_foreign_remote_by_default_and_allows_opt_in(
    client: TestClient,
    db_session: Session,
) -> None:
    suffix = uuid.uuid4().hex
    seen_at = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    location_token = f"LocationScopeville-{suffix}"
    company = models.Company(
        slug=f"location-scope-company-{suffix}",
        name=f"Location Scope Company {suffix}",
    )
    domestic = models.Opportunity(
        slug=f"location-scope-domestic-{suffix}",
        title="Domestic role",
        company=company,
        category="job",
        location=location_token,
        country="IN",
        is_remote=False,
        apply_url=f"https://example.com/location-scope/domestic/{suffix}",
        status="active",
        last_seen_at=seen_at,
    )
    abroad = models.Opportunity(
        slug=f"location-scope-abroad-{suffix}",
        title="Abroad role",
        company=company,
        category="job",
        location=location_token,
        country="US",
        is_remote=False,
        apply_url=f"https://example.com/location-scope/abroad/{suffix}",
        status="active",
        last_seen_at=seen_at,
    )
    foreign_remote = models.Opportunity(
        slug=f"location-scope-foreign-remote-{suffix}",
        title="US remote role",
        company=company,
        category="job",
        location=location_token,
        country="US",
        is_remote=True,
        apply_url=f"https://example.com/location-scope/foreign-remote/{suffix}",
        status="active",
        last_seen_at=seen_at,
    )
    remote = models.Opportunity(
        slug=f"location-scope-remote-{suffix}",
        title="Location-agnostic remote role",
        company=company,
        category="job",
        location=location_token,
        country=None,
        is_remote=True,
        apply_url=f"https://example.com/location-scope/remote/{suffix}",
        status="active",
        last_seen_at=seen_at,
    )
    db_session.add_all([company, domestic, abroad, foreign_remote, remote])
    db_session.flush()

    domestic_body = client.get(
        "/feed",
        params={
            "scope": "domestic",
            "country": "IN",
            "location": location_token,
            "limit": 10,
        },
    ).json()
    domestic_with_remote_abroad_body = client.get(
        "/feed",
        params={
            "scope": "domestic",
            "country": "IN",
            "remote_abroad": True,
            "location": location_token,
            "limit": 10,
        },
    ).json()
    abroad_body = client.get(
        "/feed",
        params={
            "scope": "abroad",
            "country": "IN",
            "remote_abroad": True,
            "location": location_token,
            "limit": 10,
        },
    ).json()
    domestic_slugs = {item["slug"] for item in domestic_body["items"]}
    domestic_with_remote_abroad_slugs = {
        item["slug"] for item in domestic_with_remote_abroad_body["items"]
    }
    abroad_slugs = {item["slug"] for item in abroad_body["items"]}

    assert domestic.slug in domestic_slugs
    assert abroad.slug not in domestic_slugs
    assert foreign_remote.slug not in domestic_slugs
    assert remote.slug in domestic_slugs
    assert domestic.slug in domestic_with_remote_abroad_slugs
    assert foreign_remote.slug in domestic_with_remote_abroad_slugs
    assert remote.slug in domestic_with_remote_abroad_slugs
    assert domestic.slug not in abroad_slugs
    assert abroad.slug in abroad_slugs
    assert foreign_remote.slug in abroad_slugs
    assert remote.slug in abroad_slugs


def test_feed_filters_combine_with_category(client: TestClient, feed_rows) -> None:
    company_a, _company_b, opportunities, _location_token, _suffix = feed_rows

    body = client.get(
        "/feed",
        params={"company": company_a.slug, "category": "internship", "limit": 10},
    ).json()

    assert body["total"] == 1
    assert [item["slug"] for item in body["items"]] == [opportunities[0].slug]


def test_feed_accepts_hackathon_category_and_rejects_bogus_category(
    client: TestClient,
    db_session: Session,
) -> None:
    suffix = str(uuid.uuid4())
    seen_at = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    location_token = f"HackathonFilterville-{suffix}"
    company = models.Company(
        slug=f"hackathon-filter-company-{suffix}",
        name=f"Hackathon Filter Company {suffix}",
    )
    hackathon = models.Opportunity(
        slug=f"hackathon-filter-event-{suffix}",
        title="Build challenge",
        company=company,
        category="hackathon",
        location=location_token,
        apply_url=f"https://example.com/hackathon-filter/event/{suffix}",
        status="active",
        last_seen_at=seen_at,
    )
    role = models.Opportunity(
        slug=f"hackathon-filter-role-{suffix}",
        title="Backend engineer",
        company=company,
        category="job",
        location=location_token,
        apply_url=f"https://example.com/hackathon-filter/role/{suffix}",
        status="active",
        last_seen_at=seen_at,
    )
    db_session.add_all([company, hackathon, role])
    db_session.flush()

    response = client.get(
        "/feed",
        params={
            "category": "hackathon",
            "location": location_token,
            "limit": 10,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert [item["slug"] for item in body["items"]] == [hackathon.slug]
    assert all(item["category"] == "hackathon" for item in body["items"])

    bogus_response = client.get("/feed", params={"category": "fellowship"})
    assert bogus_response.status_code == 422


def test_feed_top_filter_returns_ranked_companies_and_combines_with_category(
    client: TestClient,
    db_session: Session,
) -> None:
    suffix = str(uuid.uuid4())
    seen_at = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    location_token = f"TopFilterville-{suffix}"
    ranked_company = models.Company(
        slug=f"top-filter-ranked-{suffix}",
        name=f"Top Filter Ranked {suffix}",
        global_rank=5,
    )
    prestige_company = models.Company(
        slug=f"top-filter-prestige-{suffix}",
        name=f"Top Filter Prestige {suffix}",
        prestige_rank=7,
    )
    unranked_company = models.Company(
        slug=f"top-filter-unranked-{suffix}",
        name=f"Top Filter Unranked {suffix}",
    )
    ranked_opportunity = models.Opportunity(
        slug=f"top-filter-ranked-internship-{suffix}",
        title="Ranked internship",
        company=ranked_company,
        category="internship",
        location=location_token,
        apply_url=f"https://example.com/top-filter/ranked/{suffix}",
        status="active",
        last_seen_at=seen_at,
    )
    prestige_opportunity = models.Opportunity(
        slug=f"top-filter-prestige-internship-{suffix}",
        title="Prestige internship",
        company=prestige_company,
        category="internship",
        location=location_token,
        apply_url=f"https://example.com/top-filter/prestige/{suffix}",
        status="active",
        last_seen_at=seen_at,
    )
    unranked_opportunity = models.Opportunity(
        slug=f"top-filter-unranked-job-{suffix}",
        title="Unranked job",
        company=unranked_company,
        category="job",
        location=location_token,
        apply_url=f"https://example.com/top-filter/unranked/{suffix}",
        status="active",
        last_seen_at=seen_at,
    )
    db_session.add_all(
        [
            ranked_company,
            prestige_company,
            unranked_company,
            ranked_opportunity,
            prestige_opportunity,
            unranked_opportunity,
        ]
    )
    db_session.flush()

    top_10 = client.get(
        "/feed",
        params={"top": 10, "location": location_token, "limit": 10},
    ).json()
    top_1 = client.get(
        "/feed",
        params={"top": 1, "location": location_token, "limit": 10},
    ).json()
    top_10_job = client.get(
        "/feed",
        params={"top": 10, "category": "job", "location": location_token, "limit": 10},
    ).json()
    top_10_internship = client.get(
        "/feed",
        params={
            "top": 10,
            "category": "internship",
            "location": location_token,
            "limit": 10,
        },
    ).json()

    expected_ranked_slugs = {ranked_opportunity.slug, prestige_opportunity.slug}

    assert prestige_company.global_rank is None
    assert unranked_company.global_rank is None
    assert unranked_company.prestige_rank is None
    assert top_10["total"] == 2
    assert {item["slug"] for item in top_10["items"]} == expected_ranked_slugs
    assert top_1["total"] == 0
    assert top_1["items"] == []
    assert top_10_job["total"] == 0
    assert top_10_job["items"] == []
    assert top_10_internship["total"] == 2
    assert {item["slug"] for item in top_10_internship["items"]} == expected_ranked_slugs


def test_feed_orders_open_and_real_roles_before_closed_and_competitions(
    client: TestClient,
    db_session: Session,
) -> None:
    suffix = uuid.uuid4().hex
    now = datetime.now(UTC)
    location_token = f"OrderingFilterville-{suffix}"
    company = models.Company(
        slug=f"ordering-filter-company-{suffix}",
        name=f"Ordering Filter Company {suffix}",
    )
    open_internship = models.Opportunity(
        slug=f"ordering-filter-open-internship-{suffix}",
        title="Open internship",
        company=company,
        category="internship",
        location=location_token,
        apply_url=f"https://example.com/ordering-filter/open-internship/{suffix}",
        deadline=now + timedelta(days=10),
        status="active",
        last_seen_at=now - timedelta(hours=3),
    )
    closed_internship = models.Opportunity(
        slug=f"ordering-filter-closed-internship-{suffix}",
        title="Recently closed internship",
        company=company,
        category="internship",
        location=location_token,
        apply_url=f"https://example.com/ordering-filter/closed-internship/{suffix}",
        deadline=now - timedelta(days=2),
        status="active",
        last_seen_at=now,
    )
    no_deadline_job = models.Opportunity(
        slug=f"ordering-filter-no-deadline-job-{suffix}",
        title="Job without a deadline",
        company=company,
        category="job",
        location=location_token,
        apply_url=f"https://example.com/ordering-filter/no-deadline-job/{suffix}",
        deadline=None,
        status="active",
        last_seen_at=now - timedelta(hours=1),
    )
    ppi_competition = models.Opportunity(
        slug=f"ordering-filter-ppi-competition-{suffix}",
        title="PPI competition",
        company=company,
        category="competition",
        location=location_token,
        apply_url=f"https://example.com/ordering-filter/ppi-competition/{suffix}",
        deadline=now + timedelta(days=30),
        meta={"offers_ppi": True},
        status="active",
        last_seen_at=now - timedelta(hours=2),
    )
    db_session.add_all(
        [
            company,
            open_internship,
            closed_internship,
            no_deadline_job,
            ppi_competition,
        ]
    )
    db_session.flush()

    deadline_sorted = client.get(
        "/feed",
        params={
            "category": "internship",
            "location": location_token,
            "sort": "deadline",
            "limit": 10,
        },
    ).json()
    roles = client.get(
        "/feed",
        params={"kind": "roles", "location": location_token, "limit": 10},
    ).json()
    recent = client.get(
        "/feed",
        params={"location": location_token, "sort": "recent", "limit": 10},
    ).json()

    assert deadline_sorted["total"] == 2
    assert [item["slug"] for item in deadline_sorted["items"]] == [
        open_internship.slug,
        closed_internship.slug,
    ]
    assert roles["total"] == 4
    assert [item["slug"] for item in roles["items"]] == [
        open_internship.slug,
        no_deadline_job.slug,
        ppi_competition.slug,
        closed_internship.slug,
    ]
    assert recent["total"] == 4
    assert [item["slug"] for item in recent["items"]] == [
        no_deadline_job.slug,
        ppi_competition.slug,
        open_internship.slug,
        closed_internship.slug,
    ]


def test_feed_keeps_grace_period_and_undated_rows_but_excludes_expired_categories(
    client: TestClient,
    db_session: Session,
) -> None:
    suffix = uuid.uuid4().hex
    now = datetime.now(UTC)
    location_token = f"DeadlineFilterville-{suffix}"
    company = models.Company(
        slug=f"deadline-filter-company-{suffix}",
        name=f"Deadline Filter Company {suffix}",
    )
    expired_competition = models.Opportunity(
        slug=f"deadline-filter-expired-competition-{suffix}",
        title="Expired competition",
        company=company,
        category="competition",
        location=location_token,
        apply_url=f"https://example.com/deadline-filter/expired/{suffix}",
        deadline=now - timedelta(days=20),
        meta={"offers_ppi": True},
        status="active",
        last_seen_at=now,
    )
    recently_closed_competition = models.Opportunity(
        slug=f"deadline-filter-recently-closed-competition-{suffix}",
        title="Recently closed competition",
        company=company,
        category="competition",
        location=location_token,
        apply_url=f"https://example.com/deadline-filter/recently-closed/{suffix}",
        deadline=now - timedelta(days=3),
        meta={"offers_ppi": True},
        status="active",
        last_seen_at=now,
    )
    earlier_closed_hackathon = models.Opportunity(
        slug=f"deadline-filter-earlier-closed-hackathon-{suffix}",
        title="Earlier closed hackathon",
        company=company,
        category="hackathon",
        location=location_token,
        apply_url=f"https://example.com/deadline-filter/earlier-closed/{suffix}",
        deadline=now - timedelta(days=10),
        meta={"offers_ppo": True},
        status="active",
        last_seen_at=now,
    )
    soon_hackathon = models.Opportunity(
        slug=f"deadline-filter-soon-hackathon-{suffix}",
        title="Soon hackathon",
        company=company,
        category="hackathon",
        location=location_token,
        apply_url=f"https://example.com/deadline-filter/soon/{suffix}",
        deadline=now + timedelta(days=5),
        status="active",
        last_seen_at=now,
    )
    future_hackathon = models.Opportunity(
        slug=f"deadline-filter-future-hackathon-{suffix}",
        title="Future hackathon",
        company=company,
        category="hackathon",
        location=location_token,
        apply_url=f"https://example.com/deadline-filter/future/{suffix}",
        deadline=now + timedelta(days=30),
        status="active",
        last_seen_at=now,
    )
    no_deadline_competition = models.Opportunity(
        slug=f"deadline-filter-no-deadline-competition-{suffix}",
        title="Competition without a deadline",
        company=company,
        category="competition",
        location=location_token,
        apply_url=f"https://example.com/deadline-filter/no-deadline/{suffix}",
        status="active",
        last_seen_at=now,
    )
    expired_internship = models.Opportunity(
        slug=f"deadline-filter-expired-internship-{suffix}",
        title="Expired Unstop internship",
        company=company,
        category="internship",
        location=location_token,
        apply_url=f"https://example.com/deadline-filter/expired-internship/{suffix}",
        deadline=now - timedelta(days=20),
        meta={"platform": "unstop"},
        status="active",
        last_seen_at=now,
    )
    ats_internship_without_deadline = models.Opportunity(
        slug=f"deadline-filter-ats-internship-{suffix}",
        title="ATS internship without a deadline",
        company=company,
        category="internship",
        location=location_token,
        apply_url=f"https://example.com/deadline-filter/ats-internship/{suffix}",
        deadline=None,
        meta={"platform": "greenhouse"},
        status="active",
        last_seen_at=now,
    )
    past_deadline_role = models.Opportunity(
        slug=f"deadline-filter-past-role-{suffix}",
        title="Past-deadline role",
        company=company,
        category="job",
        location=location_token,
        apply_url=f"https://example.com/deadline-filter/role/{suffix}",
        deadline=now - timedelta(days=30),
        status="active",
        last_seen_at=now,
    )
    recently_detected_closed_job = models.Opportunity(
        slug=f"deadline-filter-recently-closed-job-{suffix}",
        title="Recently detected closed job",
        company=company,
        category="job",
        location=location_token,
        apply_url=f"https://example.com/deadline-filter/recent-closed-job/{suffix}",
        closed_at=now - timedelta(days=3),
        status="active",
        last_seen_at=now,
    )
    stale_detected_closed_job = models.Opportunity(
        slug=f"deadline-filter-stale-closed-job-{suffix}",
        title="Stale detected closed job",
        company=company,
        category="job",
        location=location_token,
        apply_url=f"https://example.com/deadline-filter/stale-closed-job/{suffix}",
        closed_at=now - timedelta(days=20),
        status="active",
        last_seen_at=now,
    )
    uncategorized_past_deadline = models.Opportunity(
        slug=f"deadline-filter-uncategorized-{suffix}",
        title="Uncategorized past-deadline opportunity",
        company=company,
        category=None,
        location=location_token,
        apply_url=f"https://example.com/deadline-filter/uncategorized/{suffix}",
        deadline=now - timedelta(days=30),
        status="active",
        last_seen_at=now,
    )
    db_session.add_all(
        [
            company,
            expired_competition,
            recently_closed_competition,
            earlier_closed_hackathon,
            soon_hackathon,
            future_hackathon,
            no_deadline_competition,
            expired_internship,
            ats_internship_without_deadline,
            past_deadline_role,
            recently_detected_closed_job,
            stale_detected_closed_job,
            uncategorized_past_deadline,
        ]
    )
    db_session.flush()

    all_opportunities = client.get(
        "/feed",
        params={"location": location_token, "limit": 10},
    ).json()
    competitions = client.get(
        "/feed",
        params={
            "kind": "competitions",
            "location": location_token,
            "sort": "deadline",
            "limit": 10,
        },
    ).json()
    roles = client.get(
        "/feed",
        params={"kind": "roles", "location": location_token, "limit": 10},
    ).json()

    assert all_opportunities["total"] == 9
    assert {item["slug"] for item in all_opportunities["items"]} == {
        recently_closed_competition.slug,
        earlier_closed_hackathon.slug,
        soon_hackathon.slug,
        future_hackathon.slug,
        no_deadline_competition.slug,
        ats_internship_without_deadline.slug,
        past_deadline_role.slug,
        recently_detected_closed_job.slug,
        uncategorized_past_deadline.slug,
    }
    recent_closed_job_item = next(
        item
        for item in all_opportunities["items"]
        if item["slug"] == recently_detected_closed_job.slug
    )
    assert recent_closed_job_item["closed_at"] is not None
    assert stale_detected_closed_job.slug not in {
        item["slug"] for item in all_opportunities["items"]
    }
    assert competitions["total"] == 5
    assert [item["slug"] for item in competitions["items"]] == [
        soon_hackathon.slug,
        future_hackathon.slug,
        no_deadline_competition.slug,
        recently_closed_competition.slug,
        earlier_closed_hackathon.slug,
    ]
    assert roles["total"] == 5
    assert {item["slug"] for item in roles["items"]} == {
        recently_closed_competition.slug,
        earlier_closed_hackathon.slug,
        ats_internship_without_deadline.slug,
        past_deadline_role.slug,
        recently_detected_closed_job.slug,
    }


def test_feed_excludes_undated_rows_older_than_the_stale_window(
    client: TestClient,
    db_session: Session,
) -> None:
    """A missing posted_at must not bypass the 10-month rule.

    Before the first_seen_at fallback, `posted_at IS NULL` made the stale
    predicate NULL, so `stale.is_not(True)` kept the row: an undated listing
    could sit in the feed forever.
    """
    suffix = uuid.uuid4().hex
    now = datetime.now(UTC)
    location_token = f"UndatedStaleville-{suffix}"
    company = models.Company(
        slug=f"undated-stale-company-{suffix}",
        name=f"Undated Stale Company {suffix}",
    )
    undated_old = models.Opportunity(
        slug=f"undated-stale-old-{suffix}",
        title="Undated old listing",
        company=company,
        category="job",
        location=location_token,
        apply_url=f"https://example.com/undated-stale/old/{suffix}",
        posted_at=None,
        first_seen_at=now - timedelta(days=400),
        status="active",
        last_seen_at=now,
    )
    undated_recent = models.Opportunity(
        slug=f"undated-stale-recent-{suffix}",
        title="Undated recent listing",
        company=company,
        category="job",
        location=location_token,
        apply_url=f"https://example.com/undated-stale/recent/{suffix}",
        posted_at=None,
        first_seen_at=now - timedelta(days=10),
        status="active",
        last_seen_at=now,
    )
    # An old first_seen_at must NOT override a future deadline that still
    # keeps the listing current.
    undated_old_with_future_deadline = models.Opportunity(
        slug=f"undated-stale-old-future-deadline-{suffix}",
        title="Undated old listing with a future deadline",
        company=company,
        category="job",
        location=location_token,
        apply_url=f"https://example.com/undated-stale/old-future/{suffix}",
        posted_at=None,
        first_seen_at=now - timedelta(days=400),
        deadline=now + timedelta(days=30),
        status="active",
        last_seen_at=now,
    )
    dated_recent = models.Opportunity(
        slug=f"undated-stale-dated-recent-{suffix}",
        title="Dated recent listing",
        company=company,
        category="job",
        location=location_token,
        apply_url=f"https://example.com/undated-stale/dated-recent/{suffix}",
        posted_at=now - timedelta(days=5),
        first_seen_at=now - timedelta(days=400),
        status="active",
        last_seen_at=now,
    )
    db_session.add_all(
        [
            company,
            undated_old,
            undated_recent,
            undated_old_with_future_deadline,
            dated_recent,
        ]
    )
    db_session.flush()

    body = client.get("/feed", params={"location": location_token, "limit": 10}).json()
    slugs = {item["slug"] for item in body["items"]}

    assert undated_old.slug not in slugs
    assert undated_recent.slug in slugs
    assert undated_old_with_future_deadline.slug in slugs
    # posted_at still wins over first_seen_at when it is present.
    assert dated_recent.slug in slugs


def test_feed_experienced_only_filter_is_null_safe_and_detail_still_serves(
    client: TestClient,
    db_session: Session,
) -> None:
    suffix = uuid.uuid4().hex
    seen_at = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    location_token = f"ExperiencedOnlyFilterville-{suffix}"
    company = models.Company(
        slug=f"experienced-only-filter-company-{suffix}",
        name=f"Experienced Only Filter Company {suffix}",
    )
    no_meta = models.Opportunity(
        slug=f"experienced-only-filter-no-meta-{suffix}",
        title="No meta student listing",
        company=company,
        category="job",
        location=location_token,
        apply_url=f"https://example.com/experienced-only-filter/no-meta/{suffix}",
        meta=None,
        status="active",
        last_seen_at=seen_at,
    )
    absent_flag = models.Opportunity(
        slug=f"experienced-only-filter-absent-flag-{suffix}",
        title="Absent flag student listing",
        company=company,
        category="job",
        location=location_token,
        apply_url=f"https://example.com/experienced-only-filter/absent-flag/{suffix}",
        meta={"platform": "greenhouse"},
        status="active",
        last_seen_at=seen_at,
    )
    null_flag = models.Opportunity(
        slug=f"experienced-only-filter-null-flag-{suffix}",
        title="Null flag student listing",
        company=company,
        category="job",
        location=location_token,
        apply_url=f"https://example.com/experienced-only-filter/null-flag/{suffix}",
        meta={ELIGIBLE_EXPERIENCED_ONLY_META_KEY: None},
        status="active",
        last_seen_at=seen_at,
    )
    false_flag = models.Opportunity(
        slug=f"experienced-only-filter-false-flag-{suffix}",
        title="False flag student listing",
        company=company,
        category="job",
        location=location_token,
        apply_url=f"https://example.com/experienced-only-filter/false-flag/{suffix}",
        meta={ELIGIBLE_EXPERIENCED_ONLY_META_KEY: False},
        status="active",
        last_seen_at=seen_at,
    )
    true_flag = models.Opportunity(
        slug=f"experienced-only-filter-true-flag-{suffix}",
        title="Experienced-only listing",
        company=company,
        category="job",
        location=location_token,
        apply_url=f"https://example.com/experienced-only-filter/true-flag/{suffix}",
        meta={ELIGIBLE_EXPERIENCED_ONLY_META_KEY: True},
        status="active",
        last_seen_at=seen_at,
    )
    db_session.add_all([company, no_meta, absent_flag, null_flag, false_flag, true_flag])
    db_session.flush()

    body = client.get("/feed", params={"location": location_token, "limit": 10}).json()
    slugs = {item["slug"] for item in body["items"]}

    assert {no_meta.slug, absent_flag.slug, null_flag.slug, false_flag.slug} <= slugs
    assert true_flag.slug not in slugs

    detail_response = client.get(f"/opportunity/{true_flag.slug}")
    assert detail_response.status_code == 200
    assert detail_response.json()["slug"] == true_flag.slug


def test_is_stale_opportunity_falls_back_to_first_seen_at() -> None:
    """The Python detail-metadata check must agree with the SQL filter."""
    now = datetime.now(UTC)

    undated_old = models.Opportunity(
        posted_at=None,
        first_seen_at=now - timedelta(days=400),
        deadline=None,
    )
    undated_recent = models.Opportunity(
        posted_at=None,
        first_seen_at=now - timedelta(days=10),
        deadline=None,
    )
    undated_old_with_future_deadline = models.Opportunity(
        posted_at=None,
        first_seen_at=now - timedelta(days=400),
        deadline=now + timedelta(days=30),
    )
    dated_recent_seen_long_ago = models.Opportunity(
        posted_at=now - timedelta(days=5),
        first_seen_at=now - timedelta(days=400),
        deadline=None,
    )
    dated_old = models.Opportunity(
        posted_at=now - timedelta(days=400),
        first_seen_at=now - timedelta(days=400),
        deadline=None,
    )

    assert is_stale_opportunity(undated_old, now) is True
    assert is_stale_opportunity(undated_recent, now) is False
    assert is_stale_opportunity(undated_old_with_future_deadline, now) is False
    assert is_stale_opportunity(dated_recent_seen_long_ago, now) is False
    assert is_stale_opportunity(dated_old, now) is True
