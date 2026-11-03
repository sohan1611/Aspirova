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


def test_promoted_surfaces_exclude_stale_rows_but_detail_remains_reachable(
    client: TestClient,
    db_session: Session,
) -> None:
    suffix = uuid.uuid4().hex
    term = f"stalepromoted{suffix}"
    location_token = f"StalePromotedville-{suffix}"
    now = datetime.now(UTC)
    company = models.Company(
        slug=f"stale-promoted-company-{suffix}",
        name=f"Stale Promoted Company {suffix}",
    )
    stale = models.Opportunity(
        slug=f"stale-promoted-stale-{suffix}",
        title=f"{term} stale role",
        company=company,
        category="job",
        location=location_token,
        apply_url=f"https://example.com/stale-promoted/stale/{suffix}",
        posted_at=now - timedelta(days=STALE_AFTER_DAYS + 1),
        deadline=None,
        status="active",
        first_seen_at=now,
        last_seen_at=now,
    )
    old_with_future_deadline = models.Opportunity(
        slug=f"stale-promoted-future-deadline-{suffix}",
        title=f"{term} old role with future deadline",
        company=company,
        category="job",
        location=location_token,
        apply_url=f"https://example.com/stale-promoted/future/{suffix}",
        posted_at=now - timedelta(days=STALE_AFTER_DAYS + 1),
        deadline=now + timedelta(days=10),
        status="active",
        first_seen_at=now,
        last_seen_at=now,
    )
    unknown_posted_at = models.Opportunity(
        slug=f"stale-promoted-null-posted-at-{suffix}",
        title=f"{term} null posted_at role",
        company=company,
        category="job",
        location=location_token,
        apply_url=f"https://example.com/stale-promoted/null-posted-at/{suffix}",
        posted_at=None,
        deadline=None,
        status="active",
        first_seen_at=now,
        last_seen_at=now,
    )
    recent = models.Opportunity(
        slug=f"stale-promoted-recent-{suffix}",
        title=f"{term} recent role",
        company=company,
        category="job",
        location=location_token,
        apply_url=f"https://example.com/stale-promoted/recent/{suffix}",
        posted_at=now - timedelta(days=30),
        deadline=None,
        status="active",
        first_seen_at=now,
        last_seen_at=now,
    )
    db_session.add_all([company, stale, old_with_future_deadline, unknown_posted_at, recent])
    db_session.flush()

    feed = client.get("/feed", params={"location": location_token, "limit": 10})
    search = client.get("/search", params={"q": term, "limit": 10})
    for_you = client.get(
        "/for-you",
        params={"terms": term, "categories": "job", "limit": 10},
    )
    detail = client.get(f"/opportunity/{stale.slug}")

    assert feed.status_code == 200
    assert search.status_code == 200
    assert for_you.status_code == 200
    expected_promoted_slugs = {
        old_with_future_deadline.slug,
        unknown_posted_at.slug,
        recent.slug,
    }
    assert feed.json()["total"] == 3
    assert {item["slug"] for item in feed.json()["items"]} == expected_promoted_slugs
    assert search.json()["total"] == 3
    assert {item["slug"] for item in search.json()["items"]} == expected_promoted_slugs
    assert for_you.json()["total"] == 3
    assert {item["slug"] for item in for_you.json()["items"]} == expected_promoted_slugs
    assert detail.status_code == 200
    assert detail.json()["slug"] == stale.slug
    assert detail.json()["is_stale"] is True

    current_detail = client.get(f"/opportunity/{old_with_future_deadline.slug}")
    null_posted_at_detail = client.get(f"/opportunity/{unknown_posted_at.slug}")

    assert current_detail.status_code == 200
    assert current_detail.json()["is_stale"] is False
    assert null_posted_at_detail.status_code == 200
    assert null_posted_at_detail.json()["is_stale"] is False


@pytest.mark.parametrize("sort", ["student", "recent", "deadline"])
def test_feed_total_includes_closed_rows_but_open_total_does_not(
    client: TestClient, db_session: Session, sort: str
) -> None:
    suffix = uuid.uuid4().hex
    location_token = f"OpenCountville-{suffix}"
    now = datetime.now(UTC)
    listings = []
    for state, fields in [
        ("open", {}),
        ("future-deadline", {"deadline": now + timedelta(days=5)}),
        ("closed", {"closed_at": now - timedelta(days=1)}),
        ("past-deadline", {"deadline": now - timedelta(days=1)}),
    ]:
        listings.append(
            models.Opportunity(
                slug=f"feed-open-count-{state}-{suffix}",
                title=f"Open count {state} role",
                category="job",
                location=location_token,
                apply_url=f"https://example.com/feed-open-count/{state}/{suffix}",
                status="active",
                first_seen_at=now,
                last_seen_at=now,
                **fields,
            )
        )
    db_session.add_all(listings)
    db_session.flush()

    slugs = []
    for page in range(1, 5):
        response = client.get(
            "/feed",
            params={"location": location_token, "sort": sort, "limit": 1, "page": page},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 4
        assert body["open_total"] == 2
        assert body["page"] == page
        assert body["limit"] == 1
        assert len(body["items"]) == 1
        slugs.append(body["items"][0]["slug"])

    assert set(slugs[:2]) == {listing.slug for listing in listings[:2]}
    assert set(slugs[2:]) == {listing.slug for listing in listings[2:]}

    empty = client.get(
        "/feed",
        params={"location": location_token, "sort": sort, "limit": 1, "page": 5},
    )
    assert empty.status_code == 200
    assert empty.json()["items"] == []
    assert empty.json()["total"] == 0
    assert empty.json()["open_total"] == 0
