"""Bounded fixed-window rate limiting for the current single-instance API.

``render.yaml`` declares one Render Starter web service with no autoscaling,
so a process-local fixed window has the same per-(bucket, identifier) behavior
as a shared Redis window while avoiding an Upstash write for every request.
The in-process backend is therefore the default. The Redis implementation is
retained for a future multi-instance deployment: set ``RATE_LIMIT_BACKEND`` to
``redis`` to use Upstash's atomic fixed-window Lua script instead.

The read cache remains Redis-backed and is intentionally unrelated to this
choice. Every limiter backend fails open: an unexpected limiter error is
logged and allows the request rather than producing a 429 or 500.
"""

import asyncio
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass
from threading import Lock

from upstash_ratelimit.asyncio import FixedWindow, Ratelimit
from upstash_redis.asyncio import Redis

from core.config import get_settings

logger = logging.getLogger(__name__)

# Backstop above the client's own timeout (core/redis_client.py) - belt and
# suspenders against any hang inside the SDK we haven't accounted for.
_CALL_TIMEOUT_SECONDS = 1.5

# The identifier is normally a client IP, so it is attacker-controlled. Keep a
# hard ceiling on process memory even if an attacker continually changes it.
_MEMORY_MAX_ENTRIES = 50_000
_MEMORY_PRUNE_EVERY = 256


@dataclass
class RateLimitResult:
    allowed: bool
    retry_after_seconds: int = 0


@dataclass
class _MemoryRateLimitEntry:
    count: int
    window_end: float


_MEMORY_ENTRIES: OrderedDict[tuple[str, str], _MemoryRateLimitEntry] = OrderedDict()
_MEMORY_EXPIRIES: dict[float, set[tuple[str, str]]] = {}
_MEMORY_LOCK = Lock()
_memory_checks = 0
_memory_next_expiry: float | None = None


def _now() -> float:
    """Clock seam for deterministic fixed-window tests."""
    return time.time()


