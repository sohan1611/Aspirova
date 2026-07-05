"""Tests for Part 2.3 - latency instrumentation (Doc handoffs/
PHASE-2-HANDOFF.md sec 3/6). X-Total-Time-Ms/X-DB-Time-Ms must appear on
every response, and a cache hit must report X-DB-Time-Ms near zero - the
empirical proof that Part 2.1's "cache hit skips the DB" claim is actually
true on a live response, not just true by code inspection.
"""

from api import middleware
from api.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


class FakeAsyncRedis:
    """Same minimal double as test_rate_limit_and_cache.py - duplicated
    rather than shared, matching this codebase's convention of no shared
    conftest.py across test files."""

    def __init__(self) -> None:
        self._counters: dict[str, int] = {}
        self._store: dict[str, str] = {}

    async def eval(self, script, keys, args):
        key = keys[0]
        increment_by = int(args[1])
        self._counters[key] = self._counters.get(key, 0) + increment_by
        return self._counters[key]

    async def get(self, key):
        return self._store.get(key)

    async def set(self, key, value, ex=None, **kwargs):
        self._store[key] = value


def test_timing_headers_present_on_a_normal_response() -> None:
    response = client.get("/feed", params={"limit": 1})
    assert response.status_code == 200
    assert float(response.headers["X-Total-Time-Ms"]) >= 0
    assert float(response.headers["X-DB-Time-Ms"]) >= 0


def test_timing_headers_present_on_a_429(monkeypatch) -> None:
    fake = FakeAsyncRedis()
    monkeypatch.setattr(middleware, "get_redis", lambda: fake)
    from core.config import get_settings

    monkeypatch.setattr(get_settings(), "rate_limit_ip_feed_search_per_minute", 1)

    headers = {"X-Forwarded-For": "203.0.113.99"}
    client.get("/feed", params={"limit": 1}, headers=headers)
    throttled = client.get("/feed", params={"limit": 1}, headers=headers)

    assert throttled.status_code == 429
    assert "X-Total-Time-Ms" in throttled.headers
    assert "X-DB-Time-Ms" in throttled.headers


def test_db_time_is_near_zero_on_cache_hit_but_positive_on_cache_miss(monkeypatch) -> None:
    fake = FakeAsyncRedis()
    monkeypatch.setattr(middleware, "get_redis", lambda: fake)

    headers = {"X-Forwarded-For": "203.0.113.98"}
    miss = client.get("/feed", params={"limit": 1}, headers=headers)
    assert miss.headers["X-Cache"] == "MISS"
    miss_db_ms = float(miss.headers["X-DB-Time-Ms"])

    hit = client.get("/feed", params={"limit": 1}, headers=headers)
    assert hit.headers["X-Cache"] == "HIT"
    hit_db_ms = float(hit.headers["X-DB-Time-Ms"])

    assert hit_db_ms == 0.0
    assert miss_db_ms > hit_db_ms
