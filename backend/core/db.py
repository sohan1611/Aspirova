"""Shared engine factory. Every Postgres connection in this codebase goes
through here so connection-robustness settings live in exactly one place.

Three independent mechanisms, because they bound different failure modes
(each verified by directly testing it, not assumed):

- connect_timeout: bounds the initial TCP handshake. Verified locally
  against a deliberately unreachable address: fails in exactly the
  configured time, not the OS default (which can be minutes).
- keepalives: detects a connection that goes silently dead AFTER it was
  successfully established - packets vanish without either side sending a
  TCP reset (common behind NAT/stateful firewalls on cloud CI networks).
  Without this, a query can hang forever waiting for a response that will
  never arrive, because neither endpoint knows the connection is dead.
- statement_timeout: a server-side cap on any single query. Set via an
  explicit `SET` after connecting, NOT via the `options` connection
  startup parameter - verified that approach silently does nothing here,
  almost certainly because the Supabase pooler (PgBouncer) does not
  forward arbitrary startup options through to the backend. `SET` is a
  normal query over an established connection, which the Session pooler
  (chosen specifically for full session semantics) passes through fine.

This combination exists because connect_timeout alone was NOT sufficient:
a GitHub Actions run hung for ~4-5 minutes before its first failure twice
in a row, with connect_timeout=10 already in place - meaning the hang was
happening after a successful connection, not during the handshake. Per-
source isolation (Doc 04 sec 7) cannot hold if one stuck operation can
consume the entire time budget regardless of which layer it stalls in.

With Supabase Pro's higher session-pooler client limit, the persistent Render
server uses the correct session-mode pooler and the cap is relaxed from 5+5 to
10+10 for healthier concurrency. Pre-ping still self-heals stale connections
before checkout, while recycling prevents dead connections from lingering; the
prior free-tier-exhaustion cap is historical.
"""

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool

from core.config import get_settings

CONNECT_TIMEOUT_SECONDS = 10
STATEMENT_TIMEOUT_MS = 20_000

POOL_SIZE = 10
MAX_OVERFLOW = 10
POOL_RECYCLE_SECONDS = 300

DEFAULT_CONNECT_ARGS = {
    "connect_timeout": CONNECT_TIMEOUT_SECONDS,
    "keepalives": 1,
    "keepalives_idle": 5,
    "keepalives_interval": 5,
    "keepalives_count": 3,
}


def make_engine(**kwargs) -> Engine:
    settings = get_settings()
    transaction_mode = settings.db_pool_mode.strip().lower() == "transaction"
    connect_args = {**DEFAULT_CONNECT_ARGS, **kwargs.pop("connect_args", {})}

    if transaction_mode:
        # Supabase's transaction-mode pooler (:6543) hands the server
        # connection back after EACH transaction, so two things the
        # session-mode setup relied on no longer hold:
        #  1) server-side prepared statements can't be reused across the
        #     rotating server backends -> disable them (psycopg
        #     prepare_threshold=None), or every query risks
        #     "prepared statement does not exist".
        #  2) a connect-time `SET statement_timeout` would not survive past
        #     its own transaction -> pass it as a startup option so the cap is
        #     established on the backend itself, for every transaction.
        connect_args.setdefault("prepare_threshold", None)

    pool_kwargs: dict = {}
    if transaction_mode:
        # Let the external pooler own connection pooling; SQLAlchemy must not
        # keep its own long-lived connections stacked on top of it.
        pool_kwargs["poolclass"] = NullPool
    else:
        pool_kwargs.update(
            pool_pre_ping=True,
            pool_size=POOL_SIZE,
            max_overflow=MAX_OVERFLOW,
            pool_recycle=POOL_RECYCLE_SECONDS,
        )

    if "poolclass" in kwargs:
        pool_kwargs.pop("pool_size", None)
        pool_kwargs.pop("max_overflow", None)
        pool_kwargs.pop("pool_recycle", None)
    pool_kwargs.update(kwargs)
    engine = create_engine(settings.database_url, connect_args=connect_args, **pool_kwargs)

    if not transaction_mode:
        # Session mode: `SET` over the established connection is honored and
        # persists for the session (verified live; the `options` startup param
        # is NOT forwarded by the session pooler - see module docstring).
        @event.listens_for(engine, "connect")
        def _set_statement_timeout(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute(f"SET statement_timeout = {STATEMENT_TIMEOUT_MS}")
            cursor.close()
    else:
        # Transaction mode: the pooler returns the server backend to the pool
        # after every transaction, so neither a connect-time `SET` nor the
        # `options` startup param sticks (both verified ineffective against the
        # :6543 pooler - it reports the 2min default). `SET LOCAL` at the start
        # of each transaction applies the cap for exactly that transaction,
        # which is the whole lifetime of one pooled server backend here.
        @event.listens_for(engine, "begin")
        def _set_local_statement_timeout(connection) -> None:
            connection.exec_driver_sql(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}")

    return engine
