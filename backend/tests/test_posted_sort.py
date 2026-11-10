"""Posting freshness, search sorts and the shared deadline boundary (S-07)."""

import uuid
from datetime import UTC, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import case, func, select, text
from sqlalchemy.orm import Session

from api import for_you, middleware
from api.deps import get_db
from api.facets import _deadline_within_facets
from api.filters import exclude_stale_opportunities, listing_closed
from api.main import app
from api.search import TRIGRAM_FALLBACK_THRESHOLD, _search_ordering
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


@pytest.fixture
def listing_factory(db_session: Session):
    suffix = uuid.uuid4().hex
    now = db_session.scalar(select(func.now())).astimezone(UTC)
    company = models.Company(slug=f"posted-sort-{suffix}", name=f"Posted Sort {suffix}")
    term = f"postedsort{suffix}"

    def add(name, **fields):
        values = {
            "title": f"{term} {name}",
            "category": "competition",
            "primary_source": "greenhouse",
            "status": "active",
            "first_seen_at": now,
            "last_seen_at": now,
        }
        values.update(fields)
        row = models.Opportunity(
            slug=f"posted-sort-{name}-{suffix}",
            company=company,
            apply_url=f"https://example.com/{suffix}/{name}",
            **values,
        )
        db_session.add(row)
        return row

    return add, company, term, now


@pytest.fixture(params=["fts", "trigram"])
def search_sort_rows(request, listing_factory, db_session):
    add, company, term, now = listing_factory
    query = term
    titles = [f"{term} " * 4, f"{term} role", f"{term} opportunity"]
    if request.param == "trigram":
        query = f"sofware enginer {term}"
        titles = [f"Software Engineer {term} role {index}" for index in range(3)]
    old = add(
        "old",
        title=titles[0],
        title_normalized=titles[0].lower(),
        posted_at=now - timedelta(days=30),
        deadline=now + timedelta(days=3),
        meta={"prize_inr": 500},
    )
    newer = add(
        "newer",
        title=titles[1],
        title_normalized=titles[1].lower(),
        posted_at=now - timedelta(days=1),
        last_seen_at=now - timedelta(days=2),
        deadline=now + timedelta(days=2),
        meta={"prize_inr": 100},
    )
    unknown_posted = add(
        "unknown-posted",
        title=titles[2],
        title_normalized=titles[2].lower(),
        posted_at=None,
        first_seen_at=now - timedelta(hours=3),
    )
    db_session.flush()
    tsquery = func.websearch_to_tsquery("english", query)
    fts_count = db_session.scalar(
        select(func.count())
        .select_from(models.Opportunity)
        .where(
            models.Opportunity.company_id == company.id,
            models.Opportunity.search_tsv.op("@@")(tsquery),
        )
    )
    relevance = func.ts_rank(models.Opportunity.search_tsv, tsquery)
    if request.param == "trigram":
        assert fts_count == 0
        relevance = func.similarity(models.Opportunity.title_normalized, query.lower())
        assert (
            db_session.scalar(
                select(func.min(relevance)).where(models.Opportunity.company_id == company.id)
            )
            >= TRIGRAM_FALLBACK_THRESHOLD
        )
    else:
        assert fts_count == 3
    return company, query, [old, newer, unknown_posted], relevance


def _slugs(response):
    assert response.status_code == 200
    return [item["slug"] for item in response.json()["items"]]


def test_recent_feed_uses_posting_date_and_first_seen_fallback(client, search_sort_rows):
    company, _query, rows, _relevance = search_sort_rows
    old, newer, unknown_posted = rows
    assert _slugs(client.get("/feed", params={"company": company.slug, "sort": "recent"})) == [
        unknown_posted.slug,
        newer.slug,
        old.slug,
    ]


@pytest.mark.parametrize("sort", ["recent", "deadline", "student", "prize"])
def test_search_sorts_both_matching_paths_with_stable_pagination(
    client, db_session, search_sort_rows, sort
):
    company, query, rows, relevance = search_sort_rows
    old, newer, unknown_posted = rows
    expected = {
        "recent": [unknown_posted.slug, newer.slug, old.slug],
        "deadline": [newer.slug, old.slug, unknown_posted.slug],
        "prize": [old.slug, newer.slug, unknown_posted.slug],
        "student": list(
            db_session.scalars(
                select(models.Opportunity.slug)
                .where(models.Opportunity.company_id == company.id)
                .order_by(relevance.desc(), models.Opportunity.id.desc())
            )
        ),
    }[sort]
    params = {"q": query, "company": company.slug, "sort": sort, "limit": 2}
    first = client.get("/search", params=params)
    second = client.get("/search", params={**params, "page": 2})
    assert _slugs(first) + _slugs(second) == expected
    assert first.json()["total"] == second.json()["total"] == 3
    assert _slugs(client.get("/search", params=params)) == expected[:2]
    if sort == "student":
        assert (
            _slugs(client.get("/search", params={"q": query, "company": company.slug})) == expected
        )


