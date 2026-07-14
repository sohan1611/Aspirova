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
from sqlalchemy import text

from core.db import make_engine


@pytest.fixture(scope="session")
def engine():
    eng = make_engine()
    yield eng
    eng.dispose()


# Children before parents - every FK into opportunities/companies/sources here
# is ON DELETE NO ACTION (except opportunity_view_counts, CASCADE), so residue
# must be removed in dependency order. opportunity_sources.raw_listing_id ->
# raw_listings means opportunity_sources must precede raw_listings.
_ISOLATION_RESIDUE_DELETES = (
    "delete from opportunity_tags where opportunity_id in ("
    " select o.id from opportunities o join companies c on c.id = o.company_id"
    " where c.slug like 'test-isolation-co-%')",
    "delete from opportunity_sources where opportunity_id in ("
    " select o.id from opportunities o join companies c on c.id = o.company_id"
    " where c.slug like 'test-isolation-co-%')"
    " or source_id in (select id from sources where slug like 'test-isolation-%')",
    "delete from notifications where opportunity_id in ("
    " select o.id from opportunities o join companies c on c.id = o.company_id"
    " where c.slug like 'test-isolation-co-%')",
    "delete from opportunity_view_counts where opportunity_id in ("
    " select o.id from opportunities o join companies c on c.id = o.company_id"
    " where c.slug like 'test-isolation-co-%')",
    "delete from raw_listings where source_id in ("
    " select id from sources where slug like 'test-isolation-%')",
    "delete from crawl_runs where source_id in ("
    " select id from sources where slug like 'test-isolation-%')",
    "delete from source_state where source_id in ("
    " select id from sources where slug like 'test-isolation-%')",
    "delete from opportunities where company_id in ("
    " select id from companies where slug like 'test-isolation-co-%')",
    "delete from companies where slug like 'test-isolation-co-%'",
    "delete from sources where slug like 'test-isolation-%'",
)


def _purge_isolation_residue(engine) -> None:
    try:
        with engine.begin() as conn:
            for stmt in _ISOLATION_RESIDUE_DELETES:
                conn.execute(text(stmt))
    except Exception as exc:  # best-effort: never block the suite on cleanup
        print(f"WARNING: isolation-residue purge skipped: {exc}")


@pytest.fixture(scope="session", autouse=True)
def _purge_isolation_test_residue(engine):
    """The runner-isolation fixture (tests/test_runner_isolation.py) COMMITS
    synthetic 'test-isolation-*' sources/companies + 'Fake Job' opportunities
    to the shared DB - it has to, because crawl_company_board opens its own
    sessions and would not see uncommitted fixture rows. Its per-test `finally`
    cleanup is skipped whenever a run is hard-killed (CI cancel-in-progress,
    crash, timeout), leaking those fake active opportunities into the LIVE feed
    (confirmed live: 27 'Fake Job' rows across 8 orphaned companies). Purging at
    session start bounds the blast radius to at most one interrupted run's
    residue instead of letting it accumulate for days; the teardown purge keeps
    a normal run clean even if a fixture finally is bypassed."""
    _purge_isolation_residue(engine)
    yield
    _purge_isolation_residue(engine)
