"""Shared engine factory. Every Postgres connection in this codebase goes
through here so the connect timeout lives in exactly one place.

Without an explicit connect_timeout, a stalled TCP handshake falls back to
the OS default, which can be minutes long. Confirmed live: a GitHub Actions
run hung ~5 minutes on the first connection attempt, then hung again on the
next company, until the 15-minute job timeout killed the whole run - zero
companies got a chance to even fail fast, let alone succeed. Per-source
isolation (Doc 04 sec 7) cannot hold if one stuck connection attempt can
consume the entire time budget.
"""

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from core.config import get_settings

CONNECT_TIMEOUT_SECONDS = 10


def make_engine(**kwargs) -> Engine:
    connect_args = {"connect_timeout": CONNECT_TIMEOUT_SECONDS, **kwargs.pop("connect_args", {})}
    return create_engine(get_settings().database_url, connect_args=connect_args, **kwargs)
