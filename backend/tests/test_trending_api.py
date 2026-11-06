import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from api import middleware, trending
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
    posted_at: datetime | None = None,
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
        posted_at=posted_at,
        deadline=deadline,
        meta=meta,
        last_seen_at=datetime.now(UTC),
    )


@pytest.fixture
def landing_trending_rows(db_session, monkeypatch):
    suffix = uuid.uuid4().hex
    rows = []
    names = [
        "blank",
        "favicon",
        "other-first",
        "other-second",
        "prestige",
        "other-third",
        "forbes",
        "other-fourth",
        "both",
        "independent",
        "famous-last",
    ]
    for index, name in enumerate(names):
        company = models.Company(
            slug=f"logo-trending-company-{name}-{suffix}",
            name=name,
            domain=f"{suffix}.example" if name == "favicon" else None,
            logo_url=(
                f"https://example.com/{name}.png" if name not in {"blank", "favicon"} else None
            ),
            prestige_rank=index if name in {"blank", "prestige", "both", "famous-last"} else None,
            global_rank=1 if name in {"favicon", "forbes", "both"} else None,
        )
        row = _opportunity(suffix, f"logo-{name}", company)
        row.title = "Software Intern"
        if name == "independent":
            row.company = None
        db_session.add(row)
        db_session.flush()
        db_session.add(models.OpportunityViewCount(opportunity_id=row.id, views=10_000 - index))
        rows.append(row)
    db_session.flush()
    monkeypatch.setattr(
        trending,
        "exclude_stale_opportunities",
        lambda: models.Opportunity.id.in_([row.id for row in rows]),
    )
    return rows


@pytest.mark.parametrize(
    "limit,expected",
    [
        (1, [4]),
        (5, [4, 2, 6, 3, 8]),
        (6, [4, 2, 6, 3, 8, 5]),
        (12, [4, 2, 6, 3, 8, 5, 10, 7]),
    ],
)
def test_landing_widgets_require_logos_and_interleave_famous(
    client, landing_trending_rows, limit, expected
):
    rows = landing_trending_rows
    original = client.get("/trending", params={"limit": 12})
    preferred = client.get("/trending", params={"limit": limit, "prefer_logos": "true"})
    assert original.status_code == preferred.status_code == 200
    assert [item["slug"] for item in original.json()["items"]] == [row.slug for row in rows]
    assert [item["slug"] for item in preferred.json()["items"]] == [
        rows[index].slug for index in expected
    ]
    assert all(item["company"]["logo_url"] is not None for item in preferred.json()["items"])


@pytest.mark.parametrize("has_famous", [False, True])
def test_landing_widgets_use_all_famous_when_fewer_than_half(
    client, db_session, landing_trending_rows, has_famous
):
    rows = landing_trending_rows
    for index in ([6, 8, 10] if has_famous else [4, 6, 8, 10]):
        rows[index].company.prestige_rank = None
        rows[index].company.global_rank = None
    db_session.flush()
    response = client.get("/trending", params={"limit": 8, "prefer_logos": "true"})
    assert response.status_code == 200
    expected = [4, 2, 3, 5, 6, 7, 8, 10] if has_famous else [2, 3, 4, 5, 6, 7, 8, 10]
    assert [item["slug"] for item in response.json()["items"]] == [
        rows[index].slug for index in expected
    ]


def test_landing_widgets_return_fewer_when_only_one_logo(client, db_session, landing_trending_rows):
    rows = landing_trending_rows
    for index, row in enumerate(rows):
        if row.company is not None and index != 4:
            row.company.logo_url = None
    db_session.flush()
    response = client.get("/trending", params={"limit": 8, "prefer_logos": "true"})
    assert response.status_code == 200
    assert [item["slug"] for item in response.json()["items"]] == [rows[4].slug]


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


def test_trending_excludes_senior_title_with_enough_views(
    client: TestClient,
    db_session: Session,
) -> None:
    suffix = uuid.uuid4().hex
    company = models.Company(
        slug=f"trending-early-career-company-{suffix}",
        name=f"Trending Early Career Company {suffix}",
    )
    senior = _opportunity(suffix, "senior", company)
    senior.title = "Senior Software Engineer"
    senior.title_normalized = "senior software engineer"
    non_senior = _opportunity(suffix, "non-senior", company)
    non_senior.title = "Software Engineer"
    non_senior.title_normalized = "software engineer"
    db_session.add_all([company, senior, non_senior])
    db_session.flush()
    db_session.add_all(
        [
            models.OpportunityViewCount(opportunity_id=senior.id, views=10_000),
            models.OpportunityViewCount(opportunity_id=non_senior.id, views=10_000),
        ]
    )
    db_session.flush()

    response = client.get("/trending", params={"limit": 24})

    assert response.status_code == 200
    slugs = {item["slug"] for item in response.json()["items"]}
    assert senior.slug not in slugs
    assert non_senior.slug in slugs


