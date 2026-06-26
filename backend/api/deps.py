"""Shared FastAPI dependencies: DB session per request.

pool_pre_ping=True matters specifically for this long-lived process (unlike
the short-lived crawler/scripts): a Supabase pooler connection that's gone
stale between requests would otherwise surface as an opaque mid-request
failure - confirmed how real that risk is when a transient connection drop
took down an entire crawl run before the runner.py fix in Step 7.
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from core.config import get_settings

_engine = create_engine(get_settings().database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=_engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
