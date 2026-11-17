"""Offline cache replacement checks with real ASGI middleware and fake Redis."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import middleware
from core import cache
from core.config import Settings


class FakeRedis:
    def __init__(self):
        self.store = {}
        self.calls = []

    async def get(self, key):
        self.calls.append("GET")
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.calls.append("SET")
        self.store[key] = value


@pytest.fixture(autouse=True)
def isolated_cache(monkeypatch):
    cache.reset_l1_cache()
    cache.reset_l2_circuit()
    monkeypatch.setattr(middleware, "_ROUTE_QUERY_PARAM_CACHE", {})
    yield
    cache.reset_l1_cache()
    cache.reset_l2_circuit()


def configure(monkeypatch, *, l2_enabled=False):
    settings = Settings(_env_file=None, l1_cache_enabled=True, read_cache_l2_enabled=l2_enabled)
    monkeypatch.setattr(middleware, "get_settings", lambda: settings)
    monkeypatch.setattr(cache, "get_settings", lambda: settings)
    redis = FakeRedis()
    monkeypatch.setattr(
        middleware, "get_redis", lambda: redis if l2_enabled else pytest.fail("L2 disabled")
    )
    return redis


@pytest.mark.parametrize("l2_enabled", [False, True])
def test_detail_refresh_skips_read_and_replaces_both_cache_tiers(monkeypatch, l2_enabled):
    redis = configure(monkeypatch, l2_enabled=l2_enabled)
    app = FastAPI()
    app.add_middleware(middleware.ReadCacheMiddleware)
    state = {"deadline": "2026-12-01", "calls": 0}

    @app.get("/opportunity/{slug}")
    def detail(slug: str):
        state["calls"] += 1
        return {"slug": slug, "deadline": state["deadline"]}

    with TestClient(app) as client:
        assert client.get("/opportunity/role").headers["X-Cache"] == "MISS"
        state["deadline"] = "2026-12-15"
        old = client.get("/opportunity/role")
        assert old.headers["X-Cache"] == "HIT" and old.json()["deadline"] == "2026-12-01"
        refresh = client.get("/opportunity/role", headers={"X-Aspirova-Refresh": "1"})
        assert refresh.headers["X-Cache"] == "MISS"
        assert refresh.json()["deadline"] == "2026-12-15"
        fresh = client.get("/opportunity/role")
        assert fresh.headers["X-Cache"] == "HIT" and fresh.json() == refresh.json()
        assert state["calls"] == 2
        # The refresh issues a write only, with neither an L1 nor an L2 read.
        assert redis.calls == (["GET", "SET", "SET"] if l2_enabled else [])
        if l2_enabled:
            cache.reset_l1_cache()
            from_l2 = client.get("/opportunity/role")
            assert from_l2.headers["X-Cache"] == "HIT" and from_l2.json() == refresh.json()
            assert state["calls"] == 2


@pytest.mark.parametrize(
    "url", ["/feed", "/opportunity/role/similar", "/opportunity/", "/programme/role"]
)
def test_refresh_header_is_ignored_on_other_paths(monkeypatch, url):
    configure(monkeypatch)
    app = FastAPI()
    app.add_middleware(middleware.ReadCacheMiddleware)
    state = {"version": 1}

    @app.get(url)
    def endpoint():
        return {"version": state["version"]}

    with TestClient(app) as client:
        assert client.get(url).headers["X-Cache"] == "MISS"
        state["version"] = 2
        response = client.get(url, headers={"X-Aspirova-Refresh": "1"})
        assert response.headers["X-Cache"] == "HIT" and response.json() == {"version": 1}


@pytest.mark.parametrize("header", ["0", "true", "2"])
def test_detail_refresh_requires_exact_header_value(monkeypatch, header):
    configure(monkeypatch)
    app = FastAPI()
    app.add_middleware(middleware.ReadCacheMiddleware)
    state = {"version": 1}

    @app.get("/opportunity/{slug}")
    def detail(slug: str):
        return {"version": state["version"]}

    with TestClient(app) as client:
        client.get("/opportunity/role")
        state["version"] = 2
        response = client.get("/opportunity/role", headers={"X-Aspirova-Refresh": header})
        assert response.headers["X-Cache"] == "HIT" and response.json() == {"version": 1}