def test_recent_round_robin_stays_within_utc_day(client, db_session, listing_factory):
    add, company, _term, now = listing_factory
    today = now.replace(hour=12, minute=0, second=0, microsecond=0)
    rows = []
    for index in range(3):
        for source, offset in [("greenhouse", 0), ("lever", 30)]:
            rows.append(
                add(
                    f"{source}-{index}",
                    primary_source=source,
                    posted_at=today - timedelta(minutes=index + offset),
                )
            )
    old = add("quiet-source", primary_source="ashby", posted_at=today - timedelta(days=10))
    db_session.flush()
    params = {"company": company.slug, "sort": "recent", "limit": 3}
    pages = [client.get("/feed", params={**params, "page": page}) for page in (1, 2, 3)]
    assert [slug for response in pages for slug in _slugs(response)] == [
        row.slug for row in [*rows, old]
    ]
    assert all(response.json()["total"] == 7 for response in pages)


@pytest.mark.parametrize("sort", ["recent", "deadline"])
def test_search_sort_ties_end_with_descending_id(client, db_session, search_sort_rows, sort):
    company, query, rows, _relevance = search_sort_rows
    for row in rows:
        row.posted_at = rows[0].posted_at
        row.deadline = rows[0].deadline
        row.title = rows[0].title
        row.title_normalized = rows[0].title_normalized
    db_session.flush()
    expected = [row.slug for row in sorted(rows, key=lambda row: row.id, reverse=True)]
    params = {"q": query, "company": company.slug, "sort": sort, "limit": 2}
    assert (
        _slugs(client.get("/search", params=params))
        + _slugs(client.get("/search", params={**params, "page": 2}))
        == expected
    )


def test_recent_day_buckets_ignore_database_timezone(client, db_session, listing_factory):
    add, company, _term, now = listing_factory
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    india = timezone(timedelta(hours=5, minutes=30))
    newest = add("utc-newest", posted_at=(midnight + timedelta(minutes=30)).astimezone(india))
    same_day = add("utc-same-day", posted_at=midnight + timedelta(minutes=10))
    previous_day = add(
        "utc-previous-day", primary_source="lever", posted_at=midnight - timedelta(minutes=1)
    )
    db_session.flush()
    db_session.execute(text("SET LOCAL TIME ZONE 'America/Los_Angeles'"))
    assert _slugs(client.get("/feed", params={"company": company.slug, "sort": "recent"})) == [
        newest.slug,
        same_day.slug,
        previous_day.slug,
    ]


def test_deadline_boundary_across_discovery_and_facets(
    client, db_session, listing_factory, monkeypatch
):
    add, company, term, now = listing_factory
    past = add("past", deadline=now - timedelta(seconds=1), posted_at=now)
    future = add("future", deadline=now + timedelta(minutes=1), posted_at=now - timedelta(days=1))
    unknown = add("unknown", posted_at=now - timedelta(days=2))
    detected = add("detected", closed_at=now - timedelta(seconds=1), posted_at=now)
    db_session.flush()
    scope = models.Opportunity.company_id == company.id
    monkeypatch.setattr(
        for_you,
        "exclude_stale_opportunities",
        lambda: exclude_stale_opportunities() & scope,
    )
    for endpoint in ("/feed", "/search"):
        params = {"company": company.slug, "q": term, "sort": "deadline"}
        response = client.get(endpoint, params=params)
        assert _slugs(response) == [future.slug, unknown.slug]
        if endpoint == "/feed":
            assert response.json()["open_total"] == 2
        assert set(_slugs(client.get(endpoint, params={**params, "status": "closed"}))) == {
            past.slug,
            detected.slug,
        }
        assert _slugs(client.get(endpoint, params={**params, "deadline_within": 7})) == [
            future.slug
        ]
        assert (
            _slugs(
                client.get(endpoint, params={**params, "status": "closed", "deadline_within": 7})
            )
            == []
        )
    assert set(_slugs(client.get("/for-you", params={"categories": "competition"}))) == {
        future.slug,
        unknown.slug,
    }
    options = _deadline_within_facets(db_session, [scope])
    assert {option.value: option.count for option in options} == {"1": 1, "3": 1, "7": 1, "30": 1}
    closed = dict(
        db_session.execute(select(models.Opportunity.slug, listing_closed()).where(scope)).all()
    )
    assert closed == {past.slug: True, future.slug: False, unknown.slug: False, detected.slug: True}
    # status=closed is exclusive at the API, so check mixed-state ordering directly.
    for sort in ("recent", "deadline", "prize"):
        slugs = list(
            db_session.scalars(
                select(models.Opportunity.slug)
                .where(scope)
                .order_by(*_search_ordering(sort, func.length(models.Opportunity.title)))
            )
        )
        assert set(slugs[:2]) == {future.slug, unknown.slug}
        assert set(slugs[2:]) == {past.slug, detected.slug}
    is_closed = case((listing_closed(), 1), else_=0)
    assert db_session.scalar(select(func.count()).where(scope, is_closed == 0)) == 2
