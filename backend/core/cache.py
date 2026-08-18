"""Read-cache for the public GET surfaces (Doc handoffs/PHASE-2-HANDOFF.md
sec 11.1/11.5). TTL-only for Part 2.1: the crawler-driven cache-version
bump described in sec 11.1 is deferred, per that section's own explicit
allowance, until Upstash credentials are wired into the crawler's GitHub
Actions environment (a separate manual prerequisite - none exist yet). The
route-specific TTLs in api.middleware stay inside the daily crawl cadence,
so correctness never depends on the deferred piece landing later.

Fails open on every path (sec 11.2): a cache miss - including "Redis is
down" - always falls through to the real query; it never turns into a 500.

TWO TIERS. L1 is an in-process TTL map; L2 is Upstash. L1 exists for the
same reason core/ratelimit.py defaults to an in-process window: render.yaml
declares ONE Render web service with no autoscaling (numInstances: 1), so a
process-local entry has the same visibility as a shared Redis one while
costing no Upstash command at all.

That distinction stopped being academic on 2026-08-18, when the Upstash free
tier hit its ceiling and every single cache call - read AND write - began
raising `UpstashError: max requests limit exceeded. Limit: 500000, Usage:
500000`. Because both paths fail open, nothing 500'd and no alarm fired; the
cache simply degraded to a no-op and every public request fell through to
Postgres (measured live: three identical /feed calls, all `x-cache: MISS`,
each paying ~537ms of DB time). A quota cap on a best-effort dependency had
quietly become a full-traffic load increase on the database and on Supabase
egress, which is the binding cost constraint for this project.

L1 removes that single point of failure from the hot path: it serves hits
with no network call, so the cache keeps working whether or not Upstash is
reachable, in quota, or configured at all. L2 is still written and read
(best-effort) so a process restart can warm from it and so a future
multi-instance deployment keeps a shared tier.

L1 is bounded by BOTH entry size and total bytes - the sitemap response is
~1.7MB, so an unbounded map would be a memory leak on a 512MB instance.
"""

import asyncio
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass
from threading import Lock

from upstash_redis.asyncio import Redis

from core.config import get_settings

logger = logging.getLogger(__name__)

_CALL_TIMEOUT_SECONDS = 1.5


@dataclass
class _L1Entry:
    value: str
    expires_at: float
    size_bytes: int


_L1: OrderedDict[str, _L1Entry] = OrderedDict()
_L1_BYTES = 0
_L1_LOCK = Lock()


def _now() -> float:
    """Clock seam for deterministic TTL tests."""
    return time.time()


def reset_l1_cache() -> None:
    """Drop every L1 entry. Used by tests; never called on the request path."""
    global _L1_BYTES

    with _L1_LOCK:
        _L1.clear()
        _L1_BYTES = 0


def l1_stats() -> tuple[int, int]:
    """Return (entry_count, total_bytes) for observability and tests."""
    with _L1_LOCK:
        return len(_L1), _L1_BYTES


def _l1_drop_locked(key: str) -> None:
    """Remove one entry and its byte accounting. Caller holds _L1_LOCK."""
    global _L1_BYTES

    entry = _L1.pop(key, None)
    if entry is not None:
        _L1_BYTES -= entry.size_bytes


def l1_get(key: str) -> str | None:
    """Return a live L1 value, or None when absent or expired."""
    with _L1_LOCK:
        entry = _L1.get(key)
        if entry is None:
            return None
        if entry.expires_at <= _now():
            _l1_drop_locked(key)
            return None
        # Touch for LRU: most recently used goes last.
        _L1.move_to_end(key)
        return entry.value


def l1_set(key: str, value: str, ttl_seconds: int) -> None:
    """Store a value in L1, evicting least-recently-used entries as needed.

    Oversized single responses are skipped rather than evicting the entire
    cache to hold one giant body.
    """
    global _L1_BYTES

    if ttl_seconds <= 0:
        return

    settings = get_settings()
    if not settings.l1_cache_enabled:
        return

    size_bytes = len(value.encode())
    if size_bytes > settings.l1_cache_max_entry_bytes:
        return

    max_total = settings.l1_cache_max_bytes
    expires_at = _now() + ttl_seconds

    with _L1_LOCK:
        _l1_drop_locked(key)
        _L1[key] = _L1Entry(value=value, expires_at=expires_at, size_bytes=size_bytes)
        _L1_BYTES += size_bytes

        # Evict LRU-first until back inside the byte budget. The just-added
        # key is newest, so it is evicted last - and only if it alone
        # exceeds the budget, which the entry-size guard above prevents.
        while _L1_BYTES > max_total and _L1:
            oldest_key = next(iter(_L1))
            _l1_drop_locked(oldest_key)


def build_cache_key(
    path: str,
    query_items: list[tuple[str, str]],
    allowed_params: set[str] | None = None,
) -> str:
    if allowed_params is not None:
        query_items = [(k, v) for k, v in query_items if k in allowed_params]
    sorted_qs = "&".join(f"{k}={v}" for k, v in sorted(query_items))
    return f"aspirova:cache:{path}?{sorted_qs}"


async def cache_get(
    redis: Redis | None,
    key: str,
    l1_ttl_seconds: int | None = None,
) -> str | None:
    """Read through L1 then L2.

    ``l1_ttl_seconds`` opts a caller into the in-process tier; when it is
    None only L2 is consulted, which keeps callers that do not want a
    process-local copy (see pipeline/copilot.py) on their previous
    behaviour.
    """
    if l1_ttl_seconds is not None:
        hit = l1_get(key)
        if hit is not None:
            return hit

    if redis is None:
        return None

    try:
        value = await asyncio.wait_for(redis.get(key), timeout=_CALL_TIMEOUT_SECONDS)
    except Exception:
        logger.warning("cache read failed for key=%s - treating as miss", key, exc_info=True)
        return None

    # Warm L1 from L2 so a restarted process stops paying for L2 immediately.
    if value is not None and l1_ttl_seconds is not None:
        l1_set(key, value, l1_ttl_seconds)
    return value


async def cache_set(
    redis: Redis | None,
    key: str,
    value: str,
    ttl_seconds: int,
    *,
    write_l1: bool = False,
) -> None:
    """Write to L1 (when opted in) and best-effort to L2.

    L1 is written FIRST and unconditionally, so an unreachable or
    out-of-quota Upstash cannot stop the cache from working.
    """
    if write_l1:
        l1_set(key, value, ttl_seconds)

    if redis is None:
        return
    try:
        await asyncio.wait_for(redis.set(key, value, ex=ttl_seconds), timeout=_CALL_TIMEOUT_SECONDS)
    except Exception:
        logger.warning("cache write failed for key=%s - ignored", key, exc_info=True)
