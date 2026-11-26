"""TRUST-02 contracts; database cases use only the caller's disposable DB."""

import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from core import models
from core.destination_facts import classify_destination_facts, retain_alive_verification, url_key
from core.freshness import SOURCE_CADENCE, cadence, is_stale, last_verified, stale_expression
from crawlers import runner
from pipeline.crawl_safety import permits_absence
from pipeline.destination_check import inspect_destination
from pipeline.expire import expire_missing_opportunities
from pipeline.liveness import check_listing_liveness
from pipeline.retirement import retire_rolling_window_listings

NOW = datetime(2026, 11, 26, 12, tzinfo=timezone.utc)


def listing(source="greenhouse", *, age=200, **kwargs):
    return models.Opportunity(
        slug=uuid.uuid4().hex,
        title="Software Engineer Intern",
        apply_url=f"https://example.org/postings/{uuid.uuid4().hex}",
        primary_source=source,
        last_seen_at=NOW - timedelta(hours=age),
        status="active",
        **kwargs,
    )


def observation(row, status="alive", code=200, now=NOW, **kwargs):
    return {
        "url_key": url_key(row.apply_url),
        "status": status,
        "http_status": code,
        "checked_at": now.isoformat(),
        "warnings": [],
        **kwargs,
    }


def facts(row, status="alive", code=200, now=NOW):
    return classify_destination_facts(
        row.apply_url, observation=observation(row, status, code, now)
    )


def test_every_adapter_has_one_cadence_and_defaults_are_safe():
    assert set(runner.ATS_ADAPTERS) | set(runner.AGGREGATOR_ADAPTERS) == set(SOURCE_CADENCE)
    assert cadence(None) == cadence("future-source")
    assert all(
        c.crawl_hours <= c.target_hours < c.stale_hours and c.check_hours < c.stale_hours
        for c in SOURCE_CADENCE.values()
    )


@pytest.mark.parametrize("source", sorted(SOURCE_CADENCE))
def test_stale_boundary_and_reseen_soft_reopen(source):
    row = listing(source, age=cadence(source).stale_hours)
    assert not is_stale(row, NOW)
    assert is_stale(row, NOW + timedelta(seconds=1))
    assert row.closed_at is None
    row.last_seen_at = NOW
    assert not is_stale(row, NOW)


def test_positive_check_retained_through_unknown_and_cleared_on_destination_change():
    row = listing(age=1000)
    row.destination_facts = retain_alive_verification(facts(row))
    assert last_verified(row) == NOW
    assert not is_stale(row, NOW)
    for status, code in (
        ("unknown", 403),
        ("unknown", 429),
        ("unknown", 503),
        ("unknown", None),
        ("sign_in_required", 401),
        ("gone", 404),
    ):
        row.destination_facts = retain_alive_verification(
            facts(row, status, code, NOW + timedelta(hours=1)), row.destination_facts
        )
        assert last_verified(row) == NOW
    row.apply_url += "/changed"
    row.destination_facts = retain_alive_verification(
        facts(row, "unknown", 403), row.destination_facts
    )
    assert is_stale(row, NOW)


def test_recent_unknown_is_not_verification_and_sql_uses_the_same_evidence():
    row = listing(age=1000)
    row.destination_facts = facts(row, "unknown", 403)
    assert last_verified(row) == row.last_seen_at
    assert is_stale(row, NOW)
    sql = str(stale_expression(NOW).compile(dialect=postgresql.dialect()))
    assert "last_seen_at" in sql and "destination_facts" in sql and "make_interval" in sql


def test_old_posting_stays_stale_after_positive_verification():
    from api.filters import is_stale_opportunity

    row = listing(
        age=1000, posted_at=NOW - timedelta(days=400), first_seen_at=NOW - timedelta(days=400)
    )
    assert is_stale_opportunity(row, NOW)
    row.destination_facts = retain_alive_verification(facts(row))
    assert is_stale_opportunity(row, NOW)
    assert is_stale(row, NOW)
    row.destination_facts = facts(row, "unknown", 403)
    row.last_seen_at = NOW
    assert is_stale_opportunity(row, NOW)
    assert is_stale(row, NOW)


