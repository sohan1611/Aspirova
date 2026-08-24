"""Tests for Part 2.1 - rate limiting + read cache (Doc
handoffs/PHASE-2-HANDOFF.md sec 11). Runs against fake Redis doubles, not
real Upstash - no credentials exist yet in this environment (a manual
prerequisite per Doc sec 10), and sec 11.2's whole point is that the API
must behave safely with OR without a real Redis behind it. Each test
monkeypatches api.middleware.get_redis directly (not FastAPI's
dependency_overrides, which does not reach ASGI middleware) and reverts
automatically at teardown.

Distinct X-Forwarded-For values per test avoid bucket collisions. The shared
test fixture clears the process-local limiter between tests, matching pytest's
normal request-isolation expectations.
"""

import asyncio

import pytest
import upstash_ratelimit.limiter as upstash_limiter
from sqlalchemy import event

from api import middleware
from api.deps import _engine
from api.main import app
from core import ratelimit
from core.config import get_settings
from fastapi.testclient import TestClient

client = TestClient(app)


@pytest.fixture(autouse=True)
def freeze_rate_limit_time(monkeypatch) -> None:
    """Keep every request in a test within the same fixed-window bucket."""
    monkeypatch.setattr(upstash_limiter, "now_ms", lambda: 1_750_000_000_000)


@pytest.fixture(autouse=True)
def use_memory_rate_limit_backend(monkeypatch) -> None:
    """Existing endpoint checks exercise the new default backend explicitly."""
    monkeypatch.setattr(get_settings(), "rate_limit_backend", "memory")


class FakeAsyncRedis:
    """Minimal async double covering exactly what our code calls: `eval`
    (upstash_ratelimit's FixedWindow atomic script) and `get`/`set`
    (core/cache.py). Not a general Redis emulator."""

    def __init__(self) -> None:
        self._counters: dict[str, int] = {}
        self._store: dict[str, str] = {}
        self._ttls: dict[str, int | None] = {}
        self.set_calls = 0

    async def eval(self, script, keys, args):
        key = keys[0]
        increment_by = int(args[1])
        self._counters[key] = self._counters.get(key, 0) + increment_by
        return self._counters[key]

    async def get(self, key):
        return self._store.get(key)

    async def set(self, key, value, ex=None, **kwargs):
        self.set_calls += 1
        self._store[key] = value
        self._ttls[key] = ex


def _last_cache_ttl(fake: FakeAsyncRedis) -> int | None:
    assert fake._ttls
    return list(fake._ttls.values())[-1]


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
    assert fake._counters == {}  # rate limiting did not issue Redis writes


def test_rate_limit_fails_open_when_redis_unreachable(monkeypatch) -> None:
    monkeypatch.setattr(middleware, "get_redis", lambda: BrokenAsyncRedis())
    monkeypatch.setattr(get_settings(), "rate_limit_backend", "redis")
    monkeypatch.setattr(get_settings(), "rate_limit_ip_feed_search_per_minute", 1)

    headers = {"X-Forwarded-For": "203.0.113.2"}
    for _ in range(5):
        response = client.get("/feed", params={"limit": 1}, headers=headers)
        assert response.status_code == 200


def test_memory_fixed_window_blocks_then_allows_in_the_next_window(monkeypatch) -> None:
    clock = {"now": 119.0}
    monkeypatch.setattr(ratelimit, "_now", lambda: clock["now"])

    async def check() -> ratelimit.RateLimitResult:
        return await ratelimit.check_rate_limit(
            None,
            bucket="memory-window",
            identifier="203.0.113.200",
            max_requests=2,
            window_seconds=60,
        )

    async def run() -> tuple[ratelimit.RateLimitResult, ...]:
        first = await check()
        second = await check()
        blocked = await check()
        clock["now"] = 120.0
        next_window = await check()
        return first, second, blocked, next_window

    first, second, blocked, next_window = asyncio.run(run())

    assert first.allowed
    assert second.allowed
    assert not blocked.allowed
    assert blocked.retry_after_seconds == 1
    assert next_window.allowed


