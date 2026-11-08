"""Unit and integration coverage for undated listing liveness checks."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from core import models
from pipeline.liveness import _classify_status_code, check_listing_liveness
from pipeline.liveness import _select_candidates, fetch_url_liveness_status


@pytest.fixture
def db_session(engine):
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def _opportunity(
    db_session: Session,
    *,
    suffix: str,
    name: str,
    last_seen_at: datetime,
    deadline: datetime | None = None,
    closed_at: datetime | None = None,
    status: str = "active",
) -> models.Opportunity:
    opportunity = models.Opportunity(
        slug=f"liveness-{name}-{suffix}",
        title=f"Liveness {name}",
        category="job",
        apply_url=f"https://example.com/liveness/{name}/{suffix}",
        deadline=deadline,
        closed_at=closed_at,
        status=status,
        last_seen_at=last_seen_at,
    )
    db_session.add(opportunity)
    db_session.flush()
    return opportunity


def test_liveness_marks_only_stale_undated_confirmed_gone_rows(
    db_session: Session,
) -> None:
    now = datetime.now(timezone.utc)
    suffix = uuid.uuid4().hex
    gone = _opportunity(
        db_session,
        suffix=suffix,
        name="gone",
        last_seen_at=now - timedelta(days=8),
    )
    alive = _opportunity(
        db_session,
        suffix=suffix,
        name="alive",
        last_seen_at=now - timedelta(days=7),
    )
    blocked = _opportunity(
        db_session,
        suffix=suffix,
        name="blocked",
        last_seen_at=now - timedelta(days=6),
    )
    fresh = _opportunity(
        db_session,
        suffix=suffix,
        name="fresh",
        last_seen_at=now - timedelta(days=1),
    )
    dated = _opportunity(
        db_session,
        suffix=suffix,
        name="dated",
        last_seen_at=now - timedelta(days=9),
        deadline=now + timedelta(days=10),
    )
    already_closed = _opportunity(
        db_session,
        suffix=suffix,
        name="already-closed",
        last_seen_at=now - timedelta(days=10),
        closed_at=now - timedelta(days=2),
    )

    decisions = {
        gone.apply_url: "closed",
        alive.apply_url: "alive",
        blocked.apply_url: "inconclusive",
    }
    checked_urls: list[str] = []

    def checker(url: str):
        checked_urls.append(url)
        return decisions[url]

    result = check_listing_liveness(
        db_session,
        apply=True,
        limit=10,
        max_seconds=60,
        batch_size=1,
        commit_each_batch=False,
        now=now,
        checker=checker,
    )
    db_session.expire_all()

    rows = dict(
        db_session.execute(
            select(models.Opportunity.slug, models.Opportunity.closed_at).where(
                models.Opportunity.slug.in_(
                    [
                        gone.slug,
                        alive.slug,
                        blocked.slug,
                        fresh.slug,
                        dated.slug,
                        already_closed.slug,
                    ]
                )
            )
        ).all()
    )
    assert result.scanned == 3
    assert result.closed == 1
    assert result.alive == 1
    assert result.inconclusive == 1
    assert checked_urls == [gone.apply_url, alive.apply_url, blocked.apply_url]
    assert rows[gone.slug] == now
    assert rows[alive.slug] is None
    assert rows[blocked.slug] is None
    assert rows[fresh.slug] is None
    assert rows[dated.slug] is None
    assert rows[already_closed.slug] == now - timedelta(days=2)
    assert (
        db_session.scalar(
            select(models.Opportunity.status).where(models.Opportunity.slug == gone.slug)
        )
        == "active"
    )


def test_liveness_dry_run_does_not_mutate_rows(db_session: Session) -> None:
    now = datetime.now(timezone.utc)
    suffix = uuid.uuid4().hex
    gone = _opportunity(
        db_session,
        suffix=suffix,
        name="dry-run-gone",
        last_seen_at=now - timedelta(days=8),
    )

    result = check_listing_liveness(
        db_session,
        apply=False,
        limit=10,
        max_seconds=60,
        now=now,
        checker=lambda _url: "closed",
    )
    db_session.expire_all()

    assert result.closed == 1
    assert (
        db_session.scalar(
            select(models.Opportunity.closed_at).where(models.Opportunity.slug == gone.slug)
        )
        is None
    )


def test_liveness_status_code_classification_is_conservative() -> None:
    assert _classify_status_code(404) == "closed"
    assert _classify_status_code(410) == "closed"
    assert _classify_status_code(200) == "alive"
    assert _classify_status_code(302) == "alive"
    assert _classify_status_code(400) == "inconclusive"
    assert _classify_status_code(403) == "inconclusive"
    assert _classify_status_code(429) == "inconclusive"
    assert _classify_status_code(500) == "inconclusive"


@pytest.mark.parametrize(
    "host,query,expected",
    [
        ("job-boards.greenhouse.io", "error=true", "closed"),
        ("boards.greenhouse.io", "foo=bar&error=true", "closed"),
        ("job-boards.greenhouse.io", "error=false", "alive"),
        ("job-boards.greenhouse.io", "", "alive"),
        ("job-boards.greenhouse.io.evil.example", "error=true", "alive"),
        ("example.com", "error=true", "alive"),
    ],
)
def test_greenhouse_soft_404_after_redirect(host, query, expected):
    def respond(request):
        if request.url.host == "original.example":
            return httpx.Response(302, headers={"location": f"https://{host}/webflow?{query}"})
        return httpx.Response(200, text="board page")

    with httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=True) as client:
        assert fetch_url_liveness_status("https://original.example/jobs/1", client) == expected


def test_liveness_rotates_every_outcome_without_clobbering_meta(db_session):
    now = datetime.now(timezone.utc)
    suffix = uuid.uuid4().hex
    rows = [
        _opportunity(
            db_session, suffix=suffix, name=status, last_seen_at=now - timedelta(days=20 - index)
        )
        for index, status in enumerate(("inconclusive", "alive", "closed"))
    ]
    for row in rows:
        row.meta = {"summary_source": "deterministic", "keep": {"nested": True}}
    db_session.flush()
    outcomes = dict(zip((row.apply_url for row in rows), ("inconclusive", "alive", "closed")))
    check_listing_liveness(
        db_session, apply=True, checker=lambda url: outcomes[url], now=now, commit_each_batch=False
    )
    db_session.expire_all()
    for row in rows:
        assert row.meta == {
            "summary_source": "deterministic",
            "keep": {"nested": True},
            "liveness_checked_at": now.isoformat(),
        }
    selected = {row.id for row in _select_candidates(db_session, limit=100)}
    assert not selected.intersection(row.id for row in rows)


def test_liveness_orders_never_checked_then_old_checks_and_skips_rolling(db_session):
    now = datetime.now(timezone.utc)
    suffix = uuid.uuid4().hex
    rows = [
        _opportunity(
            db_session, suffix=suffix, name=name, last_seen_at=now - timedelta(days=20 + index)
        )
        for index, name in enumerate(("never", "old-check", "recent-check", "rolling"))
    ]
    rows[1].meta = {"liveness_checked_at": (now - timedelta(days=4)).isoformat()}
    rows[2].meta = {"liveness_checked_at": (now - timedelta(days=2)).isoformat()}
    rows[3].primary_source = "remoteok"
    db_session.flush()
    assert [row.id for row in _select_candidates(db_session, limit=100)] == [rows[0].id, rows[1].id]


def test_liveness_stamps_json_null_meta(db_session):
    now = datetime.now(timezone.utc)
    row = _opportunity(
        db_session, suffix=uuid.uuid4().hex, name="null-meta", last_seen_at=now - timedelta(days=10)
    )
    row.meta = None
    db_session.flush()
    check_listing_liveness(
        db_session, apply=True, checker=lambda url: "inconclusive", now=now, commit_each_batch=False
    )
    db_session.expire_all()
    assert row.meta == {"liveness_checked_at": now.isoformat()}
