"""Integration tests for the dream-companies API (Doc 03 sec 4.2) -
per-plan limits enforced entirely through can() (Doc 08 sec 1 hard rule).

Both get_db and get_current_user are overridden with the test's own
rollback-wrapped session/fake user (FastAPI's dependency_overrides), the
same pattern used to avoid a real Supabase session in test_bookmarks_auth.py
while still exercising the real route logic against real data.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import upstash_ratelimit.limiter as upstash_limiter
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from api import dream_companies
from api.auth import get_current_user
from api.deps import get_db
from api.main import app
from core import models
from core.config import get_settings


class FakeAsyncRedis:
    """Minimal async double for Upstash's fixed-window rate limiter."""

    def __init__(self) -> None:
        self._counters: dict[str, int] = {}

    async def eval(self, script, keys, args):
        key = keys[0]
        increment_by = int(args[1])
        self._counters[key] = self._counters.get(key, 0) + increment_by
        return self._counters[key]


@pytest.fixture(autouse=True)
def freeze_rate_limit_time(monkeypatch) -> None:
    """Keep write requests in a test within the same fixed-window bucket."""
    monkeypatch.setattr(upstash_limiter, "now_ms", lambda: 1_750_000_000_000)


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
def seeded(db_session: Session):
    free_plan = db_session.scalar(select(models.Plan).where(models.Plan.key == "free"))
    if free_plan is None:
        free_plan = models.Plan(key="free", price_paise=0, billing=None, features={})
        db_session.add(free_plan)
    free_plan.features = {"dream_companies_limit": 1}
    pro_plan = models.Plan(
        key="pro-dc-test",
        price_paise=4900,
        billing="monthly",
        features={"dream_companies_limit": None},
    )
    user = models.User(email=f"dream-companies-test-{uuid.uuid4()}@example.com")
    company_a = models.Company(slug="dc-test-acme", name="Acme", name_normalized="acme")
    company_b = models.Company(slug="dc-test-globex", name="Globex", name_normalized="globex")
    db_session.add_all([pro_plan, user, company_a, company_b])
    db_session.flush()
    return {
        "free_plan": free_plan,
        "pro_plan": pro_plan,
        "user": user,
        "company_a": company_a,
        "company_b": company_b,
    }


@pytest.fixture
def client(db_session, seeded):
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: seeded["user"]
    app.dependency_overrides[dream_companies.enforce_dream_company_write_limit] = lambda: seeded[
        "user"
    ]
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(dream_companies.enforce_dream_company_write_limit, None)


def test_free_user_can_add_one_dream_company(client, seeded) -> None:
    response = client.post(f"/dream-companies/{seeded['company_a'].slug}")
    assert response.status_code == 204

    listed = client.get("/dream-companies").json()
    assert len(listed) == 1
    assert listed[0]["company"]["slug"] == seeded["company_a"].slug


def test_free_user_is_blocked_at_the_second_dream_company(client, seeded, db_session) -> None:
    client.post(f"/dream-companies/{seeded['company_a'].slug}")

    response = client.post(f"/dream-companies/{seeded['company_b'].slug}")

    assert response.status_code == 403
    listed = client.get("/dream-companies").json()
    assert len(listed) == 1


def test_pro_user_is_not_limited(client, seeded, db_session) -> None:
    db_session.add(
        models.Subscription(
            user_id=seeded["user"].id, plan_id=seeded["pro_plan"].id, status="active"
        )
    )
    db_session.flush()

    r1 = client.post(f"/dream-companies/{seeded['company_a'].slug}")
    r2 = client.post(f"/dream-companies/{seeded['company_b'].slug}")

    assert r1.status_code == 204
    assert r2.status_code == 204
    assert len(client.get("/dream-companies").json()) == 2


def test_adding_the_same_company_twice_is_idempotent_not_a_limit_violation(client, seeded) -> None:
    r1 = client.post(f"/dream-companies/{seeded['company_a'].slug}")
    r2 = client.post(f"/dream-companies/{seeded['company_a'].slug}")

    assert r1.status_code == 204
    assert (
        r2.status_code == 204
    )  # re-adding the same one already at the limit is a no-op, not a 403
    assert len(client.get("/dream-companies").json()) == 1


