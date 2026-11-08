"""Transactional fixtures for the architect's throwaway PostgreSQL run."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from core import models
from core.adapters import RawListing
from crawlers import runner
from crawlers.ashby import AshbyAdapter
from pipeline.expire import expire_missing_opportunities
from pipeline.retirement import (
    find_dead_boards,
    retire_dead_board_listings,
    retire_rolling_window_listings,
)


@pytest.fixture
def db_session(engine):
    with engine.connect() as connection:
        transaction = connection.begin()
        with Session(bind=connection) as session:
            yield session
        transaction.rollback()


@pytest.fixture
def board(db_session):
    token = f"audit-{uuid.uuid4().hex}"
    source = models.Source(slug=token, adapter_key="greenhouse", type="ats")
    company = models.Company(slug=token, name="Audit", ats_type="greenhouse", ats_board_id=token)
    db_session.add_all([source, company])
    db_session.flush()
    return source, company, token


def _opportunity(session, company, source, *, url=None, days=40):
    row = models.Opportunity(
        slug=uuid.uuid4().hex,
        company_id=company.id,
        title="Audit listing",
        apply_url=url
        or f"https://job-boards.greenhouse.io/{company.ats_board_id}/jobs/{uuid.uuid4().hex}",
        primary_source=source,
        last_seen_at=datetime.now(timezone.utc) - timedelta(days=days),
        status="active",
    )
    session.add(row)
    session.flush()
    return row


def _runs(session, board, states, *, hours=None):
    source, _, token = board
    now = datetime.now(timezone.utc)
    hours = hours or [24 * (len(states) - index - 1) for index in range(len(states))]
    for state, age in zip(states, hours):
        session.add(
            models.CrawlRun(
                source_id=source.id,
                started_at=now - timedelta(hours=age),
                finished_at=now - timedelta(hours=age),
                status="partial",
                log={
                    "board_token": token,
                    "board_state": state,
                    "http_status": 200 if state == "empty" else 404,
                },
            )
        )
    session.flush()


@pytest.mark.parametrize(
    "states,hours,closes",
    [
        (["not_found"] * 3, [48, 24, 0], True),
        (["not_found"] * 2, [48, 0], False),
        (["not_found", "error", "not_found"], [48, 24, 0], False),
        (["not_found"] * 3, [47, 24, 0], False),
        (["empty"] * 3, [48, 24, 0], True),
        (["not_found"] * 3, [120, 96, 72], False),
        (["not_found", None, "not_found"], [48, 24, 0], False),
        (["not_found", "not_found", "ok"], [48, 24, 0], False),
    ],
)
def test_dead_streak_guards_and_provenance(db_session, board, states, hours, closes):
    source, company, token = board
    dead = _opportunity(db_session, company, "greenhouse")
    aggregator = _opportunity(db_session, company, "unstop", url="https://unstop.com/audit")
    another_board = _opportunity(
        db_session, company, "greenhouse", url="https://job-boards.greenhouse.io/other/jobs/1"
    )
    merged = _opportunity(db_session, company, "greenhouse")
    unstop = models.Source(slug=uuid.uuid4().hex, adapter_key="unstop")
    db_session.add(unstop)
    db_session.flush()
    db_session.add(
        models.OpportunitySource(
            opportunity_id=merged.id, source_id=unstop.id, source_url=aggregator.apply_url
        )
    )
    # Previously populated empty boards retain their old SourceState timestamp.
    db_session.add(
        models.SourceState(
            source_id=source.id,
            page_key=token,
            last_content_hash="populated",
            last_crawled_at=datetime.now(timezone.utc) - timedelta(days=20),
        )
    )
    _runs(db_session, board, states, hours=hours)
    counts = retire_dead_board_listings(db_session)
    assert counts.get(f"greenhouse/{token}", 0) == int(closes)
    db_session.expire_all()
    assert (dead.closed_at is not None) == closes
    assert aggregator.closed_at is None
    assert another_board.closed_at is None
    assert merged.closed_at is None


def test_only_the_last_three_runs_count(db_session, board):
    _runs(db_session, board, ["error", "empty", "not_found", "empty"], hours=[72, 48, 24, 0])
    matches = [row for row in find_dead_boards(db_session) if row.token == board[2]]
    assert len(matches) == 1
    assert matches[0].state == "empty"


@pytest.mark.parametrize(
    "status,age_days,close",
    [
        ("success", 0, True),
        ("partial", 0, True),
        ("failed", 0, False),
        ("success", 3, False),
        (None, 0, False),
    ],
)
def test_rolling_feed_requires_recent_contact_and_preserves_fresh_rows(
    db_session, board, status, age_days, close
):
    _, company, _ = board
    source = models.Source(slug=uuid.uuid4().hex, adapter_key="remoteok")
    other = models.Source(slug=uuid.uuid4().hex, adapter_key="ashby")
    db_session.add_all([source, other])
    db_session.flush()
    stale = _opportunity(db_session, company, "remoteok")
    fresh = _opportunity(db_session, company, "remoteok", days=29)
    merged = _opportunity(db_session, company, "remoteok")
    canonical_fresh = _opportunity(db_session, company, "remoteok", days=1)
    # A fresh company ATS board must not bypass the feed outage/TTL guards.
    db_session.add(
        models.SourceState(
            source_id=board[0].id, page_key=board[2], last_crawled_at=datetime.now(timezone.utc)
        )
    )
    db_session.add(
        models.OpportunitySource(
            opportunity_id=merged.id, source_id=other.id, seen_at=datetime.now(timezone.utc)
        )
    )
    if status is not None:
        seen = datetime.now(timezone.utc) - timedelta(days=age_days)
        db_session.add(
            models.CrawlRun(source_id=source.id, status=status, started_at=seen, finished_at=seen)
        )
    db_session.flush()
    expire_missing_opportunities(db_session)
    retire_rolling_window_listings(db_session)
    db_session.expire_all()
    assert (stale.closed_at is not None) == close
    assert fresh.closed_at is None
    assert merged.closed_at is None
    assert canonical_fresh.closed_at is None


def test_relocated_old_rows_retire_only_after_complete_new_board_crawl(db_session, board):
    _, company, _ = board
    old = _opportunity(db_session, company, "greenhouse")
    unstop = models.Source(slug=uuid.uuid4().hex, adapter_key="unstop", type="aggregator")
    db_session.add(unstop)
    aggregator = _opportunity(db_session, company, "unstop")
    new_source = models.Source(slug=uuid.uuid4().hex, adapter_key="ashby")
    db_session.add(new_source)
    db_session.flush()
    company.ats_type, company.ats_board_id = "ashby", f"new-{company.slug}"
    new = _opportunity(db_session, company, "ashby", days=0)
    # An incomplete new board crawl does not advance SourceState.
    db_session.flush()
    expire_missing_opportunities(db_session)
    db_session.expire_all()
    assert old.closed_at is None
    db_session.add(
        models.SourceState(
            source_id=new_source.id,
            page_key=company.ats_board_id,
            last_crawled_at=datetime.now(timezone.utc),
        )
    )
    db_session.flush()
    expire_missing_opportunities(db_session)
    db_session.expire_all()
    assert old.closed_at is not None
    assert new.closed_at is None
    assert aggregator.closed_at is None


def test_unchanged_new_board_does_not_refresh_migrated_or_aggregator_rows(db_session, board):
    _, company, _ = board
    now = datetime.now(timezone.utc)
    old = _opportunity(db_session, company, "greenhouse")
    aggregator = _opportunity(db_session, company, "remoteok")
    source = models.Source(slug=uuid.uuid4().hex, adapter_key="ashby", crawl_tier=1)
    db_session.add(source)
    db_session.flush()
    company.ats_type, company.ats_board_id = "ashby", f"new-{company.slug}"
    current = _opportunity(db_session, company, "ashby", days=1)
    raw = RawListing(
        source_slug="ashby",
        external_id=uuid.uuid4().hex,
        source_url=f"https://jobs.ashbyhq.com/{company.ats_board_id}/current",
        content_hash="fixture",
        raw_payload={},
    )
    db_session.add(
        models.RawListing(
            source_id=source.id,
            external_id=raw.external_id,
            source_url=raw.source_url,
            content_hash=raw.content_hash,
            opportunity_id=current.id,
        )
    )
    db_session.add(
        models.SourceState(
            source_id=source.id,
            page_key=company.ats_board_id,
            last_content_hash=runner._board_fingerprint([raw]),
            last_crawled_at=now - timedelta(hours=8),
        )
    )
    db_session.flush()
    old_seen, aggregator_seen, current_seen = (
        old.last_seen_at,
        aggregator.last_seen_at,
        current.last_seen_at,
    )
    result = runner.crawl_company_board(
        db_session, source, company, AshbyAdapter, prefetched=[raw], prefetched_health="ok"
    )
    assert result["status"] == "success"
    db_session.expire_all()
    assert old.last_seen_at == old_seen
    assert aggregator.last_seen_at == aggregator_seen
    assert current.last_seen_at > current_seen
    expire_missing_opportunities(db_session)
    db_session.expire_all()
    assert old.closed_at is not None
