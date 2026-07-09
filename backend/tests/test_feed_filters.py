import uuid
from datetime import UTC, datetime

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