def test_removing_a_dream_company_frees_up_the_limit(client, seeded) -> None:
    client.post(f"/dream-companies/{seeded['company_a'].slug}")

    remove_response = client.delete(f"/dream-companies/{seeded['company_a'].slug}")
    add_other_response = client.post(f"/dream-companies/{seeded['company_b'].slug}")

    assert remove_response.status_code == 204
    assert add_other_response.status_code == 204
    listed = client.get("/dream-companies").json()
    assert len(listed) == 1
    assert listed[0]["company"]["slug"] == seeded["company_b"].slug


def test_dream_company_write_limit_throttles_post_and_delete(client, seeded, monkeypatch) -> None:
    fake = FakeAsyncRedis()
    app.dependency_overrides.pop(dream_companies.enforce_dream_company_write_limit)
    monkeypatch.setattr(dream_companies, "get_redis", lambda: fake)
    monkeypatch.setattr(get_settings(), "rate_limit_user_dream_company_write_per_minute", 1)

    added = client.post(f"/dream-companies/{seeded['company_a'].slug}")
    throttled = client.delete(f"/dream-companies/{seeded['company_a'].slug}")

    assert added.status_code == 204
    assert throttled.status_code == 429
    assert int(throttled.headers["Retry-After"]) >= 0


def test_unknown_company_slug_returns_404(client) -> None:
    response = client.post("/dream-companies/this-company-does-not-exist-xyz")
    assert response.status_code == 404


def _grant_pro(db_session, seeded):
    db_session.add(
        models.Subscription(
            user_id=seeded["user"].id, plan_id=seeded["pro_plan"].id, status="active"
        )
    )
    db_session.flush()


def test_browser_preflight_allows_put(client):
    # TestClient skips the browser's preflight, so a route can pass every other test
    # here while real browsers block it. This failed in the first real-DOM run.
    origin = get_settings().cors_origins_list[0]

    response = client.options(
        "/dream-companies",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )

    assert response.status_code == 200
    assert "PUT" in response.headers["access-control-allow-methods"]


def test_put_creates_multiple_follows_normalizes_roles_and_is_idempotent(
    client, seeded, db_session
):
    _grant_pro(db_session, seeded)
    payload = {
        "company_slugs": [seeded["company_a"].slug, seeded["company_b"].slug],
        "roles": ["software", "data", "software"],
    }
    assert client.put("/dream-companies", json=payload).status_code == 204
    assert client.put("/dream-companies", json=payload).status_code == 204
    items = client.get("/dream-companies").json()
    assert len(items) == 2
    assert all(item["roles"] == ["data", "software"] for item in items)
    assert {item["company"]["slug"] for item in items} == set(payload["company_slugs"])


def test_put_edit_at_limit_and_post_preserves_roles(client, seeded):
    payload = {"company_slugs": [seeded["company_a"].slug], "roles": ["software"]}
    assert client.put("/dream-companies", json=payload).status_code == 204
    payload["roles"] = ["research", "engineering"]
    assert client.put("/dream-companies", json=payload).status_code == 204
    assert client.post(f"/dream-companies/{seeded['company_a'].slug}").status_code == 204
    assert client.get("/dream-companies").json()[0]["roles"] == ["engineering", "research"]
    payload["roles"] = []
    assert client.put("/dream-companies", json=payload).status_code == 204
    assert client.get("/dream-companies").json()[0]["roles"] == []


@pytest.mark.parametrize("roles", [["invented"], ["software"] * 13])
def test_put_rejects_invalid_roles(client, seeded, roles):
    response = client.put(
        "/dream-companies", json={"company_slugs": [seeded["company_a"].slug], "roles": roles}
    )
    assert response.status_code == 422
    assert client.get("/dream-companies").json() == []


@pytest.mark.parametrize("count", [0, 21])
def test_put_rejects_invalid_company_count(client, count):
    response = client.put(
        "/dream-companies", json={"company_slugs": ["missing"] * count, "roles": []}
    )
    assert response.status_code == 422


def test_put_unknown_slug_does_not_create_or_edit_any_follow(client, seeded, db_session):
    _grant_pro(db_session, seeded)
    client.put(
        "/dream-companies",
        json={"company_slugs": [seeded["company_a"].slug], "roles": ["software"]},
    )
    response = client.put(
        "/dream-companies",
        json={
            "company_slugs": [
                seeded["company_a"].slug,
                seeded["company_b"].slug,
                "missing-company",
            ],
            "roles": ["sales"],
        },
    )
    assert response.status_code == 404
    items = client.get("/dream-companies").json()
    assert len(items) == 1
    assert items[0]["roles"] == ["software"]


