"""Rate limiting via Upstash's atomic fixed-window Lua script (Doc
handoffs/PHASE-2-HANDOFF.md sec 11.4) - never hand-rolled INCR+EXPIRE,
which has a real race: a crash between the two calls can leave a counter
key with no expiry, forever.

Always fails open (sec 11.2): a missing, unreachable, or erroring Redis is
treated as "allow" and logged, never as a 429 or a 500. Availability of the
public read API matters more than the limiter protecting it.
"""

import asyncio
import logging
import time
from dataclasses import dataclass

from upstash_ratelimit.asyncio import FixedWindow, Ratelimit
from upstash_redis.asyncio import Redis

logger = logging.getLogger(__name__)

# Backstop above the client's own timeout (core/redis_client.py) - belt and
# suspenders against any hang inside the SDK we haven't accounted for.
_CALL_TIMEOUT_SECONDS = 1.5


@dataclass
class RateLimitResult:
    allowed: bool
    retry_after_seconds: int = 0


async def check_rate_limit(
    redis: Redis | None,
    *,
    bucket: str,
    identifier: str,
    max_requests: int,
    window_seconds: int,
) -> RateLimitResult:
    if redis is None:
        return RateLimitResult(allowed=True)

    try:
        limiter = Ratelimit(
            redis,
            FixedWindow(max_requests=max_requests, window=window_seconds, unit="s"),
            prefix=f"aspirova:rl:{bucket}",
        )
        result = await asyncio.wait_for(limiter.limit(identifier), timeout=_CALL_TIMEOUT_SECONDS)
        retry_after = max(0, round(result.reset - time.time())) if not result.allowed else 0
        return RateLimitResult(allowed=result.allowed, retry_after_seconds=retry_after)
    except Exception:
        logger.warning(
            "rate limit check failed for bucket=%s - failing open", bucket, exc_info=True
        )
        return RateLimitResult(allowed=True)
