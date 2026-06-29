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
"""

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine

from core.config import get_settings

CONNECT_TIMEOUT_SECONDS = 10
STATEMENT_TIMEOUT_MS = 20_000

DEFAULT_CONNECT_ARGS = {
    "connect_timeout": CONNECT_TIMEOUT_SECONDS,
    "keepalives": 1,
    "keepalives_idle": 5,
    "keepalives_interval": 5,
    "keepalives_count": 3,
}


def make_engine(**kwargs) -> Engine:
    connect_args = {**DEFAULT_CONNECT_ARGS, **kwargs.pop("connect_args", {})}
    engine = create_engine(get_settings().database_url, connect_args=connect_args, **kwargs)

    @event.listens_for(engine, "connect")
    def _set_statement_timeout(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute(f"SET statement_timeout = {STATEMENT_TIMEOUT_MS}")
        cursor.close()

    return engine
