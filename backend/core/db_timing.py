"""Per-request DB-hop timing (Doc handoffs/PHASE-2-HANDOFF.md sec 3/6 -
X-DB-Time-Ms). This is the Lever-2 input: it isolates time spent actually
waiting on Postgres from total request time (compute, rate-limit/cache
checks), which the earlier end-to-end p95 measurement (Doc handoffs/
PHASE-1-REPORT.md sec 6) could not do.

Attributed per-request via a ContextVar, not a global counter: FastAPI
runs each sync route handler in its own threadpool thread, so concurrent
requests execute genuinely in parallel, and SQLAlchemy's engine events
fire globally across every connection on that engine - a shared global
counter would mix different requests' query time together. anyio's
threadpool propagates the current context into the worker thread, so a
ContextVar set by the outer async middleware (api/middleware.py) is still
visible from the synchronous engine-event callbacks running inside it.

Per-cursor start times live on the DBAPI connection's own `.info` dict -
SQLAlchemy's documented scratch space for exactly this profiling pattern -
rather than a plain variable, and a `handle_error` listener discards any
orphaned start time on a failed execute; without that, a query that raises
mid-execution never fires `after_cursor_execute` to pop its start time,
and since connections are pooled and reused, that stale timestamp would
otherwise get incorrectly paired with a later, unrelated query on a
future, unrelated request.
"""

import time
from contextvars import ContextVar, Token

from sqlalchemy import event
from sqlalchemy.engine import Engine

_db_time_ms: ContextVar[list[float] | None] = ContextVar("db_time_ms", default=None)


def instrument(engine: Engine) -> None:
    @event.listens_for(engine, "before_cursor_execute")
    def _before(conn, cursor, statement, parameters, context, executemany) -> None:
        conn.info.setdefault("query_start_times", []).append(time.perf_counter())

    @event.listens_for(engine, "after_cursor_execute")
    def _after(conn, cursor, statement, parameters, context, executemany) -> None:
        start_times = conn.info.get("query_start_times")
        if not start_times:
            return
        elapsed_ms = (time.perf_counter() - start_times.pop()) * 1000
        accumulator = _db_time_ms.get()
        if accumulator is not None:
            accumulator[0] += elapsed_ms

    @event.listens_for(engine, "handle_error")
    def _handle_error(exception_context) -> None:
        conn = exception_context.connection
        if conn is None:
            return
        start_times = conn.info.get("query_start_times")
        if start_times:
            start_times.pop()


def start_request() -> Token:
    """Call once, at the top of a request. Returns a token for end_request."""
    return _db_time_ms.set([0.0])


def end_request(token: Token) -> float:
    """Call once, at the end of the same request. Always resets the
    ContextVar, even if nothing was accumulated."""
    accumulator = _db_time_ms.get()
    total_ms = accumulator[0] if accumulator is not None else 0.0
    _db_time_ms.reset(token)
    return total_ms
