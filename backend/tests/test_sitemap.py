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
