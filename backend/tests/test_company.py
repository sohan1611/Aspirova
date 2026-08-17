import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from api import middleware
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


def test_company_surfaces_exclude_stale_roles_but_keep_unknown_posted_at(
    client: TestClient,
    db_session: Session,
) -> None:
    suffix = uuid.uuid4().hex
    now = datetime.now(UTC)
    company = models.Company(
        slug=f"company-stale-filter-{suffix}",
        name=f"Company Stale Filter {suffix}",
        domain=f"company-stale-filter-{suffix}.example",
        logo_url=f"https://example.com/company-stale-filter/{suffix}.png",
        prestige_rank=-900_000,
    )
    recent = models.Opportunity(
        slug=f"company-stale-filter-recent-{suffix}",
        title="Company stale filter recent",
        company=company,
        apply_url=f"https://example.com/company-stale-filter/recent/{suffix}",
        status="active",
        posted_at=now - timedelta(days=1),
        first_seen_at=now - timedelta(minutes=1),
        last_seen_at=now,
    )
    unknown_posted_at = models.Opportunity(
        slug=f"company-stale-filter-null-posted-at-{suffix}",
        title="Company stale filter null posted_at",
        company=company,
        apply_url=f"https://example.com/company-stale-filter/null-posted-at/{suffix}",
        status="active",
        posted_at=None,
        first_seen_at=now - timedelta(minutes=2),
        last_seen_at=now,
    )
    old_with_future_deadline = models.Opportunity(
        slug=f"company-stale-filter-future-deadline-{suffix}",
        title="Company stale filter future deadline",
        company=company,
        apply_url=f"https://example.com/company-stale-filter/future-deadline/{suffix}",
        status="active",
        posted_at=now - timedelta(days=STALE_AFTER_DAYS + 1),
        deadline=now + timedelta(days=10),
        first_seen_at=now - timedelta(minutes=3),
        last_seen_at=now,
    )
    stale = models.Opportunity(
        slug=f"company-stale-filter-stale-{suffix}",
        title="Company stale filter stale",
        company=company,
        apply_url=f"https://example.com/company-stale-filter/stale/{suffix}",
        status="active",
        posted_at=now - timedelta(days=STALE_AFTER_DAYS + 1),
        deadline=None,
        first_seen_at=now,
        last_seen_at=now,
    )
    db_session.add_all([company, recent, unknown_posted_at, old_with_future_deadline, stale])
    db_session.flush()

    companies = client.get("/companies")
    top_companies = client.get("/companies/top?limit=24")
    company_page = client.get(f"/company/{company.slug}", params={"limit": 10})

    assert companies.status_code == 200
    assert top_companies.status_code == 200
    assert company_page.status_code == 200

    company_list_item = next(item for item in companies.json() if item["slug"] == company.slug)
    top_company_item = next(item for item in top_companies.json() if item["slug"] == company.slug)
    body = company_page.json()
    page_slugs = {item["slug"] for item in body["items"]}
    expected_slugs = {
        recent.slug,
        unknown_posted_at.slug,
        old_with_future_deadline.slug,
    }

    assert company_list_item["active_count"] == 3
    assert top_company_item["active_count"] == 3
    assert body["total"] == 3
    assert expected_slugs <= page_slugs
    assert stale.slug not in page_slugs
