"""Integration tests for positive-evidence opportunity expiry."""

import json
import uuid
from datetime import datetime, timedelta, timezone
from math import ceil
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core import models
from crawlers import github_lists
from pipeline.expire import (
    FULL_INVENTORY_SOURCES,
    RETIRE_MIN_COVERAGE,
    expire_missing_opportunities,
)


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


def _seed_opportunity(
    db_session: Session,
    suffix: str,
    case: str,
    *,
    last_seen_at: datetime,
    last_crawled_at: datetime | None,
) -> models.Opportunity:
    adapter_key = f"expire-test-adapter-{suffix}"
    board_id = f"expire-test-board-{suffix}"
    source = models.Source(
        slug=f"expire-test-source-{case}-{suffix}",
        name=f"Expire test source {case}",
        adapter_key=adapter_key,
    )
    company = models.Company(
        slug=f"expire-test-company-{case}-{suffix}",
        name=f"Expire test company {case}",
        ats_type=adapter_key,
        ats_board_id=board_id,
    )
    db_session.add_all([source, company])
    db_session.flush()

    opportunity = models.Opportunity(
        slug=f"expire-test-opportunity-{case}-{suffix}",
        company_id=company.id,
        title=f"Expire test opportunity {case}",
        apply_url=f"https://example.com/expire/{case}/{suffix}",
        status="active",
        last_seen_at=last_seen_at,
    )
    db_session.add_all(
        [
            models.SourceState(
                source_id=source.id,
                page_key=board_id,
                last_crawled_at=last_crawled_at,
            ),
            opportunity,
        ]
    )
    db_session.flush()
    return opportunity


def _seed_aggregator_evidence(
    db_session: Session,
    suffix: str,
    case: str,
    *,
    adapter_key: str,
    last_crawled_at: datetime | None,
    crawl_runs: list[tuple[datetime, int | None]],
    coverage: dict | None = None,
) -> None:
    # Tests run transactionally against a real database that may already contain
    # production sources for allowlisted adapter keys. Insert the newest evidence
    # for every matching source id so the assertions do not depend on live crawl
    # timing outside this transaction.
    db_session.add(
        models.Source(
            slug=f"expire-test-aggregator-source-{case}-{adapter_key}-{suffix}",
            name=f"Expire test aggregator source {case}",
            type="aggregator",
            adapter_key=adapter_key,
        )
    )
    db_session.flush()
    sources = db_session.scalars(
        select(models.Source).where(models.Source.adapter_key == adapter_key)
    ).all()
    for source in sources:
        if last_crawled_at is not None:
            db_session.add(
                models.SourceState(
                    source_id=source.id,
                    page_key=f"expire-test-aggregator-{case}-{source.id}-{suffix}",
                    last_crawled_at=last_crawled_at,
                )
            )
        for started_at, listings_found in crawl_runs:
            db_session.add(
                models.CrawlRun(
                    source_id=source.id,
                    tier=1,
                    started_at=started_at,
                    finished_at=started_at + timedelta(minutes=5),
                    status="success",
                    listings_found=listings_found,
                    errors=0,
                    log={"coverage": coverage} if coverage is not None else None,
                )
            )
    db_session.flush()


def _seed_aggregator_opportunity(
    db_session: Session,
    suffix: str,
    case: str,
    *,
    primary_source: str,
    last_seen_at: datetime,
) -> models.Opportunity:
    company = models.Company(
        slug=f"expire-test-aggregator-company-{case}-{suffix}",
        name=f"Expire test aggregator company {case}",
        ats_type=None,
    )
    opportunity = models.Opportunity(
        slug=f"expire-test-aggregator-opportunity-{case}-{suffix}",
        company=company,
        title=f"Expire test aggregator opportunity {case}",
        apply_url=f"https://example.com/expire/aggregator/{case}/{suffix}",
        status="active",
        primary_source=primary_source,
        last_seen_at=last_seen_at,
    )
    db_session.add_all([company, opportunity])
    db_session.flush()
    return opportunity


