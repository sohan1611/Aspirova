"""Crawl source staleness alarm (scripts/report_crawl_staleness.py).

This script gates the whole Tier-1 crawl: with --fail-on-stale it exits 1, the
workflow goes red, and the founder gets a "crawl failed" email. It had no tests,
and it spent three days emailing failures while every source was working.

The bug: staleness counted only status='success'. A 'partial' run - real
listings returned, then http_429 part-way through pagination - did not refresh
the clock, so two consecutive rate-limited runs looked identical to a dead
source. arbeitnow alternates success/partial depending on whether it dodges the
429, so the false alarm fired at random.

These tests run against a real database (there is no separate test instance) and
the query reads ALL enabled sources, so every assertion here is scoped to a
source this module inserted, looked up by its unique adapter_key. Asserting on
global counts would just be reporting on production.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from core import models
from scripts.report_crawl_staleness import (
    STALE_AFTER_HOURS,
    _load_staleness,
    print_staleness_summary,
)

NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def db_session(engine):
    """Transactional and rolled back - these tests write sources and crawl_runs
    to a real database, so nothing may persist."""
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    try:
        yield session, connection
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def source_factory(db_session):
    session, _ = db_session

    def _make(*, enabled: bool = True, runs: list[tuple[str, float]] = ()) -> str:
        """Create a source with crawl_runs given as (status, hours_ago)."""
        adapter_key = f"stale-test-{uuid.uuid4().hex[:12]}"
        source = models.Source(
            slug=adapter_key,
            name="Staleness fixture",
            type="aggregator",
            adapter_key=adapter_key,
            enabled=enabled,
        )
        session.add(source)
        session.flush()

        for status, hours_ago in runs:
            finished = NOW - timedelta(hours=hours_ago)
            session.add(
                models.CrawlRun(
                    source_id=source.id,
                    tier=1,
                    started_at=finished - timedelta(minutes=5),
                    finished_at=finished,
                    status=status,
                    listings_found=49,
                    errors=0,
                )
            )
        session.flush()
        return adapter_key

    return _make


def _lookup(db_session, adapter_key: str):
    _, connection = db_session
    for source in _load_staleness(NOW, conn=connection):
        if source.adapter_key == adapter_key:
            return source
    raise AssertionError(f"{adapter_key} missing from staleness report")


# ------------------------------------------------------- the regression itself


def test_recent_partial_runs_are_not_stale(db_session, source_factory):
    """THE bug. Two consecutive rate-limited-but-productive runs and nothing
    else - exactly arbeitnow on 2026-08-28 and 08-29, which turned a working
    crawl red and emailed the founder that it had failed."""
    key = source_factory(runs=[("partial", 6.0), ("partial", 30.0)])

    source = _lookup(db_session, key)

    assert source.stale is False, "a partial run returned listings; that is contact"
    assert source.age_hours == pytest.approx(6.0, abs=0.01)


def test_partial_refreshes_the_clock_even_when_an_older_success_is_stale(
    db_session, source_factory
):
    """The success is beyond the threshold and only the partial saves it, so
    this fails if 'partial' is ever dropped from the predicate again."""
    key = source_factory(
        runs=[("success", STALE_AFTER_HOURS + 40), ("partial", 3.0)],
    )

    assert _lookup(db_session, key).stale is False


# ------------------------------------------------------- still catches outages


def test_source_with_no_runs_at_all_is_stale(db_session, source_factory):
    """The hackerearth case: 4.7 days with no contact of any kind. Widening the
    predicate must not blind the alarm to a genuinely dead source."""
    key = source_factory(runs=[])

    source = _lookup(db_session, key)

    assert source.stale is True
    assert source.age_hours is None
    assert source.last_contact is None


def test_contact_older_than_the_threshold_is_stale(db_session, source_factory):
    key = source_factory(runs=[("partial", STALE_AFTER_HOURS + 1)])

    assert _lookup(db_session, key).stale is True


def test_failed_runs_alone_do_not_count_as_contact(db_session, source_factory):
    """A source answering only with failures is down. 'failed' must stay
    excluded - otherwise the alarm can never fire for a broken adapter."""
    key = source_factory(runs=[("failed", 1.0), ("failed", 2.0)])

    assert _lookup(db_session, key).stale is True


@pytest.mark.parametrize("status", ["success", "partial"])
def test_both_productive_statuses_count(db_session, source_factory, status):
    key = source_factory(runs=[(status, 1.0)])

    assert _lookup(db_session, key).stale is False


# ------------------------------------------------------- scope of the alarm


def test_disabled_sources_are_excluded_entirely(db_session, source_factory):
    """hackerearth was disabled rather than fixed. A disabled source must drop
    out of the report completely, not merely stop being stale - otherwise
    turning a dead source off would not clear the alarm."""
    key = source_factory(enabled=False, runs=[])

    _, connection = db_session
    reported = {source.adapter_key for source in _load_staleness(NOW, conn=connection)}

    assert key not in reported


def test_boundary_is_exclusive_at_exactly_the_threshold(db_session, source_factory):
    """`> STALE_AFTER_HOURS`, so landing exactly on 48h is still OK. Pinned so a
    later refactor cannot quietly flip this to >= and start alarming a day early."""
    key = source_factory(runs=[("success", STALE_AFTER_HOURS)])

    assert _lookup(db_session, key).stale is False


# ------------------------------------------------------- exit-code contract


def test_summary_returns_the_stale_count_that_drives_exit_1(db_session, source_factory):
    """print_staleness_summary's return value is what --fail-on-stale turns into
    SystemExit(1), so the count has to track the fresh source appearing."""
    _, connection = db_session

    key = source_factory(runs=[])
    with_dead = print_staleness_summary(NOW, conn=connection)

    session, _ = db_session
    source = session.query(models.Source).filter_by(adapter_key=key).one()
    session.add(
        models.CrawlRun(
            source_id=source.id,
            tier=1,
            started_at=NOW - timedelta(hours=1),
            finished_at=NOW - timedelta(hours=1),
            status="partial",
            listings_found=49,
            errors=0,
        )
    )
    session.flush()

    assert print_staleness_summary(NOW, conn=connection) == with_dead - 1


def test_summary_prints_last_contact_not_last_success(db_session, source_factory, capsys):
    """The field was renamed with the semantics. A log line still saying
    `last_success=` next to a partial-run timestamp is how this bug hid."""
    source_factory(runs=[("partial", 2.0)])
    _, connection = db_session

    print_staleness_summary(NOW, conn=connection)
    out = capsys.readouterr().out

    assert "last_contact=" in out
    assert "last_success=" not in out
