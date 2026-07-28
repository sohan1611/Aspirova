"""ASGI middleware for the public read surfaces: per-IP rate limiting, a
tiered-TTL read cache, and latency instrumentation (Doc handoffs/
PHASE-2-HANDOFF.md sec 11 and sec 3/6).

All three are registered in api/main.py BEFORE CORSMiddleware is added -
Starlette makes the LAST-added middleware the outermost one, so that
ordering keeps CORS wrapping everything else. A 429 or a cached response
must still pass through CORS on its way out, or the browser treats it as a
CORS failure and hides the real status/body from the caller entirely.

The cache check happens here, in middleware, rather than in a route
dependency, specifically so a hit never reaches api/deps.get_db - the
"serves without a DB query" acceptance check (sec 11.7) depends on the
cache being resolved before FastAPI's dependency injection (and therefore
the DB session) ever runs. Middleware wraps the whole router, so this holds
regardless of where a dependency would otherwise sit in a route's chain.

TimingMiddleware wraps RateLimit and Cache (added after both, before CORS -
same ordering rule) so X-Total-Time-Ms/X-DB-Time-Ms land on every response,
including a 429 and a cache hit - a cache hit's X-DB-Time-Ms should come
back near zero, which is the empirical proof of the "no DB query" claim
above, not just an assertion of it.
"""

import logging
import time
from collections.abc import Iterable, Iterator

from fastapi.routing import APIRoute
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Match

from core.cache import build_cache_key, cache_get, cache_set
from core.config import get_settings
from core.db_timing import end_request, start_request
from core.ratelimit import check_rate_limit
from core.redis_client import get_redis

logger = logging.getLogger(__name__)

_ROUTE_QUERY_PARAM_CACHE: dict[tuple[str, str], set[str] | None] = {}

# path prefix -> (bucket name, settings attribute holding the per-minute limit)
_IP_RATE_LIMITED_ROUTES: tuple[tuple[str, str, str], ...] = (
    ("/feed", "feed_search", "rate_limit_ip_feed_search_per_minute"),
    ("/for-you", "feed_search", "rate_limit_ip_feed_search_per_minute"),
    ("/search", "feed_search", "rate_limit_ip_feed_search_per_minute"),
    ("/trending", "opportunity", "rate_limit_ip_opportunity_per_minute"),
    ("/opportunity/", "opportunity", "rate_limit_ip_opportunity_per_minute"),
    ("/company/", "opportunity", "rate_limit_ip_opportunity_per_minute"),
    ("/companies", "opportunity", "rate_limit_ip_opportunity_per_minute"),
    ("/facets", "opportunity", "rate_limit_ip_opportunity_per_minute"),
    ("/plans", "opportunity", "rate_limit_ip_opportunity_per_minute"),
    (
        "/sitemap-opportunities",
        "opportunity",
        "rate_limit_ip_opportunity_per_minute",
    ),
    (
        "/sitemap-companies",
        "opportunity",
        "rate_limit_ip_opportunity_per_minute",
    ),
    ("/stats", "opportunity", "rate_limit_ip_opportunity_per_minute"),
)

_CACHEABLE_PREFIXES = (
    "/feed",
    "/for-you",
    "/search",
    "/trending",
    "/opportunity/",
    "/company/",
    "/companies",
    "/facets",
    "/plans",
    "/sitemap-opportunities",
    "/sitemap-companies",
    "/stats",
)

_LONG_CACHE_PREFIXES = (
    "/sitemap-opportunities",
    "/sitemap-companies",
    "/companies",
    "/facets",
    "/plans",
)

_LONG_CACHE_CONTROL = "public, max-age=3600, s-maxage=21600, stale-while-revalidate=86400"
_STATS_CACHE_CONTROL = "public, max-age=300, s-maxage=900, stale-while-revalidate=3600"
_READ_CACHE_CONTROL = "public, max-age=120, s-maxage=900, stale-while-revalidate=3600"


