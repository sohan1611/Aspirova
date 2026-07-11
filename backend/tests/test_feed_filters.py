import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from api import middleware
from api.deps import get_db
from api.main import app
from core import models


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


def test_feed_location_filter_narrows_results(client: TestClient, feed_rows) -> None:
    _company_a, _company_b, opportunities, location_token, _suffix = feed_rows

    body = client.get("/feed", params={"location": location_token, "limit": 10}).json()

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

    assert all_opportunities["total"] == 8
    assert {item["slug"] for item in all_opportunities["items"]} == {
        recently_closed_competition.slug,
        earlier_closed_hackathon.slug,
        soon_hackathon.slug,
        future_hackathon.slug,
        no_deadline_competition.slug,
        ats_internship_without_deadline.slug,
        past_deadline_role.slug,
        uncategorized_past_deadline.slug,
    }
    assert competitions["total"] == 5
    assert [item["slug"] for item in competitions["items"]] == [
        soon_hackathon.slug,
        future_hackathon.slug,
        no_deadline_competition.slug,
        recently_closed_competition.slug,
        earlier_closed_hackathon.slug,
    ]
    assert roles["total"] == 4
    assert {item["slug"] for item in roles["items"]} == {
        recently_closed_competition.slug,
        earlier_closed_hackathon.slug,
        ats_internship_without_deadline.slug,
        past_deadline_role.slug,
    }