def test_memory_rate_limit_fails_open_on_an_unexpected_error(monkeypatch) -> None:
    def raise_clock_error() -> float:
        raise RuntimeError("simulated memory limiter error")

    monkeypatch.setattr(ratelimit, "_now", raise_clock_error)

    async def run() -> ratelimit.RateLimitResult:
        return await ratelimit.check_rate_limit(
            None,
            bucket="memory-fail-open",
            identifier="203.0.113.204",
            max_requests=1,
            window_seconds=60,
        )

    assert asyncio.run(run()).allowed


def test_memory_rate_limits_keep_buckets_and_identifiers_independent() -> None:
    async def check(bucket: str, identifier: str) -> ratelimit.RateLimitResult:
        return await ratelimit.check_rate_limit(
            None,
            bucket=bucket,
            identifier=identifier,
            max_requests=1,
            window_seconds=60,
        )

    async def run() -> tuple[ratelimit.RateLimitResult, ...]:
        feed_a_first = await check("feed_search", "203.0.113.201")
        opportunity_a_first = await check("opportunity", "203.0.113.201")
        feed_b_first = await check("feed_search", "203.0.113.202")
        feed_a_second = await check("feed_search", "203.0.113.201")
        opportunity_a_second = await check("opportunity", "203.0.113.201")
        feed_b_second = await check("feed_search", "203.0.113.202")
        return (
            feed_a_first,
            opportunity_a_first,
            feed_b_first,
            feed_a_second,
            opportunity_a_second,
            feed_b_second,
        )

    results = asyncio.run(run())

    assert [result.allowed for result in results] == [True, True, True, False, False, False]


def test_memory_rate_limit_entry_map_stays_within_its_hard_cap(monkeypatch) -> None:
    monkeypatch.setattr(ratelimit, "_MEMORY_MAX_ENTRIES", 3)
    monkeypatch.setattr(ratelimit, "_now", lambda: 119.0)

    async def run() -> list[ratelimit.RateLimitResult]:
        return [
            await ratelimit.check_rate_limit(
                None,
                bucket="memory-cap",
                identifier=f"203.0.113.{identifier}",
                max_requests=1,
                window_seconds=60,
            )
            for identifier in range(20)
        ]

    results = asyncio.run(run())

    assert all(result.allowed for result in results)
    assert ratelimit._memory_rate_limit_entry_count() <= 3
    assert ratelimit._memory_rate_limit_entry_count() == 3


def test_redis_backend_remains_selectable(monkeypatch) -> None:
    fake = FakeAsyncRedis()
    monkeypatch.setattr(get_settings(), "rate_limit_backend", "redis")

    async def run() -> tuple[ratelimit.RateLimitResult, ratelimit.RateLimitResult]:
        first = await ratelimit.check_rate_limit(
            fake,
            bucket="redis-backend",
            identifier="203.0.113.203",
            max_requests=1,
            window_seconds=60,
        )
        second = await ratelimit.check_rate_limit(
            fake,
            bucket="redis-backend",
            identifier="203.0.113.203",
            max_requests=1,
            window_seconds=60,
        )
        return first, second

    first, second = asyncio.run(run())

    assert first.allowed
    assert not second.allowed
    assert fake._counters


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
        assert (
            first.headers["Cache-Control"]
            == "public, max-age=120, s-maxage=900, stale-while-revalidate=3600"
        )
        queries_after_first = query_count["n"]
        assert queries_after_first > 0

        second = client.get("/feed", params={"limit": 3}, headers=headers)
        assert second.status_code == 200
        assert second.headers["X-Cache"] == "HIT"
        assert (
            second.headers["Cache-Control"]
            == "public, max-age=120, s-maxage=900, stale-while-revalidate=3600"
        )
        assert second.json() == first.json()
        assert query_count["n"] == queries_after_first  # no new DB round-trip
    finally:
        event.remove(_engine, "before_cursor_execute", _count)


def test_long_cache_prefix_uses_long_ttl_and_cache_control(monkeypatch) -> None:
    fake = FakeAsyncRedis()
    monkeypatch.setattr(middleware, "get_redis", lambda: fake)

    response = client.get("/facets", headers={"X-Forwarded-For": "203.0.113.40"})

    assert response.status_code == 200
    assert response.headers["X-Cache"] == "MISS"
    assert (
        response.headers["Cache-Control"]
        == "public, max-age=3600, s-maxage=21600, stale-while-revalidate=86400"
    )
    assert _last_cache_ttl(fake) == get_settings().long_cache_ttl_seconds


