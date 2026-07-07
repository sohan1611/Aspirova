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


def test_sitemap_opportunities_returns_active_slug_shape(
    client: TestClient, db_session: Session
) -> None:
    suffix = str(uuid.uuid4())
    seen_at = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    active_a = models.Opportunity(
        slug=f"sitemap-test-active-a-{suffix}",
        title="Sitemap test active A",
        apply_url=f"https://example.com/sitemap/active-a/{suffix}",
        status="active",
        last_seen_at=seen_at,
    )
    active_b = models.Opportunity(
        slug=f"sitemap-test-active-b-{suffix}",
        title="Sitemap test active B",
        apply_url=f"https://example.com/sitemap/active-b/{suffix}",
        status="active",
        last_seen_at=seen_at,
    )
    inactive = models.Opportunity(
        slug=f"sitemap-test-inactive-{suffix}",
        title="Sitemap test inactive",
        apply_url=f"https://example.com/sitemap/inactive/{suffix}",
        status="expired",
        last_seen_at=seen_at,
    )
    db_session.add_all([active_a, active_b, inactive])
    db_session.flush()

    response = client.get("/sitemap-opportunities")

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert all(set(item.keys()) == {"slug", "last_seen_at"} for item in body)
    assert all(isinstance(item["last_seen_at"], str) for item in body)

    slugs = [item["slug"] for item in body]
    assert slugs == sorted(slugs)
    assert active_a.slug in slugs
    assert active_b.slug in slugs
    assert inactive.slug not in slugs


def test_company_page_returns_company_and_only_active_opportunities(
    client: TestClient, db_session: Session
) -> None:
    suffix = str(uuid.uuid4())
    old_seen_at = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    new_seen_at = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)
    company = models.Company(
        slug=f"company-page-test-{suffix}",
        name="Company Page Test",
        domain=f"company-page-test-{suffix}.example",
        logo_url=f"https://example.com/logo/{suffix}.png",
    )
    active_old = models.Opportunity(
        slug=f"company-page-active-old-{suffix}",
        title="Company page active old",
        company=company,
        apply_url=f"https://example.com/company/active-old/{suffix}",
        status="active",
        first_seen_at=old_seen_at,
        last_seen_at=old_seen_at,
    )
    active_new = models.Opportunity(
        slug=f"company-page-active-new-{suffix}",
        title="Company page active new",
        company=company,
        apply_url=f"https://example.com/company/active-new/{suffix}",
        status="active",
        first_seen_at=new_seen_at,
        last_seen_at=new_seen_at,
    )
    inactive = models.Opportunity(
        slug=f"company-page-inactive-{suffix}",
        title="Company page inactive",
        company=company,
        apply_url=f"https://example.com/company/inactive/{suffix}",
        status="expired",
        first_seen_at=new_seen_at,
        last_seen_at=new_seen_at,
    )
    db_session.add_all([company, active_old, active_new, inactive])
    db_session.flush()

    response = client.get(f"/company/{company.slug}", params={"limit": 10})

    assert response.status_code == 200
    body = response.json()
    assert body["company"] == {
        "slug": company.slug,
        "name": company.name,
        "domain": company.domain,
        "logo_url": company.logo_url,
    }
    assert body["total"] == 2
    assert body["page"] == 1
    assert body["limit"] == 10
    assert [item["slug"] for item in body["items"]] == [
        active_new.slug,
        active_old.slug,
    ]
    assert inactive.slug not in [item["slug"] for item in body["items"]]


def test_company_page_404_for_unknown_company(client: TestClient) -> None:
    response = client.get("/company/this-company-does-not-exist-xyz")

    assert response.status_code == 404


def test_sitemap_companies_returns_only_companies_with_active_opportunities(
    client: TestClient, db_session: Session
) -> None:
    suffix = str(uuid.uuid4())
    seen_at = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    active_company = models.Company(
        slug=f"sitemap-company-active-{suffix}",
        name="Sitemap Company Active",
    )
    inactive_company = models.Company(
        slug=f"sitemap-company-inactive-{suffix}",
        name="Sitemap Company Inactive",
    )
    empty_company = models.Company(
        slug=f"sitemap-company-empty-{suffix}",
        name="Sitemap Company Empty",
    )
    active = models.Opportunity(
        slug=f"sitemap-company-active-opp-{suffix}",
        title="Sitemap company active opportunity",
        company=active_company,
        apply_url=f"https://example.com/sitemap/company/active/{suffix}",
        status="active",
        first_seen_at=seen_at,
        last_seen_at=seen_at,
    )
    inactive = models.Opportunity(
        slug=f"sitemap-company-inactive-opp-{suffix}",
        title="Sitemap company inactive opportunity",
        company=inactive_company,
        apply_url=f"https://example.com/sitemap/company/inactive/{suffix}",
        status="expired",
        first_seen_at=seen_at,
        last_seen_at=seen_at,
    )
    db_session.add_all([active_company, inactive_company, empty_company, active, inactive])
    db_session.flush()

    response = client.get("/sitemap-companies")

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert all(set(item.keys()) == {"slug"} for item in body)

    slugs = [item["slug"] for item in body]
    assert slugs == sorted(slugs)
    assert active_company.slug in slugs
    assert inactive_company.slug not in slugs
    assert empty_company.slug not in slugs