def _window_end(now: float, window_seconds: int) -> float:
    """Return the end of the epoch-aligned fixed window containing ``now``."""
    return (now // window_seconds + 1) * window_seconds


def _drop_memory_entry(key: tuple[str, str]) -> _MemoryRateLimitEntry | None:
    """Remove one entry from both the LRU map and its expiry index.

    Called only while ``_MEMORY_LOCK`` is held.
    """
    global _memory_next_expiry

    entry = _MEMORY_ENTRIES.pop(key, None)
    if entry is None:
        return None

    expiry_keys = _MEMORY_EXPIRIES.get(entry.window_end)
    if expiry_keys is not None:
        expiry_keys.discard(key)
        if not expiry_keys:
            del _MEMORY_EXPIRIES[entry.window_end]
            if _memory_next_expiry == entry.window_end:
                _memory_next_expiry = min(_MEMORY_EXPIRIES, default=None)
    return entry


def _store_memory_entry(key: tuple[str, str], entry: _MemoryRateLimitEntry) -> None:
    """Store a new entry and index it by expiry. Lock must already be held."""
    global _memory_next_expiry

    _MEMORY_ENTRIES[key] = entry
    _MEMORY_ENTRIES.move_to_end(key)
    _MEMORY_EXPIRIES.setdefault(entry.window_end, set()).add(key)
    if _memory_next_expiry is None or entry.window_end < _memory_next_expiry:
        _memory_next_expiry = entry.window_end


def _prune_expired_memory_entries(now: float) -> None:
    """Remove expired windows without scanning live LRU entries every check.

    The expiry index makes the common case an O(1) comparison. A full cleanup
    is only needed after a window has actually expired or on the cheap periodic
    cadence below.
    """
    global _memory_next_expiry

    if _memory_next_expiry is None or _memory_next_expiry > now:
        return

    expired_windows = [window_end for window_end in _MEMORY_EXPIRIES if window_end <= now]
    for window_end in expired_windows:
        keys = _MEMORY_EXPIRIES.pop(window_end)
        for key in keys:
            entry = _MEMORY_ENTRIES.get(key)
            if entry is not None and entry.window_end == window_end:
                del _MEMORY_ENTRIES[key]
    _memory_next_expiry = min(_MEMORY_EXPIRIES, default=None)


def _make_space_for_memory_entry(now: float) -> None:
    """Prune first, then evict least-recently-used entries at the hard cap."""
    if _MEMORY_MAX_ENTRIES < 1:
        raise ValueError("_MEMORY_MAX_ENTRIES must be positive")

    if len(_MEMORY_ENTRIES) < _MEMORY_MAX_ENTRIES:
        return

    _prune_expired_memory_entries(now)
    while len(_MEMORY_ENTRIES) >= _MEMORY_MAX_ENTRIES:
        oldest_key = next(iter(_MEMORY_ENTRIES))
        _drop_memory_entry(oldest_key)


def _check_memory_rate_limit(
    *,
    bucket: str,
    identifier: str,
    max_requests: int,
    window_seconds: int,
) -> RateLimitResult:
    """Check the bounded, epoch-aligned in-process fixed window."""
    global _memory_checks

    now = _now()
    window_end = _window_end(now, window_seconds)
    key = (bucket, identifier)

    # This tiny critical section contains no awaits. A thread lock therefore
    # safely protects state across async requests without blocking on I/O.
    with _MEMORY_LOCK:
        _memory_checks += 1
        if _memory_checks % _MEMORY_PRUNE_EVERY == 0:
            _prune_expired_memory_entries(now)

        entry = _MEMORY_ENTRIES.get(key)
        if entry is not None and entry.window_end != window_end:
            _drop_memory_entry(key)
            entry = None

        if entry is None:
            _make_space_for_memory_entry(now)
            entry = _MemoryRateLimitEntry(count=0, window_end=window_end)
            _store_memory_entry(key, entry)
        else:
            _MEMORY_ENTRIES.move_to_end(key)

        # Upstash's FixedWindow increments before deciding whether the request
        # is allowed. Preserve that observable fixed-window behavior here.
        entry.count += 1
        if entry.count <= max_requests:
            return RateLimitResult(allowed=True)
        return RateLimitResult(
            allowed=False,
            retry_after_seconds=max(0, round(window_end - now)),
        )


def _reset_memory_rate_limit_state() -> None:
    """Clear process state for isolated tests."""
    global _memory_checks, _memory_next_expiry

    with _MEMORY_LOCK:
        _MEMORY_ENTRIES.clear()
        _MEMORY_EXPIRIES.clear()
        _memory_checks = 0
        _memory_next_expiry = None


def _memory_rate_limit_entry_count() -> int:
    """Return the current entry count for bounded-state tests."""
    with _MEMORY_LOCK:
        return len(_MEMORY_ENTRIES)


async def _check_redis_rate_limit(
    redis: Redis | None,
    *,
    bucket: str,
    identifier: str,
    max_requests: int,
    window_seconds: int,
) -> RateLimitResult:
    """The existing Upstash fixed-window path for multi-instance deployments."""
    if redis is None:
        return RateLimitResult(allowed=True)

    limiter = Ratelimit(
        redis,
        FixedWindow(max_requests=max_requests, window=window_seconds, unit="s"),
        prefix=f"aspirova:rl:{bucket}",
    )
    result = await asyncio.wait_for(limiter.limit(identifier), timeout=_CALL_TIMEOUT_SECONDS)
    retry_after = max(0, round(result.reset - time.time())) if not result.allowed else 0
    return RateLimitResult(allowed=result.allowed, retry_after_seconds=retry_after)


async def check_rate_limit(
    redis: Redis | None,
    *,
    bucket: str,
    identifier: str,
    max_requests: int,
    window_seconds: int,
) -> RateLimitResult:
    try:
        backend = get_settings().rate_limit_backend
        if backend == "memory":
            return _check_memory_rate_limit(
                bucket=bucket,
                identifier=identifier,
                max_requests=max_requests,
                window_seconds=window_seconds,
            )
        if backend == "redis":
            return await _check_redis_rate_limit(
                redis,
                bucket=bucket,
                identifier=identifier,
                max_requests=max_requests,
                window_seconds=window_seconds,
            )
        raise ValueError(f"unsupported rate-limit backend: {backend}")
    except Exception:
        logger.warning(
            "rate limit check failed for bucket=%s - failing open", bucket, exc_info=True
        )
        return RateLimitResult(allowed=True)