def test_junk_query_params_collapse_to_declared_route_cache_key(monkeypatch) -> None:
    fake = FakeAsyncRedis()
    monkeypatch.setattr(middleware, "get_redis", lambda: fake)

    headers = {"X-Forwarded-For": "203.0.113.43"}
    first = client.get("/facets", params={"fbclid": "abc"}, headers=headers)
    second = client.get("/facets", headers=headers)
    third = client.get("/facets", params={"utm_source": "z"}, headers=headers)

    assert first.status_code == 200
    assert first.headers["X-Cache"] == "MISS"
    assert second.status_code == 200
    assert second.headers["X-Cache"] == "HIT"
    assert third.status_code == 200
    assert third.headers["X-Cache"] == "HIT"
    assert second.json() == first.json()
    assert third.json() == first.json()
    assert fake.set_calls == 1
    assert len(fake._store) == 1


def test_request_query_param_cache_has_been_removed() -> None:
    assert not hasattr(middleware, "_REQUEST_QUERY_PARAM_CACHE")


def test_declared_feed_query_params_stay_separate_cache_entries(monkeypatch) -> None:
    fake = FakeAsyncRedis()
    monkeypatch.setattr(middleware, "get_redis", lambda: fake)

    headers = {"X-Forwarded-For": "203.0.113.44"}
    limit_20 = client.get("/feed", params={"limit": 20}, headers=headers)
    limit_100 = client.get("/feed", params={"limit": 100}, headers=headers)
    sort_recent = client.get("/feed", params={"sort": "recent"}, headers=headers)
    sort_deadline = client.get("/feed", params={"sort": "deadline"}, headers=headers)

    assert limit_20.status_code == 200
    assert limit_20.headers["X-Cache"] == "MISS"
    assert limit_100.status_code == 200
    assert limit_100.headers["X-Cache"] == "MISS"
    assert sort_recent.status_code == 200
    assert sort_recent.headers["X-Cache"] == "MISS"
    assert sort_deadline.status_code == 200
    assert sort_deadline.headers["X-Cache"] == "MISS"
    assert fake.set_calls == 4
    assert len(fake._store) == 4


def test_repeated_feed_query_params_preserve_distinct_cache_entries(monkeypatch) -> None:
    fake = FakeAsyncRedis()
    monkeypatch.setattr(middleware, "get_redis", lambda: fake)

    headers = {"X-Forwarded-For": "203.0.113.45"}
    one_company = client.get(
        "/feed",
        params=[("company", "A")],
        headers=headers,
    )
    two_companies = client.get(
        "/feed",
        params=[("company", "A"), ("company", "B")],
        headers=headers,
    )

    assert one_company.status_code == 200
    assert one_company.headers["X-Cache"] == "MISS"
    assert two_companies.status_code == 200
    assert two_companies.headers["X-Cache"] == "MISS"
    assert fake.set_calls == 2
    assert len(fake._store) == 2


def test_standard_cacheable_path_uses_read_ttl_and_cache_control(monkeypatch) -> None:
    fake = FakeAsyncRedis()
    monkeypatch.setattr(middleware, "get_redis", lambda: fake)

    response = client.get(
        "/feed",
        params={"limit": 1},
        headers={"X-Forwarded-For": "203.0.113.41"},
    )

    assert response.status_code == 200
    assert response.headers["X-Cache"] == "MISS"
    assert (
        response.headers["Cache-Control"]
        == "public, max-age=120, s-maxage=900, stale-while-revalidate=3600"
    )
    assert _last_cache_ttl(fake) == get_settings().read_cache_ttl_seconds


