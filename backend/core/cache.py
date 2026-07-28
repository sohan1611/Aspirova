"""Read-cache for the public GET surfaces (Doc handoffs/PHASE-2-HANDOFF.md
sec 11.1/11.5). TTL-only for Part 2.1: the crawler-driven cache-version
bump described in sec 11.1 is deferred, per that section's own explicit
allowance, until Upstash credentials are wired into the crawler's GitHub
Actions environment (a separate manual prerequisite - none exist yet). The
route-specific TTLs in api.middleware stay inside the daily crawl cadence,
so correctness never depends on the deferred piece landing later.

Fails open on every path (sec 11.2): a cache miss - including "Redis is
down" - always falls through to the real query; it never turns into a 500.
"""

import asyncio
import logging

from upstash_redis.asyncio import Redis

logger = logging.getLogger(__name__)

_CALL_TIMEOUT_SECONDS = 1.5


def build_cache_key(path: str, query_items: list[tuple[str, str]]) -> str:
    sorted_qs = "&".join(f"{k}={v}" for k, v in sorted(query_items))
    return f"aspirova:cache:{path}?{sorted_qs}"


async def cache_get(redis: Redis | None, key: str) -> str | None:
    if redis is None:
        return None
    try:
        return await asyncio.wait_for(redis.get(key), timeout=_CALL_TIMEOUT_SECONDS)
    except Exception:
        logger.warning("cache read failed for key=%s - treating as miss", key, exc_info=True)
        return None


async def cache_set(redis: Redis | None, key: str, value: str, ttl_seconds: int) -> None:
    if redis is None:
        return
    try:
        await asyncio.wait_for(redis.set(key, value, ex=ttl_seconds), timeout=_CALL_TIMEOUT_SECONDS)
    except Exception:
        logger.warning("cache write failed for key=%s - ignored", key, exc_info=True)