def client_ip(request: Request) -> str:
    """First hop of X-Forwarded-For. Trusted ONLY because Render always
    terminates the public connection and proxies to this process -
    otherwise request.client.host would be Render's proxy for every
    request, collapsing every real visitor into one shared bucket (Doc
    handoffs/PHASE-2-HANDOFF.md sec 11.3)."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _match_rate_limit(path: str) -> tuple[str, str] | None:
    for prefix, bucket, limit_attr in _IP_RATE_LIMITED_ROUTES:
        if path == prefix or path.startswith(prefix):
            return bucket, limit_attr
    return None


def _is_cacheable(path: str) -> bool:
    return any(path == prefix or path.startswith(prefix) for prefix in _CACHEABLE_PREFIXES)


def _declared_query_param_names(route: APIRoute) -> set[str] | None:
    query_params = getattr(getattr(route, "dependant", None), "query_params", None)
    if query_params is None:
        return None

    names: set[str] = set()
    for field in query_params:
        name = getattr(field, "alias", None) or getattr(field, "name", None)
        if not name:
            return None
        names.add(str(name))
    return names


def _iter_api_routes(routes: Iterable[object]) -> Iterator[APIRoute]:
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
            continue

        nested = getattr(route, "routes", None)
        if nested is None:
            original = getattr(route, "original_router", None)
            nested = getattr(original, "routes", None)
        if nested:
            yield from _iter_api_routes(nested)


def _allowed_cache_query_params(request: Request) -> set[str] | None:
    try:
        for route in _iter_api_routes(request.app.routes):
            match, _child_scope = route.matches(request.scope)
            if match != Match.FULL:
                continue

            route_path = getattr(route, "path", None)
            if not isinstance(route_path, str):
                return None

            cache_key = (request.method, route_path)
            if cache_key not in _ROUTE_QUERY_PARAM_CACHE:
                _ROUTE_QUERY_PARAM_CACHE[cache_key] = _declared_query_param_names(route)
            return _ROUTE_QUERY_PARAM_CACHE[cache_key]
    except Exception:
        return None
    return None


def _is_long_cache_path(path: str) -> bool:
    return any(path == prefix or path.startswith(prefix) for prefix in _LONG_CACHE_PREFIXES)


def _cache_ttl_seconds(path: str) -> int:
    settings = get_settings()
    if _is_long_cache_path(path):
        return settings.long_cache_ttl_seconds
    if path == "/stats":
        return settings.stats_cache_ttl_seconds
    return settings.read_cache_ttl_seconds


def _cache_control_header(path: str) -> str:
    if _is_long_cache_path(path):
        return _LONG_CACHE_CONTROL
    if path == "/stats":
        return _STATS_CACHE_CONTROL
    return _READ_CACHE_CONTROL


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-IP limits on the public read routes (sec 11.4). Bookmark writes
    are limited separately, per-user, via a route dependency in
    api/bookmarks.py - that needs the *authenticated* user, which only
    exists after FastAPI's dependency injection has already run, so it
    cannot be enforced at this ASGI layer."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method != "GET":
            return await call_next(request)

        match = _match_rate_limit(request.url.path)
        if match is None:
            return await call_next(request)

        bucket, limit_attr = match
        settings = get_settings()
        max_requests = getattr(settings, limit_attr)

        result = await check_rate_limit(
            get_redis(),
            bucket=bucket,
            identifier=client_ip(request),
            max_requests=max_requests,
            window_seconds=60,
        )
        if not result.allowed:
            return JSONResponse(
                {"detail": "Too many requests"},
                status_code=429,
                headers={"Retry-After": str(result.retry_after_seconds)},
            )
        return await call_next(request)


class ReadCacheMiddleware(BaseHTTPMiddleware):
    """Tiered-TTL cache for public feed/search/opportunity responses (sec 11.1).
    TTL-only for now - see core/cache.py for why version-bump invalidation
    is deferred."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method != "GET" or not _is_cacheable(request.url.path):
            return await call_next(request)

        redis = get_redis()
        allowed_params = _allowed_cache_query_params(request)
        key = build_cache_key(
            request.url.path,
            request.query_params.multi_items(),
            allowed_params,
        )

        cached = await cache_get(redis, key)
        if cached is not None:
            return Response(
                content=cached,
                media_type="application/json",
                headers={
                    "X-Cache": "HIT",
                    "Cache-Control": _cache_control_header(request.url.path),
                },
            )

        response = await call_next(request)
        if response.status_code != 200:
            return response

        body = b"".join([chunk async for chunk in response.body_iterator])
        ttl_seconds = _cache_ttl_seconds(request.url.path)
        await cache_set(redis, key, body.decode(), ttl_seconds)

        headers = {k: v for k, v in response.headers.items() if k.lower() != "content-length"}
        headers["X-Cache"] = "MISS"
        headers["Cache-Control"] = _cache_control_header(request.url.path)
        return Response(
            content=body,
            status_code=response.status_code,
            media_type=response.media_type or "application/json",
            headers=headers,
        )


class TimingMiddleware(BaseHTTPMiddleware):
    """X-Total-Time-Ms / X-DB-Time-Ms on every response (Doc handoffs/
    PHASE-2-HANDOFF.md sec 3/6) - the Lever-2 migration decision needs the
    DB hop isolated from total request time, not conflated with compute or
    the rate-limit/cache checks this wraps."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        token = start_request()
        total_start = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            db_ms = end_request(token)
        total_ms = (time.perf_counter() - total_start) * 1000
        response.headers["X-Total-Time-Ms"] = f"{total_ms:.2f}"
        response.headers["X-DB-Time-Ms"] = f"{db_ms:.2f}"
        return response