@pytest.mark.parametrize(
    ("path", "params", "ip"),
    (
        ("/trending", {"limit": 5}, "203.0.113.48"),
        ("/for-you", {"limit": 5}, "203.0.113.49"),
    ),
)
def test_trending_and_for_you_are_cacheable(monkeypatch, path, params, ip) -> None:
    fake = FakeAsyncRedis()
    monkeypatch.setattr(middleware, "get_redis", lambda: fake)

    headers = {"X-Forwarded-For": ip}
    first = client.get(path, params=params, headers=headers)
    second = client.get(path, params=params, headers=headers)

    assert first.status_code == 200
    assert first.headers["X-Cache"] == "MISS"
    assert (
        first.headers["Cache-Control"]
        == "public, max-age=120, s-maxage=900, stale-while-revalidate=3600"
    )
    assert second.status_code == 200
    assert second.headers["X-Cache"] == "HIT"
    assert (
        second.headers["Cache-Control"]
        == "public, max-age=120, s-maxage=900, stale-while-revalidate=3600"
    )
    assert second.json() == first.json()
    assert _last_cache_ttl(fake) == get_settings().read_cache_ttl_seconds
    assert fake.set_calls == 1


def test_for_you_cache_key_ignores_junk_but_keeps_declared_limit(monkeypatch) -> None:
    fake = FakeAsyncRedis()
    monkeypatch.setattr(middleware, "get_redis", lambda: fake)

    headers = {"X-Forwarded-For": "203.0.113.50"}
    first = client.get("/for-you", params={"fbclid": "x"}, headers=headers)
    second = client.get("/for-you", headers=headers)

    assert first.status_code == 200
    assert first.headers["X-Cache"] == "MISS"
    assert second.status_code == 200
    assert second.headers["X-Cache"] == "HIT"
    assert second.json() == first.json()
    assert fake.set_calls == 1
    assert len(fake._store) == 1

    fake._store.clear()
    fake._ttls.clear()
    fake.set_calls = 0

    limit_5 = client.get("/for-you", params={"limit": 5}, headers=headers)
    limit_20 = client.get("/for-you", params={"limit": 20}, headers=headers)

    assert limit_5.status_code == 200
    assert limit_5.headers["X-Cache"] == "MISS"
    assert limit_20.status_code == 200
    assert limit_20.headers["X-Cache"] == "MISS"
    assert fake.set_calls == 2
    assert len(fake._store) == 2


def test_company_detail_path_stays_on_standard_cache_tier(monkeypatch) -> None:
    fake = FakeAsyncRedis()
    monkeypatch.setattr(middleware, "get_redis", lambda: fake)

    companies = client.get("/companies", headers={"X-Forwarded-For": "203.0.113.42"})
    assert companies.status_code == 200
    body = companies.json()
    assert body
    slug = body[0]["slug"]
    fake._store.clear()
    fake._ttls.clear()

    response = client.get(
        f"/company/{slug}",
        params={"limit": 1},
        headers={"X-Forwarded-For": "203.0.113.42"},
    )

    assert response.status_code == 200
    assert response.headers["X-Cache"] == "MISS"
    assert (
        response.headers["Cache-Control"]
        == "public, max-age=120, s-maxage=900, stale-while-revalidate=3600"
    )
    assert _last_cache_ttl(fake) == get_settings().read_cache_ttl_seconds


def test_auth_path_does_not_get_public_cache_control(monkeypatch) -> None:
    fake = FakeAsyncRedis()
    monkeypatch.setattr(middleware, "get_redis", lambda: fake)

    response = client.get("/account/me")

    assert response.status_code in {401, 403}
    assert "Cache-Control" not in response.headers
    assert fake._ttls == {}


def test_cache_fails_open_when_redis_unreachable(monkeypatch) -> None:
    monkeypatch.setattr(middleware, "get_redis", lambda: BrokenAsyncRedis())
    response = client.get(
        "/feed",
        params={"limit": 1},
        headers={"X-Forwarded-For": "203.0.113.30"},
    )
    assert response.status_code == 200


