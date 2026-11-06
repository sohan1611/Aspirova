import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from api import company as company_api
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
    seen_at = datetime.now(UTC) - timedelta(days=30)
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
    seen_at = datetime.now(UTC) - timedelta(days=30)
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
    seen_at = datetime.now(UTC) - timedelta(days=30)
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


@pytest.fixture
def logo_companies(db_session: Session, monkeypatch):
    suffix = uuid.uuid4().hex
    definitions = [
        ("blank", 1, None, None, None, "active"),
        ("favicon", 2, None, "favicon.example", None, "active"),
        ("prestige", 10, None, None, "https://example.com/prestige.png", "active"),
        ("forbes", None, 20, None, "https://example.com/forbes.png", "active"),
        ("both", 30, 1, None, "https://example.com/both.png", "active"),
        ("other-alpha", None, None, None, "https://example.com/alpha.png", "active"),
        ("other-beta", None, None, None, "https://example.com/beta.png", "active"),
        ("other-gamma", None, None, None, "https://example.com/gamma.png", "active"),
        ("inactive", 0, None, None, "https://example.com/inactive.png", "expired"),
    ]
    companies = {}
    for name, rank, global_rank, domain, logo_url, status in definitions:
        company = models.Company(
            slug=f"logo-strip-{name}-{suffix}",
            name=name,
            prestige_rank=rank,
            global_rank=global_rank,
            domain=f"{suffix}.{domain}" if domain else None,
            logo_url=logo_url,
        )
        db_session.add(
            models.Opportunity(
                slug=f"logo-strip-opp-{name}-{suffix}",
                title="Software Intern",
                company=company,
                category="internship",
                apply_url=f"https://example.com/{suffix}/{name}",
                status=status,
                last_seen_at=datetime.now(UTC),
            )
        )
        companies[name] = company
    db_session.flush()
    # Scope the unfiltered company strip to this fixture's rows.
    monkeypatch.setattr(
        company_api,
        "exclude_stale_opportunities",
        lambda: models.Opportunity.company_id.in_([company.id for company in companies.values()]),
    )
    return companies


@pytest.mark.parametrize(
    "limit,expected",
    [
        (2, ["prestige", "forbes"]),
        (3, ["prestige", "forbes", "both"]),
        (4, ["prestige", "other-alpha", "forbes", "both"]),
        (6, ["prestige", "other-alpha", "forbes", "other-beta", "both", "other-gamma"]),
        (24, ["prestige", "other-alpha", "forbes", "other-beta", "both", "other-gamma"]),
    ],
)
def test_top_companies_logo_preference_requires_logos_and_interleaves_famous(
    client: TestClient, logo_companies, limit: int, expected: list[str]
) -> None:
    response = client.get("/companies/top", params={"prefer_logos": "true", "limit": limit})
    assert response.status_code == 200
    assert [item["slug"] for item in response.json()] == [
        logo_companies[name].slug for name in expected
    ]
    assert all(item["active_count"] == 1 for item in response.json())
    assert all(item["logo_url"] is not None for item in response.json())


def test_top_companies_logo_preference_with_no_logos(
    client: TestClient, db_session: Session, logo_companies
) -> None:
    for company in logo_companies.values():
        company.logo_url = None
    db_session.flush()
    response = client.get("/companies/top", params={"prefer_logos": "true", "limit": 24})
    assert response.status_code == 200
    assert response.json() == []


def test_top_companies_without_usable_images_returns_empty(
    client: TestClient, db_session: Session, logo_companies
) -> None:
    for company in logo_companies.values():
        company.logo_url = None
        company.domain = None
    db_session.flush()
    response = client.get("/companies/top", params={"prefer_logos": "true"})
    assert response.status_code == 200
    assert response.json() == []


def test_top_companies_uses_all_famous_when_fewer_than_half(
    client: TestClient, db_session: Session, logo_companies
) -> None:
    for name in ["forbes", "both"]:
        logo_companies[name].prestige_rank = None
        logo_companies[name].global_rank = None
    db_session.flush()
    response = client.get("/companies/top", params={"prefer_logos": "true", "limit": 6})
    assert response.status_code == 200
    assert [item["slug"] for item in response.json()] == [
        logo_companies[name].slug
        for name in ["prestige", "both", "forbes", "other-alpha", "other-beta", "other-gamma"]
    ]


def test_top_companies_parameter_absent_keeps_prestige_only_order(client, logo_companies):
    response = client.get("/companies/top", params={"limit": 24})
    assert response.status_code == 200
    assert [item["slug"] for item in response.json()] == [
        logo_companies[name].slug for name in ["blank", "favicon", "prestige", "both"]
    ]
