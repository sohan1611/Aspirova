"""Tests for Part 2.1 - rate limiting + read cache (Doc
handoffs/PHASE-2-HANDOFF.md sec 11). Runs against fake Redis doubles, not
real Upstash - no credentials exist yet in this environment (a manual
prerequisite per Doc sec 10), and sec 11.2's whole point is that the API
must behave safely with OR without a real Redis behind it. Each test
monkeypatches api.middleware.get_redis directly (not FastAPI's
dependency_overrides, which does not reach ASGI middleware) and reverts
automatically at teardown.

Distinct X-Forwarded-For values per test avoid bucket collisions with each
other and with test_api.py's unrelated /feed calls (which run with no real
Redis configured and therefore always fail open, per sec 11.2).
"""

import pytest
import upstash_ratelimit.limiter as upstash_limiter
from sqlalchemy import event

from api import middleware
from api.deps import _engine
from api.main import app
from core.config import get_settings
from fastapi.testclient import TestClient

client = TestClient(app)


@pytest.fixture(autouse=True)
def freeze_rate_limit_time(monkeypatch) -> None:
    """Keep every request in a test within the same fixed-window bucket."""
    monkeypatch.setattr(upstash_limiter, "now_ms", lambda: 1_750_000_000_000)


class FakeAsyncRedis:
    """Minimal async double covering exactly what our code calls: `eval`
    (upstash_ratelimit's FixedWindow atomic script) and `get`/`set`
    (core/cache.py). Not a general Redis emulator."""

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


class BrokenAsyncRedis:
    """Simulates an unreachable/erroring Upstash - every call raises."""

    async def eval(self, *args, **kwargs):
        raise ConnectionError("simulated Upstash outage")

    async def get(self, *args, **kwargs):
        raise ConnectionError("simulated Upstash outage")

    async def set(self, *args, **kwargs):
        raise ConnectionError("simulated Upstash outage")


def test_burst_of_requests_is_throttled_with_429_and_retry_after(monkeypatch) -> None:
    fake = FakeAsyncRedis()
    monkeypatch.setattr(middleware, "get_redis", lambda: fake)
    monkeypatch.setattr(get_settings(), "rate_limit_ip_feed_search_per_minute", 2)

    headers = {"X-Forwarded-For": "203.0.113.1"}
    r1 = client.get("/feed", params={"limit": 1}, headers=headers)
    r2 = client.get("/feed", params={"limit": 1}, headers=headers)
    r3 = client.get("/feed", params={"limit": 1}, headers=headers)

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r3.status_code == 429
    assert int(r3.headers["Retry-After"]) >= 0


def test_rate_limit_fails_open_when_redis_unreachable(monkeypatch) -> None:
    monkeypatch.setattr(middleware, "get_redis", lambda: BrokenAsyncRedis())
    monkeypatch.setattr(get_settings(), "rate_limit_ip_feed_search_per_minute", 1)

    headers = {"X-Forwarded-For": "203.0.113.2"}
    for _ in range(5):
        response = client.get("/feed", params={"limit": 1}, headers=headers)
        assert response.status_code == 200


def test_per_ip_keying_does_not_collapse_different_clients(monkeypatch) -> None:
    fake = FakeAsyncRedis()
    monkeypatch.setattr(middleware, "get_redis", lambda: fake)
    monkeypatch.setattr(get_settings(), "rate_limit_ip_feed_search_per_minute", 1)

    headers_a = {"X-Forwarded-For": "203.0.113.10"}
    headers_b = {"X-Forwarded-For": "203.0.113.11"}

    r_a1 = client.get("/feed", params={"limit": 1}, headers=headers_a)
    r_b1 = client.get("/feed", params={"limit": 1}, headers=headers_b)
    # A second request from A should now be throttled (limit=1) - proves A's
    # count actually incremented - while B, a distinct IP, still gets through.
    r_a2 = client.get("/feed", params={"limit": 1}, headers=headers_a)
    r_b2 = client.get("/feed", params={"limit": 1}, headers=headers_b)

    assert r_a1.status_code == 200
    assert r_b1.status_code == 200
    assert r_a2.status_code == 429
    assert r_b2.status_code == 429


def test_repeated_feed_request_is_served_from_cache_without_a_db_query(monkeypatch) -> None:
    fake = FakeAsyncRedis()
    monkeypatch.setattr(middleware, "get_redis", lambda: fake)

    query_count = {"n": 0}

    def _count(*_args, **_kwargs) -> None:
        query_count["n"] += 1

    event.listen(_engine, "before_cursor_execute", _count)
    try:
        headers = {"X-Forwarded-For": "203.0.113.20"}
        first = client.get("/feed", params={"limit": 3}, headers=headers)
        assert first.status_code == 200
        assert first.headers["X-Cache"] == "MISS"
        queries_after_first = query_count["n"]
        assert queries_after_first > 0

        second = client.get("/feed", params={"limit": 3}, headers=headers)
        assert second.status_code == 200
        assert second.headers["X-Cache"] == "HIT"
        assert second.json() == first.json()
        assert query_count["n"] == queries_after_first  # no new DB round-trip
    finally:
        event.remove(_engine, "before_cursor_execute", _count)


def test_cache_fails_open_when_redis_unreachable(monkeypatch) -> None:
    monkeypatch.setattr(middleware, "get_redis", lambda: BrokenAsyncRedis())
    response = client.get("/feed", params={"limit": 1}, headers={"X-Forwarded-For": "203.0.113.30"})
    assert response.status_code == 200