def test_facets_and_stats_are_rate_limited(monkeypatch) -> None:
    fake = FakeAsyncRedis()
    monkeypatch.setattr(middleware, "get_redis", lambda: fake)
    monkeypatch.setattr(get_settings(), "rate_limit_ip_opportunity_per_minute", 1)

    facets_headers = {"X-Forwarded-For": "203.0.113.46"}
    facets_first = client.get("/facets", headers=facets_headers)
    facets_second = client.get("/facets", headers=facets_headers)

    assert facets_first.status_code == 200
    assert facets_second.status_code == 429
    assert int(facets_second.headers["Retry-After"]) >= 0

    stats_headers = {"X-Forwarded-For": "203.0.113.47"}
    stats_first = client.get("/stats", headers=stats_headers)
    stats_second = client.get("/stats", headers=stats_headers)

    assert stats_first.status_code == 200
    assert stats_second.status_code == 429
    assert int(stats_second.headers["Retry-After"]) >= 0


def test_trending_and_for_you_are_rate_limited(monkeypatch) -> None:
    fake = FakeAsyncRedis()
    monkeypatch.setattr(middleware, "get_redis", lambda: fake)
    monkeypatch.setattr(get_settings(), "rate_limit_ip_feed_search_per_minute", 1)
    monkeypatch.setattr(get_settings(), "rate_limit_ip_opportunity_per_minute", 1)

    for_you_headers = {"X-Forwarded-For": "203.0.113.51"}
    for_you_first = client.get(
        "/for-you",
        params={"limit": 1},
        headers=for_you_headers,
    )
    for_you_second = client.get(
        "/for-you",
        params={"limit": 2},
        headers=for_you_headers,
    )

    assert for_you_first.status_code == 200
    assert for_you_second.status_code == 429
    assert int(for_you_second.headers["Retry-After"]) >= 0

    trending_headers = {"X-Forwarded-For": "203.0.113.52"}
    trending_first = client.get(
        "/trending",
        params={"limit": 1},
        headers=trending_headers,
    )
    trending_second = client.get(
        "/trending",
        params={"limit": 2},
        headers=trending_headers,
    )

    assert trending_first.status_code == 200
    assert trending_second.status_code == 429
    assert int(trending_second.headers["Retry-After"]) >= 0


class QuotaExceededAsyncRedis:
    """Reproduces the 2026-08-18 production failure exactly.

    Upstash's free tier hit its ceiling and BOTH get and set began raising
    `UpstashError: max requests limit exceeded`. Because cache.py fails open
    on each path, nothing 500'd - the cache silently became a no-op and every
    request fell through to Postgres.
    """

    def __init__(self) -> None:
        self.get_calls = 0
        self.set_calls = 0

    async def get(self, *args, **kwargs):
        self.get_calls += 1
        raise RuntimeError("ERR max requests limit exceeded. Limit: 500000, Usage: 500000")

    async def set(self, *args, **kwargs):
        self.set_calls += 1
        raise RuntimeError("ERR max requests limit exceeded. Limit: 500000, Usage: 500000")


def test_cache_still_serves_hits_when_upstash_is_out_of_quota(monkeypatch) -> None:
    """The regression test for the real outage: an exhausted Upstash quota
    must NOT silently send every public request to Postgres."""
    broken = QuotaExceededAsyncRedis()
    monkeypatch.setattr(middleware, "get_redis", lambda: broken)

    query_count = {"n": 0}

    def _count(*_args, **_kwargs) -> None:
        query_count["n"] += 1

    event.listen(_engine, "before_cursor_execute", _count)
    try:
        headers = {"X-Forwarded-For": "203.0.113.90"}
        first = client.get("/feed", params={"limit": 3}, headers=headers)
        assert first.status_code == 200
        assert first.headers["X-Cache"] == "MISS"
        queries_after_first = query_count["n"]
        assert queries_after_first > 0

        second = client.get("/feed", params={"limit": 3}, headers=headers)
        assert second.status_code == 200
        # Before L1 this was a MISS and a second full DB round-trip.
        assert second.headers["X-Cache"] == "HIT"
        assert second.json() == first.json()
        assert query_count["n"] == queries_after_first
    finally:
        event.remove(_engine, "before_cursor_execute", _count)


