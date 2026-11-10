"""Closed listings leave discovery immediately but remain readable in histories."""

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from api import facets, for_you, middleware, opportunity, sitemap, trending
from api.auth import get_current_user
from api.deps import get_db
from api.filters import exclude_stale_opportunities, saved_search_base_filters
from api.main import app
from core import models
from pipeline import liveness


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
def closed_rows(db_session: Session, monkeypatch):
    suffix = uuid.uuid4().hex
    now = datetime.now(UTC)
    term = f"closureregression{suffix}"
    company = models.Company(slug=f"closed-states-{suffix}", name=f"Closed States {suffix}")
    user = models.User(email=f"closed-states-{suffix}@example.com")
    rows = {}
    for name, category, fields in [
        ("open-role", "job", {}),
        ("closed-role", "job", {"closed_at": now - timedelta(days=1)}),
        ("past-role", "job", {"deadline": now - timedelta(days=2)}),
        ("open-competition", "competition", {"deadline": now + timedelta(days=2)}),
        ("closed-competition", "competition", {"deadline": now - timedelta(days=2)}),
        ("old-competition", "competition", {"deadline": now - timedelta(days=15)}),
    ]:
        row = models.Opportunity(
            slug=f"closed-states-{name}-{suffix}",
            title=f"{term} {name}",
            company=company,
            category=category,
            location=suffix,
            apply_url=f"https://example.com/{suffix}/{name}",
            status="active",
            first_seen_at=now,
            last_seen_at=now - timedelta(days=5),
            **fields,
        )
        db_session.add(row)
        rows[name] = row
    db_session.add(user)
    db_session.flush()
    for row in rows.values():
        db_session.add(models.OpportunityViewCount(opportunity_id=row.id, views=100))
    db_session.add(
        models.Bookmark(user_id=user.id, opportunity_id=rows["closed-role"].id, status="applied")
    )
    db_session.flush()

    # These endpoints lack company filtering; isolate discovery and sitemap counts.
    for module in (facets, for_you, opportunity, sitemap, trending):
        monkeypatch.setattr(
            module,
            "exclude_stale_opportunities",
            lambda: and_(
                exclude_stale_opportunities(), models.Opportunity.company_id == company.id
            ),
        )
    return {"rows": rows, "company": company, "user": user, "term": term, "now": now}


@pytest.fixture
def client(db_session: Session, closed_rows, monkeypatch):
    monkeypatch.setattr(middleware, "get_redis", lambda: None)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: closed_rows["user"]
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)


def _slugs(response):
    assert response.status_code == 200
    body = response.json()
    return {item["slug"] for item in body["items"]}


@pytest.mark.parametrize("endpoint", ["/feed", "/search"])
@pytest.mark.parametrize("status", [None, "open"])
def test_default_and_open_discovery_exclude_both_closure_signals(
    client, closed_rows, endpoint, status
):
    params = {"company": closed_rows["company"].slug, "limit": 100}
    if endpoint == "/search":
        params["q"] = closed_rows["term"]
    if status:
        params["status"] = status
    response = client.get(endpoint, params=params)
    rows = closed_rows["rows"]
    assert _slugs(response) == {rows["open-role"].slug, rows["open-competition"].slug}
    assert response.json()["total"] == 2


@pytest.mark.parametrize("endpoint", ["/feed", "/search"])
def test_explicit_closed_competitions_keep_only_existing_grace(client, closed_rows, endpoint):
    params = {
        "company": closed_rows["company"].slug,
        "kind": "competitions",
        "status": "closed",
    }
    if endpoint == "/search":
        params["q"] = closed_rows["term"]
    response = client.get(endpoint, params=params)
    assert _slugs(response) == {closed_rows["rows"]["closed-competition"].slug}
    assert response.json()["items"][0]["deadline"] is not None
    if endpoint == "/feed":
        assert response.json()["open_total"] == 0


def test_detail_and_saved_tracker_keep_closed_listing_and_signals(client, closed_rows):
    rows = closed_rows["rows"]
    detail = client.get(f"/opportunity/{rows['closed-role'].slug}")
    assert detail.status_code == 200
    assert datetime.fromisoformat(detail.json()["closed_at"]) == rows["closed-role"].closed_at
    assert detail.json()["apply_url"] == rows["closed-role"].apply_url
    competition = client.get(f"/opportunity/{rows['closed-competition'].slug}")
    assert competition.status_code == 200
    assert (
        datetime.fromisoformat(competition.json()["deadline"])
        == rows["closed-competition"].deadline
    )

    saved = client.get("/bookmarks")
    assert saved.status_code == 200
    assert len(saved.json()) == 1
    assert saved.json()[0]["slug"] == rows["closed-role"].slug
    assert saved.json()[0]["closed_at"] == detail.json()["closed_at"]
    assert saved.json()[0]["bookmark_status"] == "applied"


def test_other_discovery_and_sitemap_exclude_closed_immediately(client, closed_rows):
    rows = closed_rows["rows"]
    opened = {rows["open-role"].slug, rows["open-competition"].slug}
    assert _slugs(client.get("/for-you", params={"categories": "job,competition"})) == opened
    assert _slugs(client.get("/trending")) == {rows["open-role"].slug}
    similar = client.get(f"/opportunity/{rows['closed-role'].slug}/similar")
    assert similar.status_code == 200
    assert {item["slug"] for item in similar.json()} == opened
    counts = client.get("/facets")
    assert counts.status_code == 200
    assert counts.json()["company_counts"] == [
        {"value": closed_rows["company"].slug, "label": closed_rows["company"].name, "count": 2}
    ]
    sitemap_rows = client.get("/sitemap-opportunities")
    assert sitemap_rows.status_code == 200
    assert {item["slug"] for item in sitemap_rows.json()} == opened
    assert client.get("/sitemap-opportunities/count").json()["total"] == 2


def test_saved_search_defaults_exclude_closed_and_explicit_closed_keeps_grace(
    db_session, closed_rows
):
    def matching(params):
        return set(
            db_session.scalars(
                select(models.Opportunity.slug).where(
                    models.Opportunity.company_id == closed_rows["company"].id,
                    *saved_search_base_filters(params),
                )
            )
        )

    rows = closed_rows["rows"]
    assert matching({}) == {rows["open-role"].slug, rows["open-competition"].slug}
    assert matching({"kind": "competitions", "status": "closed"}) == {
        rows["closed-competition"].slug
    }


def test_liveness_503_leaves_role_open_and_discoverable(
    client, db_session, closed_rows, monkeypatch
):
    row = closed_rows["rows"]["open-role"]
    candidate = liveness.LivenessCandidate(id=row.id, apply_url=row.apply_url)
    monkeypatch.setattr(liveness, "_select_candidates", lambda session, *, limit: [candidate])
    checked_urls = []

    def respond(request):
        checked_urls.append(str(request.url))
        return httpx.Response(503)

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        result = liveness.check_listing_liveness(
            db_session,
            apply=True,
            now=closed_rows["now"],
            checker=lambda url: liveness.fetch_url_liveness_status(url, http),
            commit_each_batch=False,
        )
    db_session.expire_all()
    assert checked_urls == [row.apply_url]
    assert result.scanned == result.inconclusive == 1
    assert result.closed == 0
    assert row.status == "active"
    assert row.closed_at is None
    assert row.meta["liveness_checked_at"] == closed_rows["now"].isoformat()
    for endpoint in ("/feed", "/search"):
        params = {"company": closed_rows["company"].slug, "q": closed_rows["term"]}
        assert row.slug in _slugs(client.get(endpoint, params=params))
