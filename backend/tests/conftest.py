"""Shared fixtures across the whole test suite (Doc handoffs/
PHASE-2-HANDOFF.md sec 2/5, Part 2.8). ONE session-scoped engine (and
therefore one connection pool) for the entire pytest run, not one per
test file.

Before this, every DB-touching test file called make_engine() in its own
db_session fixture, so a full-suite run opened as many separate
QueuePools as there were such files (7, as of Part 2.7). That is the
carried-forward flake from Doc handoffs/PHASE-1-HANDOFF.md, confirmed live
during Part 2.7's own full-suite run: "max clients reached in session
mode - max clients are limited to pool_size: 15" against the free
Supabase pooler. Test files now depend on this shared `engine` fixture
instead of calling make_engine() themselves.
"""

import pytest

from core.db import make_engine


@pytest.fixture(scope="session")
def engine():
    eng = make_engine()
    yield eng
    eng.dispose()