def test_l1_entry_expires_after_its_ttl(monkeypatch) -> None:
    from core import cache as cache_module

    clock = {"now": 1_000.0}
    monkeypatch.setattr(cache_module, "_now", lambda: clock["now"])

    cache_module.l1_set("k1", "value-1", 60)
    assert cache_module.l1_get("k1") == "value-1"

    clock["now"] = 1_059.0
    assert cache_module.l1_get("k1") == "value-1"

    clock["now"] = 1_061.0
    assert cache_module.l1_get("k1") is None
    # The expired entry is dropped, not merely hidden.
    assert cache_module.l1_stats()[0] == 0


def test_l1_evicts_least_recently_used_to_stay_within_its_byte_budget(monkeypatch) -> None:
    from core import cache as cache_module

    # 250 so a third 100-byte entry overflows and forces one eviction;
    # at exactly 300 all three fit and nothing should be evicted.
    monkeypatch.setattr(get_settings(), "l1_cache_max_bytes", 250)
    monkeypatch.setattr(get_settings(), "l1_cache_max_entry_bytes", 200)

    cache_module.l1_set("a", "x" * 100, 60)
    cache_module.l1_set("b", "y" * 100, 60)
    # Touch "a" so "b" becomes the least recently used.
    assert cache_module.l1_get("a") is not None
    cache_module.l1_set("c", "z" * 100, 60)

    assert cache_module.l1_get("a") is not None
    assert cache_module.l1_get("c") is not None
    assert cache_module.l1_get("b") is None

    entries, total_bytes = cache_module.l1_stats()
    assert entries == 2
    assert total_bytes <= 250


def test_l1_skips_a_single_response_larger_than_the_entry_cap(monkeypatch) -> None:
    """A ~1.7MB sitemap must not evict the whole cache to store itself."""
    from core import cache as cache_module

    monkeypatch.setattr(get_settings(), "l1_cache_max_bytes", 10_000)
    monkeypatch.setattr(get_settings(), "l1_cache_max_entry_bytes", 500)

    cache_module.l1_set("small", "s" * 100, 60)
    cache_module.l1_set("huge", "h" * 5_000, 60)

    assert cache_module.l1_get("huge") is None
    assert cache_module.l1_get("small") is not None


def test_l1_can_be_disabled_by_settings(monkeypatch) -> None:
    from core import cache as cache_module

    monkeypatch.setattr(get_settings(), "l1_cache_enabled", False)
    cache_module.l1_set("k", "v", 60)
    assert cache_module.l1_get("k") is None


def test_cache_get_without_l1_ttl_does_not_populate_the_in_process_tier() -> None:
    """pipeline/copilot.py opts out; its answers must not sit in L1."""
    from core import cache as cache_module

    fake = FakeAsyncRedis()

    async def run() -> str | None:
        await cache_module.cache_set(fake, "copilot:k", "answer", 3600)
        return await cache_module.cache_get(fake, "copilot:k")

    assert asyncio.run(run()) == "answer"
    assert cache_module.l1_get("copilot:k") is None


def test_l2_hit_warms_l1_so_a_restarted_process_stops_paying_for_l2() -> None:
    from core import cache as cache_module

    fake = FakeAsyncRedis()

    async def run() -> tuple[str | None, str | None]:
        await cache_module.cache_set(fake, "warm:k", "from-l2", 600)
        cache_module.reset_l1_cache()  # simulate a fresh process with a warm L2
        first = await cache_module.cache_get(fake, "warm:k", l1_ttl_seconds=600)
        return first, cache_module.l1_get("warm:k")

    from_l2, from_l1 = asyncio.run(run())
    assert from_l2 == "from-l2"
    assert from_l1 == "from-l2"


def test_l2_circuit_stops_calling_upstash_after_repeated_failures() -> None:
    """A broken L2 must cost a bounded number of round trips, not one per call.

    Upstash has been answering every command with `max requests limit
    exceeded` since 2026-08-18. Failing open kept the site correct, but the
    uncached path still made two calls per request - a read and a write -
    and both were guaranteed to fail before any real work happened.
    """
    from core import cache as cache_module

    broken = QuotaExceededAsyncRedis()

    async def run() -> None:
        for i in range(10):
            await cache_module.cache_get(broken, f"trip:{i}", l1_ttl_seconds=60)

    asyncio.run(run())

    assert cache_module.l2_circuit_open() is True
    # Threshold is 3: the calls after it are skipped, not attempted.
    assert broken.get_calls == cache_module._L2_FAILURE_THRESHOLD