@pytest.mark.parametrize(
    "status,coverage,found,errors",
    [
        ("failed", "complete", 1000, 1),
        ("partial", "complete", 1000, 0),
        ("running", "complete", 1000, 0),
        ("success", "partial", 1000, 0),
        ("success", "complete", 0, 0),
        ("success", "complete", 100, 0),
        ("success", "complete", 1000, 1),
    ],
)
def test_circuit_breaker_failed_incomplete_empty_or_short_run(status, coverage, found, errors):
    history = [{"status": "success", "finished_at": NOW, "listings_found": 1000}] * 7
    run = {
        "status": status,
        "finished_at": NOW,
        "listings_found": found,
        "errors": errors,
        "log": {"coverage": {"status": coverage}},
    }
    assert not permits_absence(run, history)
    run.update(
        status="success", listings_found=1000, errors=0, log={"coverage": {"status": "complete"}}
    )
    assert permits_absence(run, history)


@pytest.mark.parametrize("code", [403, 429, 500, 503])
def test_unknown_never_becomes_gone_or_positive_verification(code):
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(code))
    ) as client:
        result = inspect_destination("https://example.org/jobs/1", client, resolve=lambda *_: True)
    assert result["status"] == "unknown"


@pytest.mark.parametrize(
    "location,body,same",
    [
        (None, "Software Engineer Intern", True),
        (None, "Welcome to our careers page", False),
        ("/careers", "Software Engineer Intern", False),
    ],
)
def test_rescue_requires_same_posting_title_and_path(location, body, same):
    def respond(request):
        if location and request.url.path == "/jobs/1":
            return httpx.Response(302, headers={"location": location})
        return httpx.Response(200, text=body)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = inspect_destination(
            "https://example.org/jobs/1",
            client,
            expected_title="Software Engineer Intern",
            resolve=lambda *_: True,
        )
    assert result.get("same_posting", False) == same


@pytest.fixture
def db_session(engine):
    with engine.connect() as connection:
        tx = connection.begin()
        with Session(bind=connection) as session:
            yield session
        tx.rollback()


@pytest.mark.parametrize("source", ["remoteok", "himalayas", "greenhouse", "unstop"])
def test_soft_aging_never_writes_hard_closure_and_positive_check_clears_it(
    db_session, source, monkeypatch
):
    from pipeline import liveness

    now = datetime.now(timezone.utc)
    row = listing(source, age=5000)
    db_session.add(row)
    db_session.flush()
    retire_rolling_window_listings(db_session)
    assert row.closed_at is None
    assert is_stale(row, now)
    monkeypatch.setattr(
        liveness,
        "fetch_destination_observation",
        lambda url, *_a, **_kw: {
            "url_key": url_key(url),
            "status": "alive",
            "http_status": 200,
            "checked_at": now.isoformat(),
            "warnings": [],
            "same_posting": True,
        },
    )
    result = check_listing_liveness(
        db_session,
        apply=True,
        freshness_mode=True,
        now=now,
        commit_each_batch=False,
    )
    db_session.expire_all()
    assert result.alive >= 1
    assert not is_stale(row, now)


def test_crawl_presence_reopens_legacy_ttl_and_inventory_absence(db_session):
    now = datetime.now(timezone.utc)
    rows = [
        listing(
            "himalayas",
            closed_at=now - timedelta(days=1),
            meta={"closed_reason": "rolling_window_ttl"},
        ),
        listing("greenhouse", closed_at=now - timedelta(days=1), meta={"closed_reason": "absence"}),
    ]
    db_session.add_all(rows)
    db_session.flush()
    runner._reopen_seen_rolling_listings(db_session, [rows[0].id])
    runner._reopen_seen_inventory_listings(db_session, [rows[1].id])
    db_session.expire_all()
    assert all(row.closed_at is None for row in rows)


def test_rescue_reopens_same_posting_but_not_gone_or_generic_page(db_session, monkeypatch):
    from pipeline import liveness

    now = datetime.now(timezone.utc)
    rows = [listing("remoteok", closed_at=now - timedelta(days=1)) for _ in range(3)]
    db_session.add_all(rows)
    db_session.flush()
    obs = {
        rows[0].apply_url: observation(rows[0], now=now, same_posting=True),
        rows[1].apply_url: observation(rows[1], "gone", 404, now),
        rows[2].apply_url: observation(rows[2], now=now, same_posting=False),
    }
    monkeypatch.setattr(liveness, "fetch_destination_observation", lambda url, *a, **k: obs[url])
    monkeypatch.setattr(liveness, "sleep", lambda _: None)
    result = check_listing_liveness(
        db_session, apply=True, rescue=True, now=now, concurrency=1, commit_each_batch=False
    )
    db_session.expire_all()
    assert result.reopened == 1
    assert rows[0].closed_at is None
    assert all(row.closed_at is not None for row in rows[1:])


