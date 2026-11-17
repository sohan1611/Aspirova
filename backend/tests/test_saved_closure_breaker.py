"""Offline checks of the closure-relative breaker; no database or transport."""

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from sqlalchemy.dialects import postgresql

from core.config import get_settings
from pipeline.saved_listing_notifications import ClosureNoticeBreaker, load_closure_notice_breaker


@pytest.fixture(scope="session", autouse=True)
def _purge_isolation_test_residue():
    """Override global DB cleanup so this module stays entirely offline."""
    yield


def test_windows_include_both_boundaries_and_hold_only_above_threshold():
    closed_at = datetime(2026, 11, 10, 12, tzinfo=timezone.utc)
    buckets = [
        (closed_at - timedelta(hours=25), 10000),
        (closed_at - timedelta(hours=24), 750),
        (closed_at, 1),
        (closed_at + timedelta(hours=24), 750),
        (closed_at + timedelta(hours=25), 10000),
    ]
    assert ClosureNoticeBreaker(buckets, 1500).holds(closed_at)
    assert not ClosureNoticeBreaker(buckets, 1501).holds(closed_at)


def test_non_hour_candidate_sums_only_buckets_inside_its_window():
    closed_at = datetime(2026, 11, 10, 12, 30, tzinfo=timezone.utc)
    hour = closed_at.replace(minute=0)
    buckets = [
        (hour - timedelta(hours=24), 1600),
        (hour, 1),
        (hour + timedelta(hours=24), 1),
    ]
    assert not ClosureNoticeBreaker(buckets, 1500).holds(closed_at)


def test_held_summary_logs_once_with_count_and_largest_window(caplog):
    closed_at = datetime(2026, 11, 10, 12, tzinfo=timezone.utc)
    breaker = ClosureNoticeBreaker([(closed_at, 1600), (closed_at + timedelta(hours=2), 20)], 1500)
    assert breaker.holds(closed_at)
    assert breaker.holds(closed_at + timedelta(hours=24))
    assert not breaker.holds(closed_at - timedelta(days=3))
    breaker.log_held()
    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1
    assert "held 2 candidates" in warnings[0]
    assert "largest window count 1620" in warnings[0]
    caplog.clear()
    ClosureNoticeBreaker([], 1500).log_held()
    assert not caplog.records


def test_bucket_loader_uses_one_query_for_eight_days_and_early_closures(monkeypatch):
    now = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
    session = Mock()
    session.execute.return_value.all.return_value = [(now - timedelta(hours=30), 1600)]
    monkeypatch.setattr(get_settings(), "saved_closure_notice_breaker", 1500)
    breaker = load_closure_notice_breaker(session, now)
    session.execute.assert_called_once()
    query = session.execute.call_args.args[0].compile(dialect=postgresql.dialect())
    sql = str(query)
    assert "date_trunc" in sql and "GROUP BY" in sql
    assert now - timedelta(days=8) in query.params.values()
    assert now in query.params.values()
    assert "withdrawn" in query.params.values()
    assert "opportunities.deadline IS NULL" in sql
    assert "opportunities.closed_at < opportunities.deadline" in sql
    assert breaker.holds(now - timedelta(hours=30))
    assert not breaker.holds(now - timedelta(hours=102))