def test_l2_circuit_skips_writes_too_while_open() -> None:
    """cache_set is the second of the two calls a cached route makes."""
    from core import cache as cache_module

    broken = QuotaExceededAsyncRedis()

    async def run() -> None:
        for i in range(cache_module._L2_FAILURE_THRESHOLD):
            await cache_module.cache_get(broken, f"w:{i}", l1_ttl_seconds=60)
        # Circuit is open now; a write must not reach Upstash.
        await cache_module.cache_set(broken, "w:x", "body", 60, write_l1=True)

    asyncio.run(run())

    assert broken.set_calls == 0
    # Failing open is preserved: L1 was still written.
    assert cache_module.l1_get("w:x") == "body"


def test_l2_circuit_allows_one_probe_per_cooldown_and_closes_on_recovery(
    monkeypatch,
) -> None:
    """After the cooldown exactly one call is let through, and a success closes."""
    from core import cache as cache_module

    clock = {"now": 1_000.0}
    monkeypatch.setattr(cache_module, "_now", lambda: clock["now"])

    broken = QuotaExceededAsyncRedis()
    healthy = FakeAsyncRedis()

    async def trip() -> None:
        for i in range(cache_module._L2_FAILURE_THRESHOLD):
            await cache_module.cache_get(broken, f"p:{i}", l1_ttl_seconds=60)

    asyncio.run(trip())
    calls_when_open = broken.get_calls
    assert cache_module.l2_circuit_open() is True

    # Still inside the cooldown: no further calls.
    clock["now"] += cache_module._L2_COOLDOWN_SECONDS - 1
    asyncio.run(cache_module.cache_get(broken, "p:during", l1_ttl_seconds=60))
    assert broken.get_calls == calls_when_open

    # Cooldown elapsed: one probe is allowed, and it fails, re-opening.
    clock["now"] += 2
    asyncio.run(cache_module.cache_get(broken, "p:probe", l1_ttl_seconds=60))
    assert broken.get_calls == calls_when_open + 1
    assert cache_module.l2_circuit_open() is True

    # A later probe against a recovered L2 closes the circuit.
    clock["now"] += cache_module._L2_COOLDOWN_SECONDS + 1
    asyncio.run(cache_module.cache_set(healthy, "p:ok", "v", 60))
    assert cache_module.l2_circuit_open() is False


def test_l2_circuit_does_not_open_on_scattered_single_failures() -> None:
    """One blip between successes must not disable L2 for five minutes."""
    from core import cache as cache_module

    broken = QuotaExceededAsyncRedis()
    healthy = FakeAsyncRedis()

    async def run() -> None:
        for i in range(6):
            await cache_module.cache_get(broken, f"blip:{i}", l1_ttl_seconds=60)
            await cache_module.cache_set(healthy, f"blip:{i}", "v", 60)

    asyncio.run(run())

    assert cache_module.l2_circuit_open() is False
    assert broken.get_calls == 6


def test_l2_circuit_keeps_a_long_outage_visible_once_per_cooldown(monkeypatch, caplog) -> None:
    """Suppressing per-request spam must not mean logging nothing at all.

    Upstash's quota outage lasted days. A breaker that goes silent after the
    first trip would leave no signal that L2 was still down.
    """
    import logging

    from core import cache as cache_module

    clock = {"now": 5_000.0}
    monkeypatch.setattr(cache_module, "_now", lambda: clock["now"])
    broken = QuotaExceededAsyncRedis()

    async def trip() -> None:
        for i in range(cache_module._L2_FAILURE_THRESHOLD):
            await cache_module.cache_get(broken, f"o:{i}", l1_ttl_seconds=60)

    asyncio.run(trip())

    with caplog.at_level(logging.WARNING, logger="core.cache"):
        for probe in range(3):
            clock["now"] += cache_module._L2_COOLDOWN_SECONDS + 1
            asyncio.run(cache_module.cache_get(broken, f"o:probe{probe}", l1_ttl_seconds=60))

    still_failing = [r for r in caplog.records if "still failing" in r.getMessage()]
    assert len(still_failing) == 3