@pytest.mark.parametrize(
    "status,found", [("failed", 1000), ("partial", 1000), ("running", 0), ("success", 100)]
)
def test_failed_or_short_full_inventory_crawl_never_closes_catalogue(db_session, status, found):
    now = datetime.now(timezone.utc)
    source = models.Source(slug=uuid.uuid4().hex, adapter_key="unstop", type="aggregator")
    company = models.Company(slug=uuid.uuid4().hex, name="Fixture company")
    db_session.add_all([source, company])
    db_session.flush()
    rows = [listing("unstop", company_id=company.id) for _ in range(10)]
    db_session.add_all(rows)
    db_session.add(
        models.SourceState(source_id=source.id, page_key="aggregator", last_crawled_at=now)
    )
    for age in range(1, 8):
        db_session.add(
            models.CrawlRun(
                source_id=source.id,
                started_at=now - timedelta(days=age),
                finished_at=now - timedelta(days=age),
                status="success",
                listings_found=1000,
                log={"coverage": {"status": "complete"}},
            )
        )
    db_session.add(
        models.CrawlRun(
            source_id=source.id,
            started_at=now,
            finished_at=now if status != "running" else None,
            status=status,
            listings_found=found,
            log={"coverage": {"status": "complete"}},
        )
    )
    db_session.flush()
    expire_missing_opportunities(db_session)
    db_session.expire_all()
    assert all(row.closed_at is None for row in rows)


@pytest.mark.parametrize(
    "source_key",
    ["remoteok", "himalayas", "arbeitnow", "jobicy", "hackerearth", "amazon", "workday", "drdo"],
)
def test_partial_sources_never_close_on_absence_even_with_apparently_complete_run(
    db_session, source_key
):
    now = datetime.now(timezone.utc)
    source = models.Source(
        slug=uuid.uuid4().hex,
        adapter_key=source_key,
        type="ats" if source_key in {"amazon", "workday"} else "aggregator",
    )
    company = models.Company(
        slug=uuid.uuid4().hex, name="Fixture", ats_type=source_key, ats_board_id=uuid.uuid4().hex
    )
    db_session.add_all([source, company])
    db_session.flush()
    row = listing(source_key, company_id=company.id)
    db_session.add_all(
        [
            row,
            models.SourceState(
                source_id=source.id, page_key=company.ats_board_id, last_crawled_at=now
            ),
            models.CrawlRun(
                source_id=source.id,
                status="success",
                started_at=now,
                finished_at=now,
                listings_found=1000,
                log={"coverage": {"status": "complete"}},
            ),
        ]
    )
    db_session.flush()
    expire_missing_opportunities(db_session)
    db_session.expire_all()
    assert row.closed_at is None


def test_ats_journal_marks_running_before_fetch_and_finishes_only_covered_sources(monkeypatch):
    from types import SimpleNamespace

    events = []

    class Journal:
        def __init__(self, _):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def add(self, row):
            row.id = row.source_id
            events.append(("add", row.status, row.log))

        def flush(self):
            pass

        def commit(self):
            events.append(("commit",))

        def execute(self, statement):
            events.append(("finish", statement.compile().params))

    monkeypatch.setattr(runner, "Session", Journal)
    jobs = [SimpleNamespace(source_id=1), SimpleNamespace(source_id=2)]
    ids = runner._begin_ats_freshness_batch(object(), 1, jobs)
    assert ids == {1: 1, 2: 2}
    assert events[-1] == ("commit",)
    assert all(event[1] == "running" for event in events if event[0] == "add")
    runner._finish_ats_freshness_batch(object(), ids, jobs, {0: {"status": "complete"}})
    finishes = [event[1]["status"] for event in events if event[0] == "finish"]
    assert finishes == ["success", "partial"]


def test_no_transaction_during_cadence_network_batches(monkeypatch):
    from pipeline import liveness

    class TrackingSession:
        in_transaction = True

        def commit(self):
            self.in_transaction = False

    session = TrackingSession()
    candidates = [liveness.LivenessCandidate(i, f"https://example.org/jobs/{i}") for i in (1, 2)]
    monkeypatch.setattr(liveness, "_select_freshness_candidates", lambda *_a, **_kw: candidates)
    monkeypatch.setattr(
        liveness, "_stamp_checked", lambda *_: setattr(session, "in_transaction", True)
    )
    monkeypatch.setattr(liveness, "_store_observations", lambda *_: None)
    monkeypatch.setattr(liveness, "_reopen_verified", lambda *_a, **_kw: 0)
    monkeypatch.setattr(liveness, "_mark_closed", lambda *_a, **_kw: 0)

    def network(_):
        assert not session.in_transaction
        return "alive"

    result = check_listing_liveness(
        session, apply=True, freshness_mode=True, batch_size=1, checker=network
    )
    assert result.alive == 2
    assert not session.in_transaction


