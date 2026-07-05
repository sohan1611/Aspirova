"""Shared FastAPI dependencies: DB session per request.

pool_pre_ping=True matters specifically for this long-lived process (unlike
the short-lived crawler/scripts): a Supabase pooler connection that's gone
stale between requests would otherwise surface as an opaque mid-request
failure - confirmed how real that risk is when a transient connection drop
took down an entire crawl run before the runner.py fix in Step 7.
"""

from collections.abc import Generator

from sqlalchemy.orm import Session, sessionmaker

from core.db import make_engine
from core.db_timing import instrument

_engine = make_engine(pool_pre_ping=True)
instrument(_engine)
SessionLocal = sessionmaker(bind=_engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
