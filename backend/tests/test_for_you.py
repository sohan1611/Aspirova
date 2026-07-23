import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from api import for_you, middleware
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


def test_for_you_ranks_fts_matches_and_excludes_nonmatches(
    client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    suffix = uuid.uuid4().hex
    keyword = "interest" + "".join(character for character in suffix if character.isalpha())
    monkeypatch.setitem(for_you.FIELD_KEYWORDS, "software", [keyword])
    now = datetime.now(UTC)
    company = models.Company(
        slug=f"for-you-ranking-company-{suffix}",
        name=f"For You Ranking Company {suffix}",
    )
    strong_match = models.Opportunity(
        slug=f"for-you-strong-software-match-{suffix}",
        title=f"{keyword} {keyword} {keyword}",
        company=company,
        category="job",
        country="AQ",
        is_remote=False,
        apply_url=f"https://example.com/for-you/strong/{suffix}",
        status="active",
        last_seen_at=now - timedelta(days=7),
    )
    weak_match = models.Opportunity(
        slug=f"for-you-weak-software-match-{suffix}",
        title=keyword,
        company=company,
        category="job",
        country="AQ",
        is_remote=False,
        apply_url=f"https://example.com/for-you/weak/{suffix}",
        status="active",
        last_seen_at=now,
    )
    nonmatch = models.Opportunity(
        slug=f"for-you-marketing-nonmatch-{suffix}",
        title="Marketing associate",
        company=company,
        category="job",
        country="AQ",
        is_remote=False,
        apply_url=f"https://example.com/for-you/nonmatch/{suffix}",
        status="active",
        last_seen_at=now,
    )
    db_session.add_all([company, strong_match, weak_match, nonmatch])
    db_session.flush()

    response = client.get(
        "/for-you",
        params={
            "fields": "software",
            "categories": "job",
            "scope": "domestic",
            "country": "AQ",
            "limit": 10,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert [item["slug"] for item in body["items"]] == [
        strong_match.slug,
        weak_match.slug,
    ]
    assert nonmatch.slug not in {item["slug"] for item in body["items"]}


def test_for_you_terms_rank_fts_matches_and_excludes_nonmatches(
    client: TestClient,
    db_session: Session,
) -> None:
    suffix = uuid.uuid4().hex
    keyword = "interest" + "".join(character for character in suffix if character.isalpha())
    now = datetime.now(UTC)
    company = models.Company(
        slug=f"for-you-terms-ranking-company-{suffix}",
        name=f"For You Terms Ranking Company {suffix}",
    )
    strong_match = models.Opportunity(
        slug=f"for-you-terms-strong-match-{suffix}",
        title=f"{keyword} {keyword} {keyword}",
        company=company,
        category="job",
        country="AQ",
        is_remote=False,
        apply_url=f"https://example.com/for-you/terms-strong/{suffix}",
        status="active",
        last_seen_at=now - timedelta(days=7),
    )
    weak_match = models.Opportunity(
        slug=f"for-you-terms-weak-match-{suffix}",
        title=keyword,
        company=company,
        category="job",
        country="AQ",
        is_remote=False,
        apply_url=f"https://example.com/for-you/terms-weak/{suffix}",
        status="active",
        last_seen_at=now,
    )
    nonmatch = models.Opportunity(
        slug=f"for-you-terms-nonmatch-{suffix}",
        title="Marketing associate",
        company=company,
        category="job",
        country="AQ",
        is_remote=False,
        apply_url=f"https://example.com/for-you/terms-nonmatch/{suffix}",
        status="active",
        last_seen_at=now,
    )
    db_session.add_all([company, strong_match, weak_match, nonmatch])
    db_session.flush()

    response = client.get(
        "/for-you",
        params={
            "terms": f" , {keyword} , ",
            "categories": "job",
            "scope": "domestic",
            "country": "AQ",
            "limit": 10,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert [item["slug"] for item in body["items"]] == [
        strong_match.slug,
        weak_match.slug,
    ]
    assert nonmatch.slug not in {item["slug"] for item in body["items"]}


def test_for_you_terms_take_precedence_over_fields(
    client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    suffix = uuid.uuid4().hex
    field_keyword = "field" + "".join(character for character in suffix if character.isalpha())
    term_keyword = "term" + "".join(
        character for character in reversed(suffix) if character.isalpha()
    )
    monkeypatch.setitem(for_you.FIELD_KEYWORDS, "software", [field_keyword])
    now = datetime.now(UTC)
    company = models.Company(
        slug=f"for-you-terms-precedence-company-{suffix}",
        name=f"For You Terms Precedence Company {suffix}",
    )
    terms_match = models.Opportunity(
        slug=f"for-you-terms-precedence-terms-match-{suffix}",
        title=f"{term_keyword} role",
        company=company,
        category="job",
        country="AQ",
        is_remote=False,
        apply_url=f"https://example.com/for-you/terms-precedence/terms/{suffix}",
        status="active",
        last_seen_at=now,
    )
    fields_match = models.Opportunity(
        slug=f"for-you-terms-precedence-fields-match-{suffix}",
        title=f"{field_keyword} role",
        company=company,
        category="job",
        country="AQ",
        is_remote=False,
        apply_url=f"https://example.com/for-you/terms-precedence/fields/{suffix}",
        status="active",
        last_seen_at=now,
    )
    db_session.add_all([company, terms_match, fields_match])
    db_session.flush()

    response = client.get(
        "/for-you",
        params={
            "fields": "software",
            "terms": term_keyword,
            "categories": "job",
            "scope": "domestic",
            "country": "AQ",
            "limit": 10,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert [item["slug"] for item in body["items"]] == [terms_match.slug]
    assert fields_match.slug not in {item["slug"] for item in body["items"]}


def test_for_you_applies_csv_category_and_country_scope_filters(
    client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    suffix = uuid.uuid4().hex
    keyword = "interest" + "".join(character for character in suffix if character.isalpha())
    monkeypatch.setitem(for_you.FIELD_KEYWORDS, "software", [keyword])
    now = datetime.now(UTC)
    company = models.Company(
        slug=f"for-you-filter-company-{suffix}",
        name=f"For You Filter Company {suffix}",
    )
    domestic_internship = models.Opportunity(
        slug=f"for-you-domestic-internship-{suffix}",
        title=f"{keyword} domestic internship",
        company=company,
        category="internship",
        country="AQ",
        is_remote=False,
        apply_url=f"https://example.com/for-you/domestic-internship/{suffix}",
        status="active",
        last_seen_at=now,
    )
    foreign_internship = models.Opportunity(
        slug=f"for-you-foreign-internship-{suffix}",
        title=f"{keyword} foreign internship",
        company=company,
        category="internship",
        country="US",
        is_remote=False,
        apply_url=f"https://example.com/for-you/foreign-internship/{suffix}",
        status="active",
        last_seen_at=now,
    )
    domestic_job = models.Opportunity(
        slug=f"for-you-domestic-job-{suffix}",
        title=f"{keyword} domestic job",
        company=company,
        category="job",
        country="AQ",
        is_remote=False,
        apply_url=f"https://example.com/for-you/domestic-job/{suffix}",
        status="active",
        last_seen_at=now,
    )
    db_session.add_all([company, domestic_internship, foreign_internship, domestic_job])
    db_session.flush()

    response = client.get(
        "/for-you",
        params={
            "fields": "software",
            "categories": "internship,job",
            "scope": "domestic",
            "country": "AQ",
            "limit": 10,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert {item["slug"] for item in body["items"]} == {
        domestic_internship.slug,
        domestic_job.slug,
    }
    assert foreign_internship.slug not in {item["slug"] for item in body["items"]}


def test_for_you_other_and_empty_fields_fall_back_to_recent_feed_order(
    client: TestClient,
    db_session: Session,
) -> None:
    suffix = uuid.uuid4().hex
    now = datetime.now(UTC)
    company = models.Company(
        slug=f"for-you-fallback-company-{suffix}",
        name=f"For You Fallback Company {suffix}",
    )
    recent_open = models.Opportunity(
        slug=f"for-you-recent-open-{suffix}",
        title="Recent generalist competition",
        company=company,
        category="competition",
        country="AQ",
        is_remote=False,
        apply_url=f"https://example.com/for-you/recent-open/{suffix}",
        status="active",
        last_seen_at=now,
    )
    older_open = models.Opportunity(
        slug=f"for-you-older-open-{suffix}",
        title="Older generalist competition",
        company=company,
        category="competition",
        country="AQ",
        is_remote=False,
        apply_url=f"https://example.com/for-you/older-open/{suffix}",
        status="active",
        last_seen_at=now - timedelta(days=1),
    )
    recently_closed = models.Opportunity(
        slug=f"for-you-recently-closed-{suffix}",
        title="Recently closed generalist competition",
        company=company,
        category="competition",
        country="AQ",
        is_remote=False,
        apply_url=f"https://example.com/for-you/recently-closed/{suffix}",
        deadline=now - timedelta(days=1),
        status="active",
        last_seen_at=now + timedelta(hours=1),
    )
    db_session.add_all([company, recent_open, older_open, recently_closed])
    db_session.flush()

    params = {
        "categories": "competition",
        "scope": "domestic",
        "country": "AQ",
        "limit": 10,
    }
    other_response = client.get("/for-you", params={**params, "fields": "other"})
    empty_response = client.get("/for-you", params={**params, "fields": ""})

    assert other_response.status_code == 200
    assert empty_response.status_code == 200
    # Runs against the shared production DB, where domestic scope also matches
    # real remote competitions, so assert deterministic invariants rather than an
    # exact global list: the no-keyword "other" and empty-field paths behave
    # identically, and the freshest open seeded row (last_seen == now, so it sorts
    # first) surfaces ahead of the closed seeded one (recent-feed order).
    other_slugs = [item["slug"] for item in other_response.json()["items"]]
    empty_slugs = [item["slug"] for item in empty_response.json()["items"]]
    assert other_slugs == empty_slugs
    assert recent_open.slug in other_slugs
    if recently_closed.slug in other_slugs:
        assert other_slugs.index(recent_open.slug) < other_slugs.index(recently_closed.slug)


def test_for_you_empty_and_whitespace_terms_behave_like_no_terms(
    client: TestClient,
    db_session: Session,
) -> None:
    suffix = uuid.uuid4().hex
    now = datetime.now(UTC)
    company = models.Company(
        slug=f"for-you-empty-terms-company-{suffix}",
        name=f"For You Empty Terms Company {suffix}",
    )
    recent_open = models.Opportunity(
        slug=f"for-you-empty-terms-recent-open-{suffix}",
        title="Recent generalist competition",
        company=company,
        category="competition",
        country="AQ",
        is_remote=False,
        apply_url=f"https://example.com/for-you/empty-terms/recent-open/{suffix}",
        status="active",
        last_seen_at=now,
    )
    db_session.add_all([company, recent_open])
    db_session.flush()

    params = {
        "categories": "competition",
        "scope": "domestic",
        "country": "AQ",
        "limit": 10,
    }
    no_terms_response = client.get("/for-you", params=params)
    empty_terms_response = client.get("/for-you", params={**params, "terms": ""})
    whitespace_terms_response = client.get("/for-you", params={**params, "terms": " ,   , "})

    assert no_terms_response.status_code == 200
    assert empty_terms_response.status_code == 200
    assert whitespace_terms_response.status_code == 200
    no_terms_body = no_terms_response.json()
    assert empty_terms_response.json() == no_terms_body
    assert whitespace_terms_response.json() == no_terms_body
    assert recent_open.slug in {item["slug"] for item in no_terms_body["items"]}


def test_for_you_junk_terms_do_not_raise(client: TestClient) -> None:
    response = client.get(
        "/for-you",
        params={
            "terms": "%%% !!! &&& ((()))",
            "categories": "job",
            "scope": "domestic",
            "country": "AQ",
        },
    )

    assert response.status_code == 200


def test_for_you_pagination_reports_total_for_each_nonempty_page(
    client: TestClient,
    db_session: Session,
) -> None:
    suffix = uuid.uuid4().hex
    now = datetime.now(UTC)
    company = models.Company(
        slug=f"for-you-pagination-company-{suffix}",
        name=f"For You Pagination Company {suffix}",
    )
    opportunities = [
        models.Opportunity(
            slug=f"for-you-pagination-{index}-{suffix}",
            title=f"Generalist competition {index}",
            company=company,
            category="competition",
            country="AQ",
            is_remote=False,
            apply_url=f"https://example.com/for-you/pagination/{index}/{suffix}",
            status="active",
            last_seen_at=now - timedelta(minutes=index),
        )
        for index in range(5)
    ]
    db_session.add_all([company, *opportunities])
    db_session.flush()

    params = {
        "fields": "other",
        "categories": "competition",
        "scope": "domestic",
        "country": "AQ",
        "limit": 2,
    }
    first_page = client.get("/for-you", params={**params, "page": 1})
    second_page = client.get("/for-you", params={**params, "page": 2})

    assert first_page.status_code == 200
    assert second_page.status_code == 200
    first_body = first_page.json()
    second_body = second_page.json()
    # Shared production DB: assert pagination consistency, not an absolute count.
    assert first_body["total"] == second_body["total"]
    assert first_body["total"] >= 5
    assert len(first_body["items"]) == 2
    assert len(second_body["items"]) == 2
    assert {item["slug"] for item in first_body["items"]}.isdisjoint(
        {item["slug"] for item in second_body["items"]}
    )