def _good_coverage_for_primary_source(db_session: Session, primary_source: str) -> int:
    currently_open = db_session.scalar(
        select(func.count(models.Opportunity.id)).where(
            models.Opportunity.status == "active",
            models.Opportunity.closed_at.is_(None),
            models.Opportunity.primary_source == primary_source,
        )
    )
    return max(1, ceil(RETIRE_MIN_COVERAGE * int(currently_open or 0)))


def _status_for_slug(db_session: Session, slug: str) -> str | None:
    db_session.expire_all()
    return db_session.scalar(
        select(models.Opportunity.status).where(models.Opportunity.slug == slug)
    )


def _status_and_closed_at_for_slug(
    db_session: Session, slug: str
) -> tuple[str, datetime | None] | None:
    db_session.expire_all()
    return db_session.execute(
        select(models.Opportunity.status, models.Opportunity.closed_at).where(
            models.Opportunity.slug == slug
        )
    ).one_or_none()


def test_expire_missing_opportunities_marks_listing_closed_absent_from_recent_crawl(
    db_session: Session,
) -> None:
    now = datetime.now(timezone.utc)
    opportunity = _seed_opportunity(
        db_session,
        str(uuid.uuid4()),
        "gone",
        last_seen_at=now - timedelta(hours=8),
        last_crawled_at=now - timedelta(hours=1),
    )

    expire_missing_opportunities(db_session)

    status_and_closed_at = _status_and_closed_at_for_slug(db_session, opportunity.slug)
    assert status_and_closed_at is not None
    status, closed_at = status_and_closed_at
    assert status == "active"
    assert closed_at is not None


def test_expire_missing_opportunities_does_not_reset_closed_at(
    db_session: Session,
) -> None:
    now = datetime.now(timezone.utc)
    original_closed_at = now - timedelta(days=3)
    opportunity = _seed_opportunity(
        db_session,
        str(uuid.uuid4()),
        "already-closed",
        last_seen_at=now - timedelta(hours=8),
        last_crawled_at=now - timedelta(hours=1),
    )
    opportunity.closed_at = original_closed_at
    db_session.flush()

    expire_missing_opportunities(db_session)

    status_and_closed_at = _status_and_closed_at_for_slug(db_session, opportunity.slug)
    assert status_and_closed_at == ("active", original_closed_at)


def test_expire_missing_opportunities_keeps_listing_seen_after_crawl(
    db_session: Session,
) -> None:
    now = datetime.now(timezone.utc)
    opportunity = _seed_opportunity(
        db_session,
        str(uuid.uuid4()),
        "present",
        last_seen_at=now - timedelta(minutes=30),
        last_crawled_at=now - timedelta(hours=1),
    )

    expire_missing_opportunities(db_session)

    assert _status_for_slug(db_session, opportunity.slug) == "active"


def test_expire_missing_opportunities_keeps_listings_when_crawl_is_stale(
    db_session: Session,
) -> None:
    now = datetime.now(timezone.utc)
    opportunity = _seed_opportunity(
        db_session,
        str(uuid.uuid4()),
        "stale",
        last_seen_at=now - timedelta(days=6),
        last_crawled_at=now - timedelta(days=5),
    )

    expire_missing_opportunities(db_session)

    assert _status_for_slug(db_session, opportunity.slug) == "active"


def test_expire_missing_opportunities_keeps_listings_when_board_was_never_crawled(
    db_session: Session,
) -> None:
    opportunity = _seed_opportunity(
        db_session,
        str(uuid.uuid4()),
        "never-crawled",
        last_seen_at=datetime.now(timezone.utc) - timedelta(days=6),
        last_crawled_at=None,
    )

    expire_missing_opportunities(db_session)

    assert _status_for_slug(db_session, opportunity.slug) == "active"


def test_expire_missing_opportunities_keeps_windowed_aggregator_absence_open(
    db_session: Session,
) -> None:
    now = datetime.now(timezone.utc)
    suffix = str(uuid.uuid4())
    assert "remoteok" not in FULL_INVENTORY_SOURCES
    opportunity = _seed_aggregator_opportunity(
        db_session,
        suffix,
        "windowed-source",
        primary_source="remoteok",
        last_seen_at=now - timedelta(hours=12),
    )
    _seed_aggregator_evidence(
        db_session,
        suffix,
        "windowed-source",
        adapter_key="remoteok",
        last_crawled_at=now - timedelta(hours=1),
        crawl_runs=[(now - timedelta(hours=1), 100)],
    )

    expire_missing_opportunities(db_session)

    assert _status_and_closed_at_for_slug(db_session, opportunity.slug) == ("active", None)


