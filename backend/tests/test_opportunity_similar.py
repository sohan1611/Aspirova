import uuid
from datetime import UTC, datetime, timedelta

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


def _opportunity(
    *,
    suffix: str,
    name: str,
    company: models.Company | None = None,
    category: str | None = None,
    country: str | None = None,
    first_seen_at: datetime,
    status: str = "active",
    deadline: datetime | None = None,
) -> models.Opportunity:
    return models.Opportunity(
        slug=f"similar-{name}-{suffix}",
        title=f"Similar {name}",
        company=company,
        category=category,
        country=country,
        apply_url=f"https://example.com/similar/{name}/{suffix}",
        first_seen_at=first_seen_at,
        last_seen_at=first_seen_at,
        status=status,
        deadline=deadline,
    )


def test_similar_same_company_results_come_first(client: TestClient, db_session: Session) -> None:
    suffix = uuid.uuid4().hex
    now = datetime.now(UTC)
    category = f"similar-category-{suffix}"
    company = models.Company(
        slug=f"similar-company-{suffix}",
        name=f"Similar Company {suffix}",
    )
    other_company = models.Company(
        slug=f"similar-other-company-{suffix}",
        name=f"Similar Other Company {suffix}",
    )
    target = _opportunity(
        suffix=suffix,
        name="target",
        company=company,
        category=category,
        country="ZZ",
        first_seen_at=now - timedelta(days=4),
    )
    same_company_recent = _opportunity(
        suffix=suffix,
        name="same-company-recent",
        company=company,
        category="job",
        country="US",
        first_seen_at=now - timedelta(days=1),
    )
    same_company_older = _opportunity(
        suffix=suffix,
        name="same-company-older",
        company=company,
        category="competition",
        country="IN",
        first_seen_at=now - timedelta(days=2),
    )
    same_category_country = _opportunity(
        suffix=suffix,
        name="same-category-country",
        company=other_company,
        category=category,
        country="ZZ",
        first_seen_at=now,
    )
    db_session.add_all(
        [
            company,
            other_company,
            target,
            same_company_recent,
            same_company_older,
            same_category_country,
        ]
    )
    db_session.flush()

    response = client.get(f"/opportunity/{target.slug}/similar", params={"limit": 4})

    assert response.status_code == 200
    items = response.json()
    assert [item["slug"] for item in items[:2]] == [
        same_company_recent.slug,
        same_company_older.slug,
    ]
    assert items[2]["slug"] == same_category_country.slug
    assert all(item["slug"] != target.slug for item in items)
    assert items[2]["country"] == "ZZ"


def test_similar_excludes_closed_competitions_and_target(
    client: TestClient,
    db_session: Session,
) -> None:
    suffix = uuid.uuid4().hex
    now = datetime.now(UTC)
    company = models.Company(
        slug=f"similar-closed-company-{suffix}",
        name=f"Similar Closed Company {suffix}",
    )
    target = _opportunity(
        suffix=suffix,
        name="target",
        company=company,
        category="internship",
        country="IN",
        first_seen_at=now,
    )
    active = _opportunity(
        suffix=suffix,
        name="active",
        company=company,
        category="job",
        country="US",
        first_seen_at=now - timedelta(days=1),
    )
    closed = _opportunity(
        suffix=suffix,
        name="closed",
        company=company,
        category="competition",
        country="IN",
        first_seen_at=now - timedelta(days=2),
        deadline=now - timedelta(days=15),
    )
    db_session.add_all([company, target, active, closed])
    db_session.flush()

    response = client.get(f"/opportunity/{target.slug}/similar", params={"limit": 12})

    assert response.status_code == 200
    slugs = {item["slug"] for item in response.json()}
    assert active.slug in slugs
    assert target.slug not in slugs
    assert closed.slug not in slugs


def test_similar_respects_limit(client: TestClient, db_session: Session) -> None:
    suffix = uuid.uuid4().hex
    now = datetime.now(UTC)
    company = models.Company(
        slug=f"similar-limit-company-{suffix}",
        name=f"Similar Limit Company {suffix}",
    )
    target = _opportunity(
        suffix=suffix,
        name="target",
        company=company,
        category="job",
        country="US",
        first_seen_at=now,
    )
    candidates = [
        _opportunity(
            suffix=suffix,
            name=f"candidate-{index}",
            company=company,
            category="internship",
            country="IN",
            first_seen_at=now - timedelta(hours=index + 1),
        )
        for index in range(3)
    ]
    db_session.add_all([company, target, *candidates])
    db_session.flush()

    response = client.get(f"/opportunity/{target.slug}/similar", params={"limit": 2})

    assert response.status_code == 200
    assert [item["slug"] for item in response.json()] == [
        candidates[0].slug,
        candidates[1].slug,
    ]


def test_similar_is_empty_safe_when_nothing_matches(
    client: TestClient,
    db_session: Session,
) -> None:
    suffix = uuid.uuid4().hex
    now = datetime.now(UTC)
    company = models.Company(
        slug=f"similar-empty-company-{suffix}",
        name=f"Similar Empty Company {suffix}",
    )
    target = _opportunity(
        suffix=suffix,
        name="target",
        company=company,
        category=f"similar-empty-category-{suffix}",
        first_seen_at=now,
    )
    db_session.add_all([company, target])
    db_session.flush()

    response = client.get(f"/opportunity/{target.slug}/similar")

    assert response.status_code == 200
    assert response.json() == []
