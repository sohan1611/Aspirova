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
def search_rows(db_session: Session):
    suffix = uuid.uuid4().hex
    search_term = f"searchfilter{suffix}"
    location_token = f"Searchville-{suffix}"
    seen_at = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

    top_company = models.Company(
        slug=f"search-filter-top-{suffix}",
        name=f"Search Filter Top {suffix}",
        global_rank=5,
    )
    mid_company = models.Company(
        slug=f"search-filter-mid-{suffix}",
        name=f"Search Filter Mid {suffix}",
        global_rank=50,
    )
    unranked_company = models.Company(
        slug=f"search-filter-unranked-{suffix}",
        name=f"Search Filter Unranked {suffix}",
    )
    opportunities = [
        models.Opportunity(
            slug=f"search-filter-top-internship-{suffix}",
            title=f"{search_term} top internship",
            company=top_company,
            category="internship",
            location=f"North {location_token}, India",
            is_remote=True,
            apply_url=f"https://example.com/search-filter/top-internship/{suffix}",
            primary_source="greenhouse",
            status="active",
            last_seen_at=seen_at,
        ),
        models.Opportunity(
            slug=f"search-filter-top-job-{suffix}",
            title=f"{search_term} top job",
            company=top_company,
            category="job",
            location=f"Elsewhere-{suffix}",
            is_remote=False,
            apply_url=f"https://example.com/search-filter/top-job/{suffix}",
            primary_source="unstop",
            status="active",
            last_seen_at=seen_at,
        ),
        models.Opportunity(
            slug=f"search-filter-mid-internship-{suffix}",
            title=f"{search_term} mid internship",
            company=mid_company,
            category="internship",
            location=f"South {location_token}, India",
            is_remote=False,
            apply_url=f"https://example.com/search-filter/mid-internship/{suffix}",
            primary_source="ashby",
            status="active",
            last_seen_at=seen_at,
        ),
        models.Opportunity(
            slug=f"search-filter-unranked-job-{suffix}",
            title=f"{search_term} unranked job",
            company=unranked_company,
            category="job",
            location=f"Coast-{suffix}",
            is_remote=True,
            apply_url=f"https://example.com/search-filter/unranked-job/{suffix}",
            primary_source="remoteok",
            status="active",
            last_seen_at=seen_at,
        ),
    ]
    db_session.add_all([top_company, mid_company, unranked_company, *opportunities])
    db_session.flush()

    return search_term, location_token, top_company.slug, opportunities


@pytest.fixture
def multipage_search_rows(db_session: Session):
    suffix = uuid.uuid4().hex
    search_term = f"multipagesearch{suffix}"
    company = models.Company(
        slug=f"search-multipage-company-{suffix}",
        name=f"Search Multipage Company {suffix}",
    )
    opportunities = [
        models.Opportunity(
            slug=f"search-multipage-{index}-{suffix}",
            title=f"{search_term} opportunity {index}",
            title_normalized=f"{search_term} opportunity {index}",
            company=company,
            category="internship",
            apply_url=f"https://example.com/search-multipage/{index}/{suffix}",
            status="active",
        )
        for index in range(5)
    ]
    distractors = [
        models.Opportunity(
            slug=f"search-multipage-different-query-{suffix}",
            title=f"different query {suffix}",
            title_normalized=f"different query {suffix}",
            company=company,
            category="internship",
            apply_url=f"https://example.com/search-multipage/different/{suffix}",
            status="active",
        ),
        models.Opportunity(
            slug=f"search-multipage-inactive-{suffix}",
            title=f"{search_term} inactive",
            title_normalized=f"{search_term} inactive",
            company=company,
            category="internship",
            apply_url=f"https://example.com/search-multipage/inactive/{suffix}",
            status="closed",
        ),
    ]
    db_session.add_all([company, *opportunities, *distractors])
    db_session.flush()

    return search_term, opportunities


@pytest.fixture
def trigram_search_rows(db_session: Session):
    suffix = uuid.uuid4().hex
    query = f"sofware enginer {suffix}"
    company = models.Company(
        slug=f"search-trigram-company-{suffix}",
        name=f"Search Trigram Company {suffix}",
    )
    opportunities = [
        models.Opportunity(
            slug=f"search-trigram-{index}-{suffix}",
            title=f"Software Engineer {suffix} role {index}",
            title_normalized=f"software engineer {suffix} role {index}",
            company=company,
            category="job",
            apply_url=f"https://example.com/search-trigram/{index}/{suffix}",
            status="active",
        )
        for index in range(3)
    ]
    db_session.add_all([company, *opportunities])
    db_session.flush()

    return query, opportunities