def test_expire_missing_opportunities_marks_allowlisted_aggregator_absence_closed(
    db_session: Session,
) -> None:
    now = datetime.now(timezone.utc)
    suffix = str(uuid.uuid4())
    assert "unstop" in FULL_INVENTORY_SOURCES
    opportunity = _seed_aggregator_opportunity(
        db_session,
        suffix,
        "allowlisted-source",
        primary_source="unstop",
        last_seen_at=now - timedelta(hours=12),
    )
    _seed_aggregator_evidence(
        db_session,
        suffix,
        "allowlisted-source",
        adapter_key="unstop",
        last_crawled_at=now - timedelta(hours=1),
        crawl_runs=[
            (
                now - timedelta(hours=1),
                _good_coverage_for_primary_source(db_session, "unstop"),
            )
        ],
    )

    expire_missing_opportunities(db_session)

    status_and_closed_at = _status_and_closed_at_for_slug(db_session, opportunity.slug)
    assert status_and_closed_at is not None
    status, closed_at = status_and_closed_at
    assert status == "active"
    assert closed_at is not None


def test_expire_missing_opportunities_keeps_allowlisted_source_when_run_truncated(
    db_session: Session,
) -> None:
    now = datetime.now(timezone.utc)
    suffix = str(uuid.uuid4())
    first = _seed_aggregator_opportunity(
        db_session,
        f"{suffix}-1",
        "truncated-source-one",
        primary_source="devpost",
        last_seen_at=now - timedelta(hours=12),
    )
    second = _seed_aggregator_opportunity(
        db_session,
        f"{suffix}-2",
        "truncated-source-two",
        primary_source="devpost",
        last_seen_at=now - timedelta(hours=13),
    )
    _seed_aggregator_evidence(
        db_session,
        suffix,
        "truncated-source",
        adapter_key="devpost",
        last_crawled_at=now - timedelta(hours=1),
        crawl_runs=[
            (now - timedelta(hours=3), 1_000_000),
            (now - timedelta(hours=1), 0),
        ],
    )

    expire_missing_opportunities(db_session)

    assert _status_and_closed_at_for_slug(db_session, first.slug) == ("active", None)
    assert _status_and_closed_at_for_slug(db_session, second.slug) == ("active", None)


def test_expire_missing_opportunities_with_good_coverage_closes_absent_only(
    db_session: Session,
) -> None:
    now = datetime.now(timezone.utc)
    suffix = str(uuid.uuid4())
    absent = _seed_aggregator_opportunity(
        db_session,
        f"{suffix}-absent",
        "good-coverage-absent",
        primary_source="devfolio",
        last_seen_at=now - timedelta(hours=12),
    )
    seen_after_crawl = _seed_aggregator_opportunity(
        db_session,
        f"{suffix}-present",
        "good-coverage-present",
        primary_source="devfolio",
        last_seen_at=now - timedelta(minutes=30),
    )
    _seed_aggregator_evidence(
        db_session,
        suffix,
        "good-coverage",
        adapter_key="devfolio",
        last_crawled_at=now - timedelta(hours=1),
        crawl_runs=[
            (
                now - timedelta(hours=1),
                _good_coverage_for_primary_source(db_session, "devfolio"),
            )
        ],
    )

    expire_missing_opportunities(db_session)

    status_and_closed_at = _status_and_closed_at_for_slug(db_session, absent.slug)
    assert status_and_closed_at is not None
    status, closed_at = status_and_closed_at
    assert status == "active"
    assert closed_at is not None
    assert _status_and_closed_at_for_slug(db_session, seen_after_crawl.slug) == (
        "active",
        None,
    )


