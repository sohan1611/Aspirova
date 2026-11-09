"""Reopen fixtures for the architect's disposable PostgreSQL run; no HTTP."""

from datetime import date, datetime, timedelta, timezone

import pytest

from pipeline.liveness import _select_candidates
from pipeline.retirement import ROLLING_WINDOW_TTL_DAYS
from scripts import reopen_rolling_ttl as reopen
from tests.test_audit_retirement import _opportunity
from tests.test_audit_retirement import board as board
from tests.test_audit_retirement import db_session as db_session


@pytest.mark.parametrize("apply", [False, True])
def test_reopen_is_date_source_age_and_reason_scoped(db_session, board, apply):
    _, company, _ = board
    closed_on = date(2026, 11, 9)
    start = datetime(2026, 11, 9, tzinfo=timezone.utc)
    keep = {"nested": True}
    rows = []
    for source, days, closed_at, reason, status in [
        ("himalayas", 40, start, "rolling_window_ttl", "active"),
        ("himalayas", 70, start, None, "active"),
        ("himalayas", 40, start - timedelta(microseconds=1), None, "active"),
        ("himalayas", 40, start + timedelta(days=1), None, "active"),
        ("remoteok", 40, start, None, "active"),
        ("himalayas", 40, start, "dead_board", "active"),
        ("himalayas", 40, start, None, "expired"),
        ("himalayas", 40, start + timedelta(hours=23), None, "active"),
    ]:
        row = _opportunity(db_session, company, source, days=days)
        row.closed_at = closed_at
        row.status = status
        row.category = "internship"
        row.meta = {"keep": keep, "liveness_checked_at": start.isoformat()}
        if reason:
            row.meta = row.meta | {"closed_reason": reason}
        rows.append(row)
    db_session.flush()
    before = [(row.closed_at, row.last_seen_at, row.status, row.meta) for row in rows]
    result = reopen.reopen_rolling_ttl(db_session, closed_on=closed_on, apply=apply)
    assert result.candidates == 2
    assert result.categories == {"internship": 2}
    assert result.min_last_seen_at == min(rows[0].last_seen_at, rows[7].last_seen_at)
    assert result.max_last_seen_at == max(rows[0].last_seen_at, rows[7].last_seen_at)
    assert result.excluded == {
        "different source": 1,
        "closed_reason=dead_board": 1,
        "status is not active": 1,
        f"last_seen_at outside {ROLLING_WINDOW_TTL_DAYS['himalayas']}-day TTL": 1,
    }
    assert result.reopened == (2 if apply else 0)
    db_session.expire_all()
    for index, row in enumerate(rows):
        closed_at, seen_at, status, meta = before[index]
        assert row.last_seen_at == seen_at and row.status == status
        if apply and index in {0, 7}:
            assert row.closed_at is None
            assert row.meta == {key: value for key, value in meta.items() if key != "closed_reason"}
        else:
            assert row.closed_at == closed_at and row.meta == meta
    if apply:
        assert reopen.reopen_rolling_ttl(db_session, closed_on=closed_on, apply=True).reopened == 0


def test_liveness_skips_himalayas_without_a_closure_marker(db_session, board):
    row = _opportunity(db_session, board[1], "himalayas", days=40)
    row.deadline = None
    db_session.flush()
    assert row.id not in {candidate.id for candidate in _select_candidates(db_session, limit=100)}


def test_cli_dry_run_rolls_back_and_apply_commits_once(monkeypatch, capsys):
    calls = []

    class FakeEngine:
        def dispose(self):
            calls.append("dispose")

    class FakeSession:
        def __init__(self, engine):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def commit(self):
            calls.append("commit")

        def rollback(self):
            calls.append("rollback")

    def run(session, *, closed_on, source, apply):
        assert closed_on == date(2026, 11, 9) and source == "himalayas"
        return reopen.ReopenResult(candidates=2, reopened=2 if apply else 0)

    monkeypatch.setattr(reopen, "make_engine", FakeEngine)
    monkeypatch.setattr(reopen, "Session", FakeSession)
    monkeypatch.setattr(reopen, "reopen_rolling_ttl", run)
    reopen.main(["--closed-on", "2026-11-09"])
    assert calls == ["rollback", "dispose"]
    assert "DRY RUN" in capsys.readouterr().out
    calls.clear()
    reopen.main(["--closed-on", "2026-11-09", "--apply"])
    assert calls == ["commit", "dispose"]
    assert "rows reopened: 2" in capsys.readouterr().out
