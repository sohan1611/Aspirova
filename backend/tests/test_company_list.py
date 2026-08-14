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


def test_companies_returns_active_company_counts_ordered(
    client: TestClient, db_session: Session
) -> None:
    suffix = str(uuid.uuid4())
    seen_at = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    high_count_company = models.Company(
        slug=f"company-list-high-count-{suffix}",
        name="Company List High Count",
        domain=f"company-list-high-count-{suffix}.example",
        logo_url=f"https://example.com/company-list/logo/{suffix}.png",
    )
    low_count_company = models.Company(
        slug=f"company-list-low-count-{suffix}",
        name="Company List Low Count",
    )
    inactive_company = models.Company(
        slug=f"company-list-inactive-{suffix}",
        name="Company List Inactive",
    )
    active_a = models.Opportunity(
        slug=f"company-list-active-a-{suffix}",
        title="Company list active A",
        company=high_count_company,
        apply_url=f"https://example.com/company-list/active-a/{suffix}",
        status="active",
        first_seen_at=seen_at,
        last_seen_at=seen_at,
    )
    active_b = models.Opportunity(
        slug=f"company-list-active-b-{suffix}",
        title="Company list active B",
        company=high_count_company,
        apply_url=f"https://example.com/company-list/active-b/{suffix}",
        status="active",
        first_seen_at=seen_at,
        last_seen_at=seen_at,
    )
    active_c = models.Opportunity(
        slug=f"company-list-active-c-{suffix}",
        title="Company list active C",
        company=low_count_company,
        apply_url=f"https://example.com/company-list/active-c/{suffix}",
        status="active",
        first_seen_at=seen_at,
        last_seen_at=seen_at,
    )
    inactive = models.Opportunity(
        slug=f"company-list-inactive-opp-{suffix}",
        title="Company list inactive",
        company=inactive_company,
        apply_url=f"https://example.com/company-list/inactive/{suffix}",
        status="expired",
        first_seen_at=seen_at,
        last_seen_at=seen_at,
    )
    db_session.add_all(
        [
            high_count_company,
            low_count_company,
            inactive_company,
            active_a,
            active_b,
            active_c,
            inactive,
        ]
    )
    db_session.flush()

    response = client.get("/companies")

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert all(
        set(item.keys()) == {"slug", "name", "domain", "logo_url", "active_count"} for item in body
    )

    # Collation-independent global invariant: counts are non-increasing. The
    # endpoint's name tiebreak among equal counts uses the DB collation, which
    # won't match a Python string sort over arbitrary real prod companies, so
    # don't assert the tiebreak here (the seeded-fixture check below covers
    # correctness + relative order of this test's own data).
    for current, next_item in zip(body, body[1:]):
        assert current["active_count"] >= next_item["active_count"]

    seeded_slugs = {
        high_count_company.slug,
        low_count_company.slug,
        inactive_company.slug,
    }
    seeded = [item for item in body if item["slug"] in seeded_slugs]
    assert seeded == [
        {
            "slug": high_count_company.slug,
            "name": high_count_company.name,
            "domain": high_count_company.domain,
            "logo_url": high_count_company.logo_url,
            "active_count": 2,
        },
        {
            "slug": low_count_company.slug,
            "name": low_count_company.name,
            "domain": None,
            "logo_url": None,
            "active_count": 1,
        },
    ]