def test_expire_missing_opportunities_keeps_allowlisted_source_when_run_count_unknown(
    db_session: Session,
) -> None:
    now = datetime.now(timezone.utc)
    suffix = str(uuid.uuid4())
    opportunity = _seed_aggregator_opportunity(
        db_session,
        suffix,
        "unknown-run-count",
        primary_source="unstop",
        last_seen_at=now - timedelta(hours=12),
    )
    _seed_aggregator_evidence(
        db_session,
        suffix,
        "unknown-run-count",
        adapter_key="unstop",
        last_crawled_at=now - timedelta(hours=1),
        crawl_runs=[
            (now - timedelta(hours=3), 1_000_000),
            (now - timedelta(hours=1), None),
        ],
    )

    expire_missing_opportunities(db_session)

    assert _status_and_closed_at_for_slug(db_session, opportunity.slug) == ("active", None)


def test_expire_missing_opportunities_marks_past_deadline_rows_closed(
    db_session: Session,
) -> None:
    suffix = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    original_closed_at = now - timedelta(days=5)
    company = models.Company(
        slug=f"expire-test-deadline-company-{suffix}",
        name=f"Expire test deadline company {suffix}",
    )
    expired_deadline = models.Opportunity(
        slug=f"expire-test-deadline-expired-{suffix}",
        company=company,
        title="Expired deadline opportunity",
        apply_url=f"https://example.com/expire/deadline/expired/{suffix}",
        status="active",
        deadline=now - timedelta(hours=1),
    )
    future_deadline = models.Opportunity(
        slug=f"expire-test-deadline-future-{suffix}",
        company=company,
        title="Future deadline opportunity",
        apply_url=f"https://example.com/expire/deadline/future/{suffix}",
        status="active",
        deadline=now + timedelta(days=1),
    )
    already_closed = models.Opportunity(
        slug=f"expire-test-deadline-already-closed-{suffix}",
        company=company,
        title="Already closed deadline opportunity",
        apply_url=f"https://example.com/expire/deadline/already-closed/{suffix}",
        status="active",
        deadline=now - timedelta(days=1),
        closed_at=original_closed_at,
    )
    inactive = models.Opportunity(
        slug=f"expire-test-deadline-inactive-{suffix}",
        company=company,
        title="Inactive deadline opportunity",
        apply_url=f"https://example.com/expire/deadline/inactive/{suffix}",
        status="closed",
        deadline=now - timedelta(days=1),
    )
    db_session.add_all(
        [
            company,
            expired_deadline,
            future_deadline,
            already_closed,
            inactive,
        ]
    )
    db_session.flush()

    closed_count = expire_missing_opportunities(db_session)

    db_session.expire_all()
    assert closed_count >= 1
    assert _status_and_closed_at_for_slug(db_session, expired_deadline.slug)[0] == "active"
    assert _status_and_closed_at_for_slug(db_session, expired_deadline.slug)[1] is not None
    assert _status_and_closed_at_for_slug(db_session, future_deadline.slug) == ("active", None)
    assert _status_and_closed_at_for_slug(db_session, already_closed.slug) == (
        "active",
        original_closed_at,
    )
    assert _status_and_closed_at_for_slug(db_session, inactive.slug) == ("closed", None)


@pytest.mark.parametrize(
    "coverage",
    [{"status": "partial"}, {"status": "unknown"}, {}, {"status": "complete"}],
)
def test_absence_retirement_requires_recorded_coverage_to_be_complete(
    db_session: Session,
    coverage: dict,
) -> None:
    now = datetime.now(timezone.utc)
    suffix = uuid.uuid4().hex
    opportunity = _seed_aggregator_opportunity(
        db_session,
        suffix,
        "stored-coverage",
        primary_source="unstop",
        last_seen_at=now - timedelta(hours=12),
    )
    slug = opportunity.slug
    _seed_aggregator_evidence(
        db_session,
        suffix,
        "stored-coverage",
        adapter_key="unstop",
        last_crawled_at=now - timedelta(hours=1),
        crawl_runs=[
            (now - timedelta(hours=1), _good_coverage_for_primary_source(db_session, "unstop"))
        ],
        coverage=coverage,
    )
    expire_missing_opportunities(db_session)
    status, closed_at = _status_and_closed_at_for_slug(db_session, slug)
    assert status == "active"
    assert (closed_at is not None) is (coverage.get("status") == "complete")


