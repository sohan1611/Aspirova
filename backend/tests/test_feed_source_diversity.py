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


@pytest.fixture
def source_feed_rows(db_session: Session):
    suffix = uuid.uuid4().hex
    seen_at = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    location_token = f"SourceFilterville-{suffix}"
    company = models.Company(
        slug=f"source-filter-company-{suffix}",
        name=f"Source Filter Company {suffix}",
    )
    source_slugs = [
        "greenhouse",
        "lever",
        "ashby",
        "smartrecruiters",
        "amazon",
        "unstop",
        "remoteok",
        "devpost",
    ]
    opportunities = {
        source_slug: models.Opportunity(
            slug=f"source-filter-{source_slug}-{suffix}",
            title=f"{source_slug} opportunity",
            company=company,
            category="job",
            location=location_token,
            apply_url=f"https://example.com/source-filter/{source_slug}/{suffix}",
            primary_source=source_slug,
            status="active",
            last_seen_at=seen_at,
        )
        for source_slug in source_slugs
    }
    db_session.add_all([company, *opportunities.values()])
    db_session.flush()
    return opportunities, location_token


def test_feed_source_filter_returns_only_requested_source_group(
    client: TestClient,
    source_feed_rows,
) -> None:
    opportunities, location_token = source_feed_rows

    unstop = client.get(
        "/feed",
        params={"source": "unstop", "location": location_token, "limit": 10},
    )
    direct = client.get(
        "/feed",
        params={"source": "direct", "location": location_token, "limit": 10},
    )

    assert unstop.status_code == 200
    unstop_body = unstop.json()
    assert unstop_body["total"] == 1
    assert [item["slug"] for item in unstop_body["items"]] == [opportunities["unstop"].slug]
    assert {item["source"] for item in unstop_body["items"]} == {"unstop"}

    assert direct.status_code == 200
    direct_body = direct.json()
    direct_sources = {
        "greenhouse",
        "lever",
        "ashby",
        "smartrecruiters",
        "amazon",
    }
    assert direct_body["total"] == len(direct_sources)
    assert {item["slug"] for item in direct_body["items"]} == {
        opportunities[source_slug].slug for source_slug in direct_sources
    }
    assert {item["source"] for item in direct_body["items"]} == direct_sources


def test_feed_recent_interleaves_sources_with_stable_pagination(
    client: TestClient,
    db_session: Session,
) -> None:
    suffix = uuid.uuid4().hex
    newest = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)
    location_token = f"SourceDiversityville-{suffix}"
    company = models.Company(
        slug=f"source-diversity-company-{suffix}",
        name=f"Source Diversity Company {suffix}",
    )
    source_offsets = {"greenhouse": 0, "unstop": 10, "remoteok": 20}
    opportunities = []
    for source_slug, source_offset in source_offsets.items():
        for source_rank in range(3):
            opportunities.append(
                models.Opportunity(
                    slug=f"source-diversity-{source_slug}-{source_rank}-{suffix}",
                    title=f"{source_slug} opportunity {source_rank}",
                    company=company,
                    category="job",
                    location=location_token,
                    apply_url=(
                        "https://example.com/source-diversity/"
                        f"{source_slug}/{source_rank}/{suffix}"
                    ),
                    primary_source=source_slug,
                    status="active",
                    last_seen_at=newest - timedelta(minutes=source_offset + source_rank),
                )
            )
    db_session.add_all([company, *opportunities])
    db_session.flush()

    params = {"location": location_token, "sort": "recent", "limit": 3}
    page_1 = client.get("/feed", params={**params, "page": 1})
    page_2 = client.get("/feed", params={**params, "page": 2})
    page_1_repeat = client.get("/feed", params={**params, "page": 1})
    page_2_repeat = client.get("/feed", params={**params, "page": 2})

    assert page_1.status_code == 200
    assert page_2.status_code == 200
    page_1_body = page_1.json()
    page_2_body = page_2.json()
    page_1_repeat_body = page_1_repeat.json()
    page_2_repeat_body = page_2_repeat.json()

    expected_source_round = ["greenhouse", "unstop", "remoteok"]
    assert page_1_body["total"] == 9
    assert page_2_body["total"] == 9
    assert [item["source"] for item in page_1_body["items"]] == expected_source_round
    assert [item["source"] for item in page_2_body["items"]] == expected_source_round

    page_1_slugs = [item["slug"] for item in page_1_body["items"]]
    page_2_slugs = [item["slug"] for item in page_2_body["items"]]
    opportunity_ids = {opportunity.slug: opportunity.id for opportunity in opportunities}
    page_1_ids = {opportunity_ids[slug] for slug in page_1_slugs}
    page_2_ids = {opportunity_ids[slug] for slug in page_2_slugs}
    assert page_1_ids.isdisjoint(page_2_ids)
    assert page_1_slugs == [item["slug"] for item in page_1_repeat_body["items"]]
    assert page_2_slugs == [item["slug"] for item in page_2_repeat_body["items"]]
