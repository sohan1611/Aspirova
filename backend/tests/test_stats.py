import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api import middleware
from api.deps import get_db
from api.main import app
from core import models
from core.config import get_settings


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


def test_stats_returns_active_counts_and_shape(client: TestClient, db_session: Session) -> None:
    baseline = db_session.execute(
        select(
            func.count(models.Opportunity.id).label("opportunities"),
            func.count(func.distinct(models.Opportunity.company_id)).label("companies"),
            func.count(func.distinct(models.Opportunity.primary_source)).label("sources"),
            func.max(models.Opportunity.last_seen_at).label("updated_at"),
        ).where(models.Opportunity.status == "active")
    ).one()

    suffix = uuid.uuid4().hex
    older_active_at = datetime(2099, 1, 1, 12, 0, tzinfo=UTC)
    newest_active_at = datetime(2099, 1, 2, 12, 0, tzinfo=UTC)
    inactive_at = datetime(2099, 1, 3, 12, 0, tzinfo=UTC)
    company_a = models.Company(slug=f"stats-company-a-{suffix}", name="Stats Company A")
    company_b = models.Company(slug=f"stats-company-b-{suffix}", name="Stats Company B")
    inactive_company = models.Company(
        slug=f"stats-company-inactive-{suffix}", name="Stats Company Inactive"
    )
    source_a = f"stats-source-a-{suffix}"
    source_b = f"stats-source-b-{suffix}"
    opportunities = [
        models.Opportunity(
            slug=f"stats-active-a1-{suffix}",
            title="Stats active A1",
            company=company_a,
            primary_source=source_a,
            apply_url=f"https://example.com/stats/active-a1/{suffix}",
            status="active",
            last_seen_at=older_active_at,
        ),
        models.Opportunity(
            slug=f"stats-active-a2-{suffix}",
            title="Stats active A2",
            company=company_a,
            primary_source=source_b,
            apply_url=f"https://example.com/stats/active-a2/{suffix}",
            status="active",
            last_seen_at=newest_active_at,
        ),
        models.Opportunity(
            slug=f"stats-active-b-{suffix}",
            title="Stats active B",
            company=company_b,
            primary_source=source_a,
            apply_url=f"https://example.com/stats/active-b/{suffix}",
            status="active",
            last_seen_at=older_active_at,
        ),
        models.Opportunity(
            slug=f"stats-active-null-dimensions-{suffix}",
            title="Stats active without company or source",
            apply_url=f"https://example.com/stats/active-null/{suffix}",
            status="active",
            last_seen_at=older_active_at,
        ),
        models.Opportunity(
            slug=f"stats-inactive-{suffix}",
            title="Stats inactive",
            company=inactive_company,
            primary_source=f"stats-source-inactive-{suffix}",
            apply_url=f"https://example.com/stats/inactive/{suffix}",
            status="expired",
            last_seen_at=inactive_at,
        ),
    ]
    db_session.add_all([company_a, company_b, inactive_company, *opportunities])
    db_session.flush()

    response = client.get("/stats")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"opportunities", "companies", "sources", "updated_at"}
    assert isinstance(body["opportunities"], int)
    assert isinstance(body["companies"], int)
    assert isinstance(body["sources"], int)
    assert isinstance(body["updated_at"], str)
    assert body["opportunities"] == baseline.opportunities + 4
    assert body["companies"] == baseline.companies + 2
    assert body["sources"] == baseline.sources + 2
    expected_updated_at = max(
        timestamp for timestamp in (baseline.updated_at, newest_active_at) if timestamp is not None
    )
    assert datetime.fromisoformat(body["updated_at"]) == expected_updated_at


class FakeCacheRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.expirations: list[int | None] = []

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None, **_kwargs) -> None:
        self.store[key] = value
        self.expirations.append(ex)


def test_stats_is_cached_for_its_route_specific_ttl(
    client: TestClient, db_session: Session, monkeypatch
) -> None:
    fake = FakeCacheRedis()
    monkeypatch.setattr(middleware, "get_redis", lambda: fake)
    execute_count = 0
    original_execute = db_session.execute

    def counting_execute(*args, **kwargs):
        nonlocal execute_count
        execute_count += 1
        return original_execute(*args, **kwargs)

    monkeypatch.setattr(db_session, "execute", counting_execute)

    first = client.get("/stats")
    second = client.get("/stats")

    assert first.status_code == 200
    assert first.headers["X-Cache"] == "MISS"
    assert second.status_code == 200
    assert second.headers["X-Cache"] == "HIT"
    assert second.json() == first.json()
    assert execute_count == 1
    assert fake.expirations == [get_settings().stats_cache_ttl_seconds]
