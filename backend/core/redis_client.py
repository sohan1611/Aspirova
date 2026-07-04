"""Shared Upstash Redis REST client for rate limiting + read caching (Doc
handoffs/PHASE-2-HANDOFF.md sec 11). Returns None when Upstash credentials
are not configured - every caller must treat None as "fail open" (sec
11.2), not as an error.

A short client-side timeout is set on the underlying httpx client because
the SDK's own default is unbounded (`httpx.AsyncClient(timeout=None)` in
upstash_redis/http.py, confirmed at the pinned version) and there is no
public constructor option for one - without this, an unreachable Upstash
endpoint would hang a request indefinitely instead of failing open quickly.
rest_retries=0 for the same reason: the SDK's default retries once after a
3s sleep, which alone would blow past any reasonable request budget before
the fail-open path is ever reached.
"""

from functools import lru_cache

import httpx
from upstash_redis.asyncio import Redis

from core.config import get_settings


@lru_cache
def get_redis() -> Redis | None:
    settings = get_settings()
    if not (settings.upstash_redis_rest_url and settings.upstash_redis_rest_token):
        return None

    redis = Redis(
        url=settings.upstash_redis_rest_url,
        token=settings.upstash_redis_rest_token,
        rest_retries=0,
    )
    redis._http._client = httpx.AsyncClient(timeout=httpx.Timeout(settings.redis_timeout_seconds))
    return redis
