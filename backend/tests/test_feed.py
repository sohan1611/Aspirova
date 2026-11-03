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


@pytest.mark.parametrize("sort", ["student", "recent", "deadline"])
def test_prefer_country_reorders_without_filtering_or_promoting_closed_rows(
    client: TestClient,
    db_session: Session,
    sort: str,
) -> None:
    suffix = uuid.uuid4().hex
    location = f"CountryPreference-{suffix}"
    now = datetime.now(UTC)
    rows = {}
    for index, (name, country, remote, closed) in enumerate(
        [
            ("foreign-remote", "US", True, False),
            ("foreign-office", "US", False, False),
            ("global-null", None, True, False),
            ("global-blank", "", True, False),
            ("local", "IN", False, False),
            ("closed-local", "IN", False, True),
        ]
    ):
        row = models.Opportunity(
            slug=f"preferred-{name}-{suffix}",
            title="Software Engineer",
            category="job",
            location=location,
            country=country,
            is_remote=remote,
            apply_url=f"https://example.com/preferred/{name}/{suffix}",
            primary_source="greenhouse",
            status="active",
            first_seen_at=now,
            last_seen_at=now - timedelta(minutes=index),
            deadline=now + timedelta(days=index + 1),
            closed_at=now - timedelta(days=1) if closed else None,
        )
        db_session.add(row)
        rows[name] = row
    db_session.flush()
    params = {"location": location, "sort": sort, "limit": 20, "kind": "roles"}
    global_response = client.get("/feed", params=params)
    preferred_response = client.get("/feed", params={**params, "prefer_country": "in"})
    assert global_response.status_code == preferred_response.status_code == 200
    global_body, preferred_body = global_response.json(), preferred_response.json()
    assert global_body["total"] == preferred_body["total"] == 6
    assert global_body["open_total"] == preferred_body["open_total"] == 5
    global_slugs = [item["slug"] for item in global_body["items"]]
    preferred_slugs = [item["slug"] for item in preferred_body["items"]]
    assert set(global_slugs) == set(preferred_slugs)
    assert preferred_slugs[-1] == rows["closed-local"].slug
    if sort == "deadline":
        assert preferred_slugs == global_slugs
    else:
        assert preferred_slugs != global_slugs
        assert preferred_slugs == [
            rows[name].slug
            for name in [
                "local",
                "global-null",
                "global-blank",
                "foreign-remote",
                "foreign-office",
                "closed-local",
            ]
        ]


@pytest.mark.parametrize("country", ["IND", "I", "1N", "", "India"])
def test_prefer_country_rejects_invalid_values(client: TestClient, country: str) -> None:
    assert client.get("/feed", params={"prefer_country": country}).status_code == 422