def test_opportunity_view_endpoint_returns_404_for_unknown_slug(
    client: TestClient,
) -> None:
    response = client.post(f"/opportunities/unknown-trending-{uuid.uuid4().hex}/view")

    assert response.status_code == 404


def test_trending_excludes_stale_inactive_and_closed_opportunities(
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
    stale = _opportunity(
        suffix,
        "stale",
        company,
        posted_at=now - timedelta(days=STALE_AFTER_DAYS + 1),
    )
    unknown_posted_at = _opportunity(suffix, "null-posted-at", company, posted_at=None)
    closed_competition = _opportunity(
        suffix,
        "closed-competition",
        company,
        category="competition",
        deadline=now - timedelta(days=15),
        meta={"offers_ppi": True},
    )
    db_session.add_all([company, visible, inactive, stale, unknown_posted_at, closed_competition])
    db_session.flush()
    db_session.add_all(
        [
            models.OpportunityViewCount(opportunity_id=visible.id, views=20_000),
            models.OpportunityViewCount(opportunity_id=inactive.id, views=30_000),
            models.OpportunityViewCount(opportunity_id=stale.id, views=40_000),
            models.OpportunityViewCount(opportunity_id=unknown_posted_at.id, views=20_001),
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
    assert unknown_posted_at.slug in slugs
    assert inactive.slug not in slugs
    assert stale.slug not in slugs
    assert closed_competition.slug not in slugs


def test_opportunity_actions_increment_and_separate_actions_and_days(
    client, db_session, monkeypatch
) -> None:
    suffix = uuid.uuid4().hex
    company = models.Company(slug=f"action-company-{suffix}", name="Action Company")
    opportunity = _opportunity(suffix, "actions", company)
    db_session.add(opportunity)
    db_session.flush()
    first_day = datetime(2026, 11, 3, 23, 59, tzinfo=UTC)

    class Clock:
        current = first_day

        @classmethod
        def now(cls, tz):
            assert tz is UTC
            return cls.current

    monkeypatch.setattr(trending, "datetime", Clock)
    path = f"/opportunities/{opportunity.slug}/actions"
    assert client.post(f"{path}/apply").json() == {"ok": True}
    assert client.post(f"{path}/apply").status_code == 200
    assert client.post(f"{path}/gate").status_code == 200
    Clock.current = first_day + timedelta(minutes=2)
    assert client.post(f"{path}/apply").status_code == 200

    rows = db_session.scalars(
        select(models.OpportunityActionCount).where(
            models.OpportunityActionCount.opportunity_id == opportunity.id
        )
    ).all()
    assert {(row.day, row.action): row.count for row in rows} == {
        (first_day.date(), "apply"): 2,
        (first_day.date(), "gate"): 1,
        (Clock.current.date(), "apply"): 1,
    }


def test_opportunity_actions_unknown_slug_returns_404(client) -> None:
    response = client.post(f"/opportunities/missing-{uuid.uuid4().hex}/actions/apply")
    assert response.status_code == 404


def test_opportunity_actions_invalid_action_returns_422(client) -> None:
    response = client.post("/opportunities/anything/actions/share")
    assert response.status_code == 422


@pytest.mark.parametrize("failure_at", ["scalar", "execute", "commit"])
def test_opportunity_actions_survive_database_error(failure_at) -> None:
    from unittest.mock import Mock

    from sqlalchemy.exc import SQLAlchemyError

    db = Mock(spec=Session)
    db.scalar.return_value = 1
    getattr(db, failure_at).side_effect = SQLAlchemyError("counter unavailable")
    assert trending.record_opportunity_action("example", "apply", db) == {"ok": True}
    db.rollback.assert_called_once()


def test_opportunity_actions_have_view_rate_limit_dependency() -> None:
    route = next(
        route
        for route in trending.router.routes
        if route.path == "/opportunities/{slug}/actions/{action}"
    )
    assert trending.enforce_view_rate_limit in [item.dependency for item in route.dependencies]