@pytest.mark.parametrize(
    "listing_state,partial,should_close",
    [("absent", False, True), ("absent", True, False), ("inactive", False, True)],
)
@pytest.mark.parametrize("company_ats", [None, "workday"])
def test_github_lists_complete_inventory_closes_missing_and_inactive_but_partial_closes_nothing(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    listing_state: str,
    partial: bool,
    should_close: bool,
    company_ats: str | None,
) -> None:
    """Feed recorded JSON through the adapter before testing retirement evidence."""
    fixture_path = Path(__file__).parent / "fixtures" / "github_lists_sample.json"
    captured = json.loads(fixture_path.read_text(encoding="utf-8-sig"))
    records_by_repo = {entry["repo"]: entry["records"] for entry in captured}
    first_repo = github_lists.LIST_REPOS[0][0]
    target = records_by_repo[first_repo][0].copy()
    if listing_state == "absent":
        records_by_repo[first_repo] = records_by_repo[first_repo][1:]
    else:
        records_by_repo[first_repo][0]["active"] = False

    def respond(request: httpx.Request) -> httpx.Response:
        repo = "/".join(request.url.path.strip("/").split("/")[:2])
        if partial and repo == github_lists.LIST_REPOS[-1][0]:
            return httpx.Response(404)
        rows = records_by_repo[repo]
        closed = rows[-1]
        assert closed["active"] is False
        # Supply a realistic file size using inactive fixture-derived padding.
        rows = rows + [
            closed | {"id": f"fixture-closed-{index}"}
            for index in range(github_lists.MIN_LIST_RECORDS - len(rows))
        ]
        return httpx.Response(200, json=rows)

    adapter = github_lists.GithubListsAdapter()
    adapter._client.close()
    monkeypatch.setattr(github_lists, "sleep", lambda _delay: None)
    with httpx.Client(
        transport=httpx.MockTransport(respond), headers={"User-Agent": github_lists.USER_AGENT}
    ) as client:
        adapter._client = client
        raw_listings = adapter.fetch()
    assert all(raw.source_url != target["url"] for raw in raw_listings)
    assert adapter.coverage()["status"] == ("partial" if partial else "complete")

    now = datetime.now(timezone.utc)
    suffix = str(uuid.uuid4())
    assert "github_lists" in FULL_INVENTORY_SOURCES
    opportunity = _seed_aggregator_opportunity(
        db_session,
        suffix,
        "github-partial",
        primary_source="github_lists",
        last_seen_at=now - timedelta(hours=12),
    )
    opportunity.title = target["title"]
    opportunity.apply_url = target["url"]
    opportunity.company.ats_type = company_ats
    db_session.flush()
    slug = opportunity.slug
    assert len(raw_listings) >= _good_coverage_for_primary_source(db_session, "github_lists")
    _seed_aggregator_evidence(
        db_session,
        suffix,
        "github-partial",
        adapter_key="github_lists",
        last_crawled_at=now - timedelta(hours=1),
        crawl_runs=[(now - timedelta(hours=1), len(raw_listings))],
        coverage=adapter.coverage(),
    )
    expire_missing_opportunities(db_session)
    status, closed_at = _status_and_closed_at_for_slug(db_session, slug)
    assert status == "active"
    assert (closed_at is not None) is should_close


def test_complete_workday_search_never_absence_retires_listing(db_session: Session) -> None:
    now = datetime.now(timezone.utc)
    suffix = uuid.uuid4().hex
    opportunity = _seed_opportunity(
        db_session,
        suffix,
        "workday-search",
        last_seen_at=now - timedelta(days=5),
        last_crawled_at=now - timedelta(hours=1),
    )
    company = db_session.get(models.Company, opportunity.company_id)
    company.ats_type = "workday"
    source = db_session.scalar(
        select(models.Source).where(models.Source.adapter_key == f"expire-test-adapter-{suffix}")
    )
    source.adapter_key = "workday"
    opportunity.primary_source = "workday"
    db_session.flush()
    slug = opportunity.slug
    expire_missing_opportunities(db_session)
    assert _status_and_closed_at_for_slug(db_session, slug) == ("active", None)
