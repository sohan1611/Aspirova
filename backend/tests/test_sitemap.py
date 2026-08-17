import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from api import middleware
from api import sitemap
from api.deps import get_db
from api.filters import STALE_AFTER_DAYS
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
    seen_at = datetime(2100, 1, 1, 12, 0, tzinfo=UTC)
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
    stale = models.Opportunity(
        slug=f"sitemap-test-stale-{suffix}",
        title="Sitemap test stale",
        apply_url=f"https://example.com/sitemap/stale/{suffix}",
        status="active",
        posted_at=datetime.now(UTC) - timedelta(days=STALE_AFTER_DAYS + 1),
        last_seen_at=seen_at,
    )
    unknown_posted_at = models.Opportunity(
        slug=f"sitemap-test-null-posted-at-{suffix}",
        title="Sitemap test null posted_at",
        apply_url=f"https://example.com/sitemap/null-posted-at/{suffix}",
        status="active",
        posted_at=None,
        last_seen_at=seen_at,
    )
    db_session.add_all([active_a, active_b, inactive, stale, unknown_posted_at])
    db_session.flush()

    response = client.get("/sitemap-opportunities")

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert all(set(item.keys()) == {"slug", "last_seen_at"} for item in body)
    assert all(isinstance(item["last_seen_at"], str) for item in body)

    slugs = [item["slug"] for item in body]
    assert active_a.slug in slugs
    assert active_b.slug in slugs
    assert unknown_posted_at.slug in slugs
    assert slugs.index(active_a.slug) < slugs.index(active_b.slug)
    assert inactive.slug not in slugs
    assert stale.slug not in slugs


def test_sitemap_opportunities_is_bounded_and_ranked_by_last_seen_at(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sitemap, "SITEMAP_OPPORTUNITY_LIMIT", 2)
    suffix = str(uuid.uuid4())
    newest_seen_at = datetime(2100, 1, 3, 12, 0, tzinfo=UTC)
    older_seen_at = datetime(2100, 1, 2, 12, 0, tzinfo=UTC)
    newest_a = models.Opportunity(
        slug=f"sitemap-limit-newest-a-{suffix}",
        title="Sitemap limit newest A",
        apply_url=f"https://example.com/sitemap/limit/newest-a/{suffix}",
        status="active",
        last_seen_at=newest_seen_at,
    )
    newest_b = models.Opportunity(
        slug=f"sitemap-limit-newest-b-{suffix}",
        title="Sitemap limit newest B",
        apply_url=f"https://example.com/sitemap/limit/newest-b/{suffix}",
        status="active",
        last_seen_at=newest_seen_at,
    )
    older = models.Opportunity(
        slug=f"sitemap-limit-older-{suffix}",
        title="Sitemap limit older",
        apply_url=f"https://example.com/sitemap/limit/older/{suffix}",
        status="active",
        last_seen_at=older_seen_at,
    )
    db_session.add_all([newest_a, newest_b, older])
    db_session.flush()

    response = client.get("/sitemap-opportunities")

    assert response.status_code == 200
    body = response.json()
    assert len(body) <= sitemap.SITEMAP_OPPORTUNITY_LIMIT
    assert [item["slug"] for item in body] == [newest_a.slug, newest_b.slug]
    last_seen_at_values = [datetime.fromisoformat(item["last_seen_at"]) for item in body]
    assert last_seen_at_values == sorted(last_seen_at_values, reverse=True)


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
    stale_only_company = models.Company(
        slug=f"sitemap-company-stale-only-{suffix}",
        name="Sitemap Company Stale Only",
    )
    unknown_posted_at_company = models.Company(
        slug=f"sitemap-company-null-posted-at-{suffix}",
        name="Sitemap Company Null Posted At",
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
    stale = models.Opportunity(
        slug=f"sitemap-company-stale-opp-{suffix}",
        title="Sitemap company stale opportunity",
        company=stale_only_company,
        apply_url=f"https://example.com/sitemap/company/stale/{suffix}",
        status="active",
        posted_at=datetime.now(UTC) - timedelta(days=STALE_AFTER_DAYS + 1),
        first_seen_at=seen_at,
        last_seen_at=seen_at,
    )
    unknown_posted_at = models.Opportunity(
        slug=f"sitemap-company-null-posted-at-opp-{suffix}",
        title="Sitemap company null posted_at opportunity",
        company=unknown_posted_at_company,
        apply_url=f"https://example.com/sitemap/company/null-posted-at/{suffix}",
        status="active",
        posted_at=None,
        first_seen_at=seen_at,
        last_seen_at=seen_at,
    )
    db_session.add_all(
        [
            active_company,
            inactive_company,
            stale_only_company,
            unknown_posted_at_company,
            empty_company,
            active,
            inactive,
            stale,
            unknown_posted_at,
        ]
    )
    db_session.flush()

    response = client.get("/sitemap-companies")

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert all(set(item.keys()) == {"slug"} for item in body)

    slugs = [item["slug"] for item in body]
    assert slugs == sorted(slugs)
    assert active_company.slug in slugs
    assert unknown_posted_at_company.slug in slugs
    assert inactive_company.slug not in slugs
    assert stale_only_company.slug not in slugs
    assert empty_company.slug not in slugs