def test_top_companies_returns_ranked_active_companies(
    client: TestClient, db_session: Session
) -> None:
    suffix = str(uuid.uuid4())
    seen_at = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    best_company = models.Company(
        slug=f"top-company-best-{suffix}",
        name="Top Company Best",
        domain=f"top-company-best-{suffix}.example",
        logo_url=f"https://example.com/top-company/logo/{suffix}.png",
        prestige_rank=-30,
    )
    alpha_company = models.Company(
        slug=f"top-company-alpha-{suffix}",
        name="Top Company Alpha",
        prestige_rank=-20,
    )
    beta_company = models.Company(
        slug=f"top-company-beta-{suffix}",
        name="Top Company Beta",
        prestige_rank=-20,
    )
    later_company = models.Company(
        slug=f"top-company-later-{suffix}",
        name="Top Company Later",
        prestige_rank=-10,
    )
    unranked_company = models.Company(
        slug=f"top-company-unranked-{suffix}",
        name="Top Company Unranked",
    )
    inactive_company = models.Company(
        slug=f"top-company-inactive-{suffix}",
        name="Top Company Inactive",
        prestige_rank=-40,
    )

    db_session.add_all(
        [
            best_company,
            alpha_company,
            beta_company,
            later_company,
            unranked_company,
            inactive_company,
            models.Opportunity(
                slug=f"top-company-best-active-a-{suffix}",
                title="Top company best active A",
                company=best_company,
                apply_url=f"https://example.com/top-company/best-a/{suffix}",
                status="active",
                first_seen_at=seen_at,
                last_seen_at=seen_at,
            ),
            models.Opportunity(
                slug=f"top-company-best-active-b-{suffix}",
                title="Top company best active B",
                company=best_company,
                apply_url=f"https://example.com/top-company/best-b/{suffix}",
                status="active",
                first_seen_at=seen_at,
                last_seen_at=seen_at,
            ),
            models.Opportunity(
                slug=f"top-company-alpha-active-{suffix}",
                title="Top company alpha active",
                company=alpha_company,
                apply_url=f"https://example.com/top-company/alpha/{suffix}",
                status="active",
                first_seen_at=seen_at,
                last_seen_at=seen_at,
            ),
            models.Opportunity(
                slug=f"top-company-beta-active-{suffix}",
                title="Top company beta active",
                company=beta_company,
                apply_url=f"https://example.com/top-company/beta/{suffix}",
                status="active",
                first_seen_at=seen_at,
                last_seen_at=seen_at,
            ),
            models.Opportunity(
                slug=f"top-company-later-active-{suffix}",
                title="Top company later active",
                company=later_company,
                apply_url=f"https://example.com/top-company/later/{suffix}",
                status="active",
                first_seen_at=seen_at,
                last_seen_at=seen_at,
            ),
            models.Opportunity(
                slug=f"top-company-unranked-active-{suffix}",
                title="Top company unranked active",
                company=unranked_company,
                apply_url=f"https://example.com/top-company/unranked/{suffix}",
                status="active",
                first_seen_at=seen_at,
                last_seen_at=seen_at,
            ),
            models.Opportunity(
                slug=f"top-company-inactive-opp-{suffix}",
                title="Top company inactive",
                company=inactive_company,
                apply_url=f"https://example.com/top-company/inactive/{suffix}",
                status="expired",
                first_seen_at=seen_at,
                last_seen_at=seen_at,
            ),
        ]
    )
    db_session.flush()

    response = client.get("/companies/top?limit=24")

    assert response.status_code == 200
    body = response.json()
    seeded_slugs = {
        best_company.slug,
        alpha_company.slug,
        beta_company.slug,
        later_company.slug,
        unranked_company.slug,
        inactive_company.slug,
    }
    seeded = [item for item in body if item["slug"] in seeded_slugs]
    assert seeded == [
        {
            "slug": best_company.slug,
            "name": best_company.name,
            "domain": best_company.domain,
            "logo_url": best_company.logo_url,
            "active_count": 2,
        },
        {
            "slug": alpha_company.slug,
            "name": alpha_company.name,
            "domain": None,
            "logo_url": None,
            "active_count": 1,
        },
        {
            "slug": beta_company.slug,
            "name": beta_company.name,
            "domain": None,
            "logo_url": None,
            "active_count": 1,
        },
        {
            "slug": later_company.slug,
            "name": later_company.name,
            "domain": None,
            "logo_url": None,
            "active_count": 1,
        },
    ]


def test_top_companies_honours_limit(client: TestClient, db_session: Session) -> None:
    suffix = str(uuid.uuid4())
    seen_at = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    companies = [
        models.Company(
            slug=f"top-company-limit-{index}-{suffix}",
            name=f"Top Company Limit {index}",
            prestige_rank=-100 + index,
        )
        for index in range(3)
    ]
    opportunities = [
        models.Opportunity(
            slug=f"top-company-limit-opp-{index}-{suffix}",
            title=f"Top company limit {index}",
            company=company,
            apply_url=f"https://example.com/top-company/limit/{index}/{suffix}",
            status="active",
            first_seen_at=seen_at,
            last_seen_at=seen_at,
        )
        for index, company in enumerate(companies)
    ]
    db_session.add_all([*companies, *opportunities])
    db_session.flush()

    response = client.get("/companies/top?limit=2")

    assert response.status_code == 200
    body = response.json()
    assert [item["slug"] for item in body] == [
        companies[0].slug,
        companies[1].slug,
    ]


@pytest.mark.parametrize("limit", [0, 25])
def test_top_companies_rejects_out_of_bounds_limit(client: TestClient, limit: int) -> None:
    response = client.get(f"/companies/top?limit={limit}")

    assert response.status_code == 422