def test_slo_cli_enforces_read_only_before_measurement(monkeypatch, capsys):
    from scripts import freshness_slo

    events = []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def begin(self):
            return self

        def execute(self, statement):
            events.append(str(statement))

    class Engine:
        def connect(self):
            return Connection()

        def dispose(self):
            events.append("disposed")

    monkeypatch.setattr(freshness_slo, "make_engine", Engine)

    def measure(_):
        assert "READ ONLY" in events[0] and "REPEATABLE READ" in events[0]
        return []

    monkeypatch.setattr(freshness_slo, "measure", measure)
    freshness_slo.main()
    assert events[-1] == "disposed"
    assert "source=greenhouse visible=0" in capsys.readouterr().out


def test_sql_freshness_matches_python_and_read_only_measurement(db_session):
    from scripts.freshness_slo import measure
    from api.filters import exclude_stale_opportunities

    baseline = measure(db_session)
    row = listing(
        age=1000, posted_at=NOW - timedelta(days=400), first_seen_at=NOW - timedelta(days=400)
    )
    row.destination_facts = retain_alive_verification(facts(row))
    db_session.add(row)
    db_session.flush()
    sql_stale = db_session.scalar(
        select(stale_expression(NOW)).where(models.Opportunity.id == row.id)
    )
    assert sql_stale == is_stale(row, NOW)
    assert (
        db_session.scalar(
            select(models.Opportunity.id).where(
                models.Opportunity.id == row.id, exclude_stale_opportunities(NOW)
            )
        )
        is None
    )
    assert measure(db_session) == baseline


def test_recovery_revalidation_selects_only_stale_or_closed_returned_rows(db_session):
    rows = [
        listing(age=1000),
        listing(age=1),
        listing(age=1, closed_at=NOW - timedelta(days=1)),
        listing(age=1000, posted_at=NOW - timedelta(days=400)),
        listing(age=1000),
    ]
    db_session.add_all(rows)
    db_session.flush()
    recovered = set()
    runner._note_freshness_recoveries(db_session, [row.id for row in rows[:4]], recovered)
    assert recovered == {rows[0].slug, rows[2].slug}
    assert not db_session.dirty


def test_deploy_preview_counts_only_new_verification_exclusions(db_session, capsys):
    from scripts.freshness_slo import measure, report

    now = datetime.now(timezone.utc)
    before = {(r["scope"], r["key"]): r for r in measure(db_session)}

    def row(source, hours, *, days=1, deadline=None, alive=False):
        item = listing(source, posted_at=now - timedelta(days=days), deadline=deadline)
        item.last_seen_at = now - timedelta(hours=hours)
        if alive:
            item.destination_facts = retain_alive_verification(facts(item, now=now))
        return item

    db_session.add_all(
        [
            row("greenhouse", 1),
            row("greenhouse", 200),
            row("greenhouse", 200, alive=True),
            row("remoteok", 800),
            row("https://not-a-public-source.example", 300),
            row("lever", 1, days=400, alive=True),
            row("lever", 1, days=400, deadline=now + timedelta(days=1)),
        ]
    )
    db_session.flush()
    rows = measure(db_session)
    after = {(r["scope"], r["key"]): r for r in rows}
    for scope, key, visible, stale in [
        ("source", "greenhouse", 3, 1),
        ("source", "remoteok", 1, 1),
        ("source", "other", 1, 1),
        ("source", "lever", 1, 0),
        ("total", "all", 6, 3),
    ]:
        assert (
            after[scope, key]["visible"] - before.get((scope, key), {}).get("visible", 0) == visible
        )
        assert after[scope, key]["stale"] - before.get((scope, key), {}).get("stale", 0) == stale
    report(rows)
    output = capsys.readouterr().out
    assert "FRESHNESS IMPACT: total=all" in output
    assert "would_be_hidden_or_stale=" in output
    assert "://" not in output


def test_landing_staleness_is_a_row_predicate():
    from sqlalchemy import func
    from api.filters import exclude_stale_opportunities

    sql = str(
        select(func.count())
        .select_from(models.Opportunity)
        .where(exclude_stale_opportunities())
        .compile(dialect=postgresql.dialect())
    )
    assert sql.upper().count("SELECT") == 1
    assert "first_seen_at" in sql and "last_seen_at" in sql and "destination_facts" in sql
