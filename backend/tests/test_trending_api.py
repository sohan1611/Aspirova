import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from api import middleware, trending
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
    monkeypatch.setattr(trending, "get_redis", lambda: None)
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


def _opportunity(
    suffix: str,
    name: str,
    company: models.Company,
    *,
    category: str = "job",
    status: str = "active",
    deadline: datetime | None = None,
    meta: dict[str, bool] | None = None,
) -> models.Opportunity:
    return models.Opportunity(
        slug=f"trending-{name}-{suffix}",
        title=f"Trending {name}",
        company=company,
        category=category,
        apply_url=f"https://example.com/trending/{name}/{suffix}",
        status=status,
        deadline=deadline,
        meta=meta,
        last_seen_at=datetime.now(UTC),
    )


def test_opportunity_view_endpoint_increments_counter(
    client: TestClient,
    db_session: Session,
) -> None:
    suffix = uuid.uuid4().hex
    company = models.Company(
        slug=f"trending-view-company-{suffix}",
        name=f"Trending View Company {suffix}",
    )
    opportunity = _opportunity(suffix, "view-counter", company)
    db_session.add_all([company, opportunity])
    db_session.flush()

    first = client.post(f"/opportunities/{opportunity.slug}/view")
    second = client.post(f"/opportunities/{opportunity.slug}/view")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == {"ok": True}
    assert second.json() == {"ok": True}
    count = db_session.scalar(
        select(models.OpportunityViewCount).where(
            models.OpportunityViewCount.opportunity_id == opportunity.id
        )
    )
    assert count is not None
    assert count.views == 2


def test_trending_returns_qualified_roles_in_descending_view_order(
    client: TestClient,
    db_session: Session,
) -> None:
    suffix = uuid.uuid4().hex
    company = models.Company(
        slug=f"trending-order-company-{suffix}",
        name=f"Trending Order Company {suffix}",
    )
    below_threshold = _opportunity(suffix, "below-threshold", company)
    lower = _opportunity(suffix, "lower", company, category="internship")
    higher = _opportunity(suffix, "higher", company)
    db_session.add_all([company, below_threshold, lower, higher])
    db_session.flush()
    db_session.add_all(
        [
            models.OpportunityViewCount(
                opportunity_id=below_threshold.id,
                views=2,
            ),
            models.OpportunityViewCount(opportunity_id=lower.id, views=10_000),
            models.OpportunityViewCount(opportunity_id=higher.id, views=10_001),
        ]
    )
    db_session.flush()

    response = client.get("/trending", params={"limit": 24})

    assert response.status_code == 200
    slugs = [item["slug"] for item in response.json()["items"]]
    assert below_threshold.slug not in slugs
    assert higher.slug in slugs
    assert lower.slug in slugs
    assert slugs.index(higher.slug) < slugs.index(lower.slug)


def test_opportunity_view_endpoint_returns_404_for_unknown_slug(
    client: TestClient,
) -> None:
    response = client.post(f"/opportunities/unknown-trending-{uuid.uuid4().hex}/view")

    assert response.status_code == 404


def test_trending_excludes_inactive_and_closed_opportunities(
    client: TestClient,
    db_session: Session,
) -> None:
    suffix = uuid.uuid4().hex
    now = datetime.now(UTC)
    company = models.Company(
        slug=f"trending-exclusion-company-{suffix}",
        name=f"Trending Exclusion Company {suffix}",
    )
    visible = _opportunity(suffix, "visible", company)
    inactive = _opportunity(suffix, "inactive", company, status="inactive")
    closed_competition = _opportunity(
        suffix,
        "closed-competition",
        company,
        category="competition",
        deadline=now - timedelta(days=15),
        meta={"offers_ppi": True},
    )
    db_session.add_all([company, visible, inactive, closed_competition])
    db_session.flush()
    db_session.add_all(
        [
            models.OpportunityViewCount(opportunity_id=visible.id, views=20_000),
            models.OpportunityViewCount(opportunity_id=inactive.id, views=30_000),
            models.OpportunityViewCount(
                opportunity_id=closed_competition.id,
                views=30_000,
            ),
        ]
    )
    db_session.flush()

    response = client.get("/trending", params={"limit": 24})

    assert response.status_code == 200
    slugs = {item["slug"] for item in response.json()["items"]}
    assert visible.slug in slugs
    assert inactive.slug not in slugs
    assert closed_competition.slug not in slugs