def test_put_over_limit_does_not_write(client, seeded):
    response = client.put(
        "/dream-companies",
        json={"company_slugs": [seeded["company_a"].slug, seeded["company_b"].slug], "roles": []},
    )
    assert response.status_code == 403
    assert (
        response.json()["detail"]
        == "Dream company limit reached for your plan (1). Upgrade for more."
    )
    assert client.get("/dream-companies").json() == []
    client.put(
        "/dream-companies",
        json={"company_slugs": [seeded["company_a"].slug], "roles": ["software"]},
    )
    assert (
        client.put(
            "/dream-companies",
            json={
                "company_slugs": [seeded["company_a"].slug, seeded["company_b"].slug],
                "roles": ["sales"],
            },
        ).status_code
        == 403
    )
    assert client.get("/dream-companies").json()[0]["roles"] == ["software"]


def test_get_follows_newest_first(client, seeded, db_session):
    _grant_pro(db_session, seeded)
    now = datetime.now(timezone.utc)
    db_session.add_all(
        [
            models.DreamCompany(
                user_id=seeded["user"].id,
                company_id=seeded["company_a"].id,
                roles=["software"],
                created_at=now - timedelta(days=1),
            ),
            models.DreamCompany(
                user_id=seeded["user"].id,
                company_id=seeded["company_b"].id,
                roles=[],
                created_at=now,
            ),
        ]
    )
    db_session.flush()
    assert [item["company"]["slug"] for item in client.get("/dream-companies").json()] == [
        seeded["company_b"].slug,
        seeded["company_a"].slug,
    ]


def test_put_uses_write_limit_dependency(client, seeded, monkeypatch):
    app.dependency_overrides.pop(dream_companies.enforce_dream_company_write_limit)
    fake = FakeAsyncRedis()
    monkeypatch.setattr(dream_companies, "get_redis", lambda: fake)
    monkeypatch.setattr(get_settings(), "rate_limit_user_dream_company_write_per_minute", 1)
    assert (
        client.put(
            "/dream-companies", json={"company_slugs": [seeded["company_a"].slug], "roles": []}
        ).status_code
        == 204
    )
    response = client.put(
        "/dream-companies", json={"company_slugs": [seeded["company_a"].slug], "roles": []}
    )
    assert response.status_code == 429


def test_company_search_substring_prefix_empty_company_and_query_cache(client, db_session):
    token = uuid.uuid4().hex[:12]
    prefix = models.Company(slug=f"search-prefix-{token}", name=f"{token} Labs")
    substring = models.Company(slug=f"search-substring-{token}", name=f"The {token} Company")
    db_session.add_all([prefix, substring])
    db_session.flush()
    now = datetime.now(timezone.utc)
    db_session.add(
        models.Opportunity(
            slug=f"search-opp-{token}",
            company_id=substring.id,
            title="Software Intern",
            apply_url="https://example.com/apply",
            first_seen_at=now,
            status="active",
        )
    )
    db_session.flush()
    response = client.get("/companies/search", params={"q": f"  {token.upper()}  "})
    assert response.status_code == 200
    assert [item["slug"] for item in response.json()] == [prefix.slug, substring.slug]
    assert [item["active_count"] for item in response.json()] == [0, 1]
    assert "public" in response.headers["Cache-Control"]
    assert (
        len(
            client.get("/companies/search", params={"q": f"  {token.upper()}  ", "limit": 1}).json()
        )
        == 1
    )
    assert client.get("/companies/search", params={"q": token + "missing"}).json() == []
    assert (
        client.get("/companies/search", params={"q": f"  {token.upper()}  "}).headers["X-Cache"]
        == "HIT"
    )


@pytest.mark.parametrize("special", ["%", "_", "\\"])
def test_company_search_escapes_wildcards(client, db_session, special):
    token = uuid.uuid4().hex[:12]
    literal = models.Company(slug=f"search-literal-{token}", name=f"{token}{special} Company")
    wildcard = models.Company(slug=f"search-wildcard-{token}", name=f"{token}x Company")
    db_session.add_all([literal, wildcard])
    db_session.flush()
    items = client.get("/companies/search", params={"q": token + special}).json()
    assert [item["slug"] for item in items] == [literal.slug]


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"q": "x"},
        {"q": " x "},
        {"q": "x" * 81},
        {"q": "xx", "limit": 21},
        {"q": "xx", "limit": 0},
    ],
)
def test_company_search_validates_query(client, params):
    assert client.get("/companies/search", params=params).status_code == 422