def test_search_total_matches_true_count_for_multipage_result_set(
    client: TestClient,
    multipage_search_rows,
) -> None:
    search_term, opportunities = multipage_search_rows
    expected_slugs = {opportunity.slug for opportunity in opportunities}

    responses = [
        client.get("/search", params={"q": search_term, "limit": 2, "page": page})
        for page in (1, 2, 3)
    ]

    assert [response.status_code for response in responses] == [200, 200, 200]
    bodies = [response.json() for response in responses]
    assert {body["total"] for body in bodies} == {len(opportunities)}
    assert [len(body["items"]) for body in bodies] == [2, 2, 1]
    returned_slugs = [item["slug"] for body in bodies for item in body["items"]]
    assert len(returned_slugs) == len(set(returned_slugs))
    assert set(returned_slugs) == expected_slugs


def test_search_page_beyond_end_returns_total_with_empty_items(
    client: TestClient,
    multipage_search_rows,
) -> None:
    search_term, opportunities = multipage_search_rows

    response = client.get("/search", params={"q": search_term, "limit": 2, "page": 4})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == len(opportunities)
    assert body["items"] == []


def test_search_zero_match_query_returns_total_zero(client: TestClient) -> None:
    response = client.get("/search", params={"q": f"zeromatch{uuid.uuid4().hex}"})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 0
    assert body["items"] == []


def test_search_trigram_fallback_total_matches_fallback_rows(
    client: TestClient,
    trigram_search_rows,
) -> None:
    query, opportunities = trigram_search_rows
    expected_slugs = {opportunity.slug for opportunity in opportunities}

    page_one = client.get("/search", params={"q": query, "limit": 2, "page": 1})
    page_two = client.get("/search", params={"q": query, "limit": 2, "page": 2})

    assert page_one.status_code == 200
    assert page_two.status_code == 200
    bodies = [page_one.json(), page_two.json()]
    assert {body["total"] for body in bodies} == {len(opportunities)}
    assert [len(body["items"]) for body in bodies] == [2, 1]
    returned_slugs = [item["slug"] for body in bodies for item in body["items"]]
    assert len(returned_slugs) == len(set(returned_slugs))
    assert set(returned_slugs) == expected_slugs


def test_search_without_filters_returns_all_fts_matches(
    client: TestClient,
    search_rows,
) -> None:
    search_term, _location_token, _company_slug, opportunities = search_rows

    response = client.get("/search", params={"q": search_term, "limit": 100})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == len(opportunities)
    assert {item["slug"] for item in body["items"]} == {
        opportunity.slug for opportunity in opportunities
    }


