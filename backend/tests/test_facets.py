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


def test_facets_return_distinct_active_companies_and_locations(
    client: TestClient, db_session: Session
) -> None:
    suffix = str(uuid.uuid4())
    seen_at = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    high_location = f"Facet High Location {suffix}"
    low_location = f"Facet Low Location {suffix}"
    inactive_location = f"Facet Inactive Location {suffix}"

    high_count_company = models.Company(
        slug=f"facet-high-count-{suffix}",
        name=f"Facet High Count {suffix}",
    )
    low_count_company = models.Company(
        slug=f"facet-low-count-{suffix}",
        name=f"Facet Low Count {suffix}",
    )
    blank_location_company = models.Company(
        slug=f"facet-blank-location-{suffix}",
        name=f"Facet Blank Location {suffix}",
    )
    inactive_company = models.Company(
        slug=f"facet-inactive-{suffix}",
        name=f"Facet Inactive {suffix}",
    )
    db_session.add_all(
        [
            high_count_company,
            low_count_company,
            blank_location_company,
            inactive_company,
            models.Opportunity(
                slug=f"facet-active-a-{suffix}",
                title="Facet active A",
                company=high_count_company,
                apply_url=f"https://example.com/facets/active-a/{suffix}",
                location=high_location,
                status="active",
                first_seen_at=seen_at,
                last_seen_at=seen_at,
            ),
            models.Opportunity(
                slug=f"facet-active-b-{suffix}",
                title="Facet active B",
                company=high_count_company,
                apply_url=f"https://example.com/facets/active-b/{suffix}",
                location=high_location,
                status="active",
                first_seen_at=seen_at,
                last_seen_at=seen_at,
            ),
            models.Opportunity(
                slug=f"facet-active-c-{suffix}",
                title="Facet active C",
                company=low_count_company,
                apply_url=f"https://example.com/facets/active-c/{suffix}",
                location=low_location,
                status="active",
                first_seen_at=seen_at,
                last_seen_at=seen_at,
            ),
            models.Opportunity(
                slug=f"facet-active-blank-location-{suffix}",
                title="Facet active blank location",
                company=blank_location_company,
                apply_url=f"https://example.com/facets/active-blank/{suffix}",
                location="",
                status="active",
                first_seen_at=seen_at,
                last_seen_at=seen_at,
            ),
            models.Opportunity(
                slug=f"facet-inactive-opp-{suffix}",
                title="Facet inactive",
                company=inactive_company,
                apply_url=f"https://example.com/facets/inactive/{suffix}",
                location=inactive_location,
                status="expired",
                first_seen_at=seen_at,
                last_seen_at=seen_at,
            ),
        ]
    )
    db_session.flush()

    response = client.get("/facets")

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"companies", "locations"}

    companies = body["companies"]
    locations = body["locations"]
    assert len(companies) == len(set(companies))
    assert len(locations) == len(set(locations))

    assert companies.count(high_count_company.name) == 1
    assert companies.count(low_count_company.name) == 1
    assert companies.index(high_count_company.name) < companies.index(low_count_company.name)
    assert inactive_company.name not in companies

    assert locations.count(high_location) == 1
    assert locations.count(low_location) == 1
    assert locations.index(high_location) < locations.index(low_location)
    assert inactive_location not in locations
    assert "" not in locations