@pytest.mark.parametrize(
    ("filter_name", "expected_indexes"),
    [
        pytest.param("category", {0, 2}, id="category"),
        pytest.param("remote", {0, 3}, id="remote"),
        pytest.param("company", {0, 1}, id="company"),
        pytest.param("location", {0, 2}, id="location"),
        pytest.param("top", {0, 1}, id="top"),
        pytest.param("source", {0, 2}, id="source"),
    ],
)
def test_search_filters_restrict_fts_matches(
    client: TestClient,
    search_rows,
    filter_name: str,
    expected_indexes: set[int],
) -> None:
    search_term, location_token, company_slug, opportunities = search_rows
    filter_params = {
        "category": {"category": "internship"},
        "remote": {"remote": True},
        "company": {"company": company_slug},
        "location": {"location": location_token.lower()},
        "top": {"top": 10},
        "source": {"source": "direct"},
    }
    expected_slugs = {opportunities[index].slug for index in expected_indexes}

    response = client.get(
        "/search",
        params={"q": search_term, "limit": 100, **filter_params[filter_name]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == len(expected_slugs)
    assert {item["slug"] for item in body["items"]} == expected_slugs


def test_search_kind_restricts_query_matches(client: TestClient, db_session: Session) -> None:
    suffix = uuid.uuid4().hex
    search_term = f"searchkind{suffix}"
    company = models.Company(
        slug=f"search-kind-company-{suffix}",
        name=f"Search Kind Company {suffix}",
    )
    role = models.Opportunity(
        slug=f"search-kind-role-{suffix}",
        title=f"{search_term} internship",
        company=company,
        category="internship",
        apply_url=f"https://example.com/search-kind/role/{suffix}",
        status="active",
    )
    competition = models.Opportunity(
        slug=f"search-kind-competition-{suffix}",
        title=f"{search_term} hackathon",
        company=company,
        category="hackathon",
        apply_url=f"https://example.com/search-kind/competition/{suffix}",
        status="active",
    )
    db_session.add_all([company, role, competition])
    db_session.flush()

    response = client.get(
        "/search",
        params={"q": search_term, "kind": "competitions", "limit": 100},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert [item["slug"] for item in body["items"]] == [competition.slug]


def test_search_keeps_grace_period_and_undated_rows_but_excludes_expired_categories(
    client: TestClient,
    db_session: Session,
) -> None:
    suffix = uuid.uuid4().hex
    search_term = f"deadlinefilter{suffix}"
    now = datetime.now(UTC)
    company = models.Company(
        slug=f"search-deadline-filter-company-{suffix}",
        name=f"Search Deadline Filter Company {suffix}",
    )
    expired_competition = models.Opportunity(
        slug=f"search-deadline-filter-expired-{suffix}",
        title=f"{search_term} expired competition",
        company=company,
        category="competition",
        apply_url=f"https://example.com/search-deadline-filter/expired/{suffix}",
        deadline=now - timedelta(days=20),
        status="active",
        last_seen_at=now,
    )
    recently_closed_competition = models.Opportunity(
        slug=f"search-deadline-filter-recently-closed-{suffix}",
        title=f"{search_term} recently closed competition",
        company=company,
        category="competition",
        apply_url=(f"https://example.com/search-deadline-filter/recently-closed/{suffix}"),
        deadline=now - timedelta(days=3),
        status="active",
        last_seen_at=now,
    )
    future_hackathon = models.Opportunity(
        slug=f"search-deadline-filter-future-{suffix}",
        title=f"{search_term} future hackathon",
        company=company,
        category="hackathon",
        apply_url=f"https://example.com/search-deadline-filter/future/{suffix}",
        deadline=now + timedelta(days=30),
        status="active",
        last_seen_at=now,
    )
    no_deadline_competition = models.Opportunity(
        slug=f"search-deadline-filter-no-deadline-{suffix}",
        title=f"{search_term} competition without deadline",
        company=company,
        category="competition",
        apply_url=f"https://example.com/search-deadline-filter/no-deadline/{suffix}",
        status="active",
        last_seen_at=now,
    )
    expired_internship = models.Opportunity(
        slug=f"search-deadline-filter-expired-internship-{suffix}",
        title=f"{search_term} expired Unstop internship",
        company=company,
        category="internship",
        apply_url=f"https://example.com/search-deadline-filter/expired-internship/{suffix}",
        deadline=now - timedelta(days=20),
        meta={"platform": "unstop"},
        status="active",
        last_seen_at=now,
    )
    ats_internship_without_deadline = models.Opportunity(
        slug=f"search-deadline-filter-ats-internship-{suffix}",
        title=f"{search_term} ATS internship without deadline",
        company=company,
        category="internship",
        apply_url=f"https://example.com/search-deadline-filter/ats-internship/{suffix}",
        deadline=None,
        meta={"platform": "greenhouse"},
        status="active",
        last_seen_at=now,
    )
    past_deadline_role = models.Opportunity(
        slug=f"search-deadline-filter-role-{suffix}",
        title=f"{search_term} past-deadline role",
        company=company,
        category="job",
        apply_url=f"https://example.com/search-deadline-filter/role/{suffix}",
        deadline=now - timedelta(days=30),
        status="active",
        last_seen_at=now,
    )
    db_session.add_all(
        [
            company,
            expired_competition,
            recently_closed_competition,
            future_hackathon,
            no_deadline_competition,
            expired_internship,
            ats_internship_without_deadline,
            past_deadline_role,
        ]
    )
    db_session.flush()

    response = client.get("/search", params={"q": search_term, "limit": 10})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 5
    assert {item["slug"] for item in body["items"]} == {
        recently_closed_competition.slug,
        future_hackathon.slug,
        no_deadline_competition.slug,
        ats_internship_without_deadline.slug,
        past_deadline_role.slug,
    }
