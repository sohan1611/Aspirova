"""ATS dispatch regressions. Only the two tests using seeded_boards need Postgres.

Those tests commit fixtures because run_tier owns its sessions. Run them only
against a throwaway local database, never production.
"""

import io
import threading
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from psycopg.errors import DeadlockDetected, QueryCanceled, UniqueViolation
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from core import models
from core.adapters import NormalizedListing, RawListing
from crawlers import runner
from crawlers.watchdog import CrawlWatchdog
from pipeline.ingest import ingest_one as real_ingest_one


def _raw(external_id, *, version=1):
    return RawListing(
        source_slug="parallel-test",
        external_id=external_id,
        source_url=f"https://parallel.test/{external_id}",
        content_hash=f"{external_id}-v{version}",
        raw_payload={"id": external_id, "version": version},
    )


def _company(index, adapter_key="parallel-test"):
    return SimpleNamespace(
        id=index,
        slug=f"company-{index}",
        name=f"Company {index}",
        ats_type=adapter_key,
        ats_board_id=f"board-{index}",
    )


def _scaffold(monkeypatch, companies, sources=None, states=(), prefetched=None):
    sources = sources or [SimpleNamespace(id=1, adapter_key="parallel-test")]
    sessions = []
    notified = []
    if prefetched is None:
        prefetched = {
            company.slug: runner._PrefetchedBoard([_raw(company.slug)], "ok")
            for company in companies
        }

    class FakeSession:
        def __init__(self, _engine, **kwargs):
            self.owner = threading.get_ident()
            self.options = kwargs
            self.rollbacks = 0
            sessions.append(self)

        def __enter__(self):
            assert self.owner == threading.get_ident()
            return self

        def __exit__(self, *_args):
            assert self.owner == threading.get_ident()

        def scalars(self, query):
            entity = query.column_descriptions[0]["entity"]
            if entity is models.Source:
                values = sources
            elif entity is models.SourceState:
                values = states
            else:
                adapter_key = next(iter(query.compile().params.values()))
                values = [company for company in companies if company.ats_type == adapter_key]
            return SimpleNamespace(all=lambda: list(values))

        def scalar(self, query):
            assert self.owner == threading.get_ident()
            slug = next(iter(query.compile().params.values()))
            return next(company for company in companies if company.slug == slug)

        def get(self, _model, source_id):
            assert self.owner == threading.get_ident()
            return next(source for source in sources if source.id == source_id)

        def rollback(self):
            self.rollbacks += 1

    for source in sources:
        monkeypatch.setitem(runner.ATS_ADAPTERS, source.adapter_key, object)
    monkeypatch.setattr(runner, "Session", FakeSession)
    monkeypatch.setattr(runner, "make_engine", lambda: object())
    monkeypatch.setattr(runner, "verify_connection_guards", lambda _engine: None)
    monkeypatch.setattr(runner, "_refresh_prestige_matches", lambda _engine: None)
    monkeypatch.setattr(runner, "notify_changed", lambda slugs: notified.append(set(slugs)))
    monkeypatch.setattr(runner, "_prefetch_ats_boards", lambda *_a, **_kw: prefetched)
    monkeypatch.setattr(runner.watchdog, "beat", lambda _activity: None)
    return sessions, notified


@pytest.mark.parametrize(
    "value, expected",
    [
        (None, 4),
        ("1", 1),
        ("0", 1),
        ("-3", 1),
        ("6", 6),
        ("7", 6),
        ("99", 6),
        ("abc", 4),
        ("2.5", 4),
    ],
)
def test_ats_ingest_workers_env(monkeypatch, capsys, value, expected):
    monkeypatch.delenv("CRAWLER_ATS_INGEST_WORKERS", raising=False)
    if value is not None:
        monkeypatch.setenv("CRAWLER_ATS_INGEST_WORKERS", value)
    assert runner._configured_ats_ingest_workers() == expected
    output = capsys.readouterr().out
    assert output == (
        "WARNING: CRAWLER_ATS_INGEST_WORKERS must be an integer; using 4 workers\n"
        if value in {"abc", "2.5"}
        else ""
    )


@pytest.mark.parametrize("value, expected", [(0, 1), (-3, 1), (1, 1), (4, 4), (6, 6), (99, 6)])
def test_run_tier_clamps_explicit_workers(monkeypatch, capsys, value, expected):
    _scaffold(monkeypatch, [_company(1)])
    monkeypatch.setenv("CRAWLER_ATS_INGEST_WORKERS", "2")
    monkeypatch.setattr(runner, "crawl_company_board", lambda *_a, **_kw: {})
    runner.run_tier(1, "ats", ats_ingest_workers=value)
    assert f"ATS INGEST: 1 boards, 1 groups, {expected} workers" in capsys.readouterr().out


def test_run_tier_uses_env_workers(monkeypatch, capsys):
    _scaffold(monkeypatch, [_company(1)])
    monkeypatch.setenv("CRAWLER_ATS_INGEST_WORKERS", "3")
    monkeypatch.setattr(runner, "crawl_company_board", lambda *_a, **_kw: {})
    runner.run_tier(1, "ats")
    assert "ATS INGEST: 1 boards, 1 groups, 3 workers" in capsys.readouterr().out


def test_inline_dispatch_preserves_clock_calls_and_uses_no_executor(monkeypatch, capsys):
    companies = [_company(index) for index in [3, 2, 1]]
    _scaffold(monkeypatch, companies)
    ran = []
    monkeypatch.setattr(
        runner, "crawl_company_board", lambda _s, _src, co, *_a, **_kw: ran.append(co.slug) or {}
    )

    def no_executor(**_kwargs):
        pytest.fail("inline ingestion must not create an executor")

    monkeypatch.setattr(runner, "ThreadPoolExecutor", no_executor)
    ticks = iter([0.0, 1.0, 100.0, 200.0])
    monkeypatch.setattr(runner, "time", SimpleNamespace(monotonic=ticks.__next__))
    runner.run_tier(1, "ats", ats_ingest_workers=1, ats_max_seconds=50)
    assert ran == ["company-3"]
    assert next(ticks, None) is None
    assert "TRUNCATED: ATS stopped early after 100.0s (budget 50.0s)" in capsys.readouterr().out


def test_company_boards_never_overlap_and_keep_order(monkeypatch):
    companies = [_company(1)] + [_company(index, "parallel-other") for index in range(2, 7)]
    sources = [SimpleNamespace(id=index, adapter_key="parallel-test") for index in [1, 2, 3]]
    sources.append(SimpleNamespace(id=4, adapter_key="parallel-other"))
    sessions, _ = _scaffold(monkeypatch, companies, sources)
    intervals = {}
    active = 0
    peak = 0
    lock = threading.Lock()

    def crawl(session, source, company, *_args, **_kwargs):
        nonlocal active, peak
        assert session.owner == threading.get_ident()
        assert session.options == {"expire_on_commit": False}
        with lock:
            active += 1
            peak = max(peak, active)
            start = time.monotonic()
        time.sleep(0.05)
        with lock:
            intervals[(company.id, source.id)] = (
                start,
                time.monotonic(),
                threading.current_thread().name,
            )
            active -= 1
        return {}

    monkeypatch.setattr(runner, "crawl_company_board", crawl)
    runner.run_tier(1, "ats", ats_ingest_workers=4)
    assert len(intervals) == 8
    assert len(sessions) == 9  # gather plus exactly one session per board
    assert 2 <= peak <= 4
    same_company = [(source_id, intervals[(1, source_id)]) for source_id in [1, 2, 3]]
    assert sorted(same_company, key=lambda entry: entry[1][0]) == same_company
    assert all(left[1][1] <= right[1][0] for left, right in zip(same_company, same_company[1:]))
    assert all(interval[2].startswith("ats-ingest") for interval in intervals.values())


def test_groups_union_all_conflicts_transitively():
    # 0--1 company, 1--2 board key, 2--3 external id; 4 and 5 unrelated.
    jobs = [
        runner._AtsJob(1, 1, "a", "parallel-test", "a", "A"),
        runner._AtsJob(1, 2, "b", "parallel-test", "shared", "B"),
        runner._AtsJob(2, 2, "c", "parallel-test", "shared", "C"),
        runner._AtsJob(3, 2, "d", "parallel-test", "d", "D"),
        runner._AtsJob(4, 3, "e", "parallel-test", "shared", "E"),
        runner._AtsJob(5, 2, "f", "parallel-test", "f", "F"),
    ]
    prefetched = {
        "c": runner._PrefetchedBoard([_raw("R0001")], "ok"),
        "d": runner._PrefetchedBoard([_raw("R0001")], "ok"),
        "e": runner._PrefetchedBoard([_raw("R0001")], "ok"),
        "f": runner._PrefetchedBoard([_raw("unrelated")], "ok"),
    }
    assert runner._ats_ingest_groups(jobs, prefetched) == [0, 0, 0, 0, 4, 5]


def test_submission_is_stalest_first_with_four_workers(monkeypatch):
    companies = [_company(index) for index in range(1, 7)]
    states = [
        SimpleNamespace(
            source_id=1,
            page_key=f"board-{index}",
            last_crawled_at=datetime(2026, 11, index, tzinfo=timezone.utc),
        )
        for index in range(1, 6)
    ]
    _scaffold(monkeypatch, companies, states=states)
    submitted = []

    class RecordingExecutor(ThreadPoolExecutor):
        def submit(self, function, engine, job, *args):
            assert threading.current_thread() is threading.main_thread()
            submitted.append(job.company_slug)
            return super().submit(function, engine, job, *args)

    monkeypatch.setattr(runner, "ThreadPoolExecutor", RecordingExecutor)
    monkeypatch.setattr(runner, "crawl_company_board", lambda *_a, **_kw: {})
    runner.run_tier(1, "ats", ats_ingest_workers=4)
    assert submitted == ["company-6", *[f"company-{index}" for index in range(1, 6)]]


def test_worker_exception_preserves_committed_slugs_and_other_boards(monkeypatch, capsys):
    companies = [_company(index) for index in range(1, 7)]
    sessions, notified = _scaffold(monkeypatch, companies)
    ran = []

    def crawl(_session, _source, company, *_args, changed_slugs, **_kwargs):
        ran.append(company.slug)
        changed_slugs.add(f"committed-{company.slug}")
        if company.id == 3:
            raise RuntimeError("board exploded after a commit")
        return {}

    monkeypatch.setattr(runner, "crawl_company_board", crawl)
    runner.run_tier(1, "ats", ats_ingest_workers=4)
    assert Counter(ran) == Counter(company.slug for company in companies)
    assert notified == [{f"committed-{company.slug}" for company in companies}]
    assert sum(session.rollbacks for session in sessions) == 1
    assert "ERROR: company-3 crawl raised unexpectedly: board exploded" in capsys.readouterr().out


def test_coverage_keeps_board_order_including_failed_fetches(monkeypatch, capsys):
    monkeypatch.setattr(runner, "_FULL_LIST_SOURCE_KEYS", {"parallel-test"})
    companies = [_company(index) for index in [3, 2, 1]]
    prefetched = {
        company.slug: runner._PrefetchedBoard([_raw(company.slug)], "ok")
        for company in companies
        if company.id != 2
    }
    outputs = []
    for workers in [1, 4]:
        sessions, _ = _scaffold(monkeypatch, companies, prefetched=prefetched)

        def crawl(_session, _source, company, *_args, **_kwargs):
            time.sleep(0.03 if company.id == 3 else 0)
            return {
                "coverage": runner._coverage_record(
                    fetched=1,
                    mode="full_list",
                    status="partial",
                    details={
                        "boards_total": 1,
                        "boards_complete": 0,
                        "incomplete_boards": [company.ats_board_id],
                    },
                )
            }

        monkeypatch.setattr(runner, "crawl_company_board", crawl)
        runner.run_tier(1, "ats", ats_ingest_workers=workers)
        outputs.append(
            [line for line in capsys.readouterr().out.splitlines() if line.startswith("COVERAGE:")]
        )
        assert len(sessions) == 3  # no session for the missing prefetch
    assert outputs[0] == outputs[1]
    assert "incomplete: board-3, board-2, board-1" in outputs[0][0]


@pytest.mark.parametrize("stop_by_signal", [False, True])
def test_parallel_gate_records_once_then_drains_before_printing(
    monkeypatch, capsys, stop_by_signal
):
    companies = [_company(index) for index in range(1, 7)]
    sessions, notified = _scaffold(monkeypatch, companies)
    barrier = threading.Barrier(2, timeout=5)
    release = threading.Event()
    expired = threading.Event()
    started = []
    finished = []
    lock = threading.Lock()

    def crawl(_session, _source, company, *_args, changed_slugs, **_kwargs):
        with lock:
            started.append(company.slug)
            first = len(started) == 1
        barrier.wait()
        if first:
            expired.set()
        else:
            assert release.wait(5)
        changed_slugs.add(company.slug)
        with lock:
            finished.append(company.slug)
        return {}

    def stop_requested():
        if expired.is_set():
            release.set()
        return stop_by_signal and expired.is_set()

    def monotonic():
        assert threading.current_thread() is threading.main_thread()
        if expired.is_set():
            release.set()
            return 100.0
        return 0.0

    def emit(message, **_kwargs):
        if message.startswith("TRUNCATED: ATS"):
            assert set(finished) == set(started)
            assert not any(thread.name.startswith("ats-ingest") for thread in threading.enumerate())
        real_emit(message)

    real_emit = runner._emit
    monkeypatch.setattr(runner, "crawl_company_board", crawl)
    monkeypatch.setattr(runner, "time", SimpleNamespace(monotonic=monotonic))
    monkeypatch.setattr(runner, "_emit", emit)
    runner.run_tier(1, "ats", ats_ingest_workers=2, ats_max_seconds=50, should_stop=stop_requested)
    output = capsys.readouterr().out.splitlines()
    assert len(started) == len(finished) == 2
    assert len(sessions) == 3
    assert notified == [set(started)]
    assert [line for line in output if line.startswith("TRUNCATED: ATS")] == [
        "TRUNCATED: ATS stopped early after 100.0s (budget 50.0s)"
    ]
    assert sum(line.startswith("  - ATS:") for line in output) == 1
    assert (
        "Stop requested; ending ATS ingestion after committed work"
        if stop_by_signal
        else "ATS time budget reached; ending after committed work"
    ) in output


@pytest.mark.parametrize("listing_count, expected_new", [(27, 25), (52, 27)])
@pytest.mark.parametrize("error_kind", ["deadlock", "timeout", "integrity"])
def test_batch_commit_errors_roll_back_reload_and_preserve_prior_commits(
    monkeypatch, listing_count, expected_new, error_kind
):
    # Fail the second commit: either a full 25-listing batch or the trailing
    # short batch. Neither may discard the first committed batch's slugs.
    failure = (
        IntegrityError("commit", {}, UniqueViolation("unique violation"))
        if error_kind == "integrity"
        else OperationalError(
            "commit",
            {},
            (
                DeadlockDetected("deadlock detected")
                if error_kind == "deadlock"
                else QueryCanceled("statement timeout")
            ),
        )
    )

    class FakeSession:
        commits = 0
        rollbacks = 0

        def scalar(self, _query):
            return None

        def commit(self):
            self.commits += 1
            if self.commits == 2:
                raise failure

        def rollback(self):
            self.rollbacks += 1

    reloads = []

    def load(*_args, **_kwargs):
        reloads.append(1)
        return {}

    class Adapter:
        def __init__(self, **_kwargs):
            pass

        def parse(self, raw):
            return raw

    def ingest(_session, _state, _source_id, _company_id, raw, _normalized, **kwargs):
        kwargs["changed_slugs"].add(raw.external_id)
        return object(), True

    monkeypatch.setattr(runner, "load_source_raw_listings", load)
    monkeypatch.setattr(runner, "load_board_state", lambda *_args: object())
    monkeypatch.setattr(runner, "ingest_one", ingest)
    monkeypatch.setattr(runner, "_record_crawl_run", lambda *_args, **_kwargs: None)
    session = FakeSession()
    changed = set()
    result = runner.crawl_company_board(
        session,
        SimpleNamespace(id=1, crawl_tier=1, adapter_key="parallel-test"),
        _company(1),
        Adapter,
        prefetched=[_raw(str(index)) for index in range(listing_count)],
        prefetched_health="degraded",  # no fingerprint/state write in this fake
        changed_slugs=changed,
    )
    assert session.rollbacks == 1
    assert len(reloads) == 2
    assert result["status"] == "partial"
    assert result["errors"] == 1
    assert result["new_opps"] == result["changed_slugs"] == len(changed) == expected_new
    assert {str(index) for index in range(25)} <= changed


def test_final_seen_update_error_uses_batch_rollback_reload(monkeypatch):
    # A linked row can belong to a different company, so even the final bulk
    # timestamp update can encounter a lock error after listing batches commit.
    reloads = []

    class FakeSession:
        rollbacks = 0

        def scalar(self, _query):
            return None

        def commit(self):
            pass

        def rollback(self):
            self.rollbacks += 1

        def execute(self, _query):
            raise OperationalError("update", {}, DeadlockDetected("deadlock detected"))

    class Adapter:
        def __init__(self, **_kwargs):
            pass

        def parse(self, raw):
            return raw

    def ingest(_session, _state, _sid, _cid, _raw, _normalized, **kwargs):
        kwargs["seen_opportunity_ids"].add(99)
        kwargs["changed_slugs"].add("committed")
        return object(), True

    monkeypatch.setattr(
        runner, "load_source_raw_listings", lambda *_a, **_kw: reloads.append(1) or {}
    )
    monkeypatch.setattr(runner, "load_board_state", lambda *_a: object())
    monkeypatch.setattr(runner, "ingest_one", ingest)
    monkeypatch.setattr(runner, "_record_crawl_run", lambda *_a, **_kw: None)
    session = FakeSession()
    changed = set()
    result = runner.crawl_company_board(
        session,
        SimpleNamespace(id=1, crawl_tier=1, adapter_key="parallel-test"),
        _company(1),
        Adapter,
        prefetched=[_raw("one")],
        prefetched_health="ok",
        changed_slugs=changed,
    )
    assert result["status"] == "partial"
    assert result["errors"] == result["new_opps"] == session.rollbacks == 1
    assert changed == {"committed"}
    assert len(reloads) == 2


def test_emit_and_watchdog_write_complete_lines_once(monkeypatch):
    class RecordingStream(io.StringIO):
        def __init__(self):
            super().__init__()
            self.writes = []
            self.flushes = 0

        def write(self, value):
            self.writes.append(value)
            return super().write(value)

        def flush(self):
            self.flushes += 1

    output = RecordingStream()
    monkeypatch.setattr(runner.sys, "stdout", output)
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(runner._emit, [f"line-{index}" for index in range(40)]))
    watchdog = CrawlWatchdog(
        hang_after_seconds=0, on_soft_hang=lambda: None, clock=lambda: 0, output=output
    )
    watchdog.check_once()
    assert len(output.writes) == output.flushes == 41
    assert all(value.endswith("\n") and value.count("\n") == 1 for value in output.writes)
    assert output.writes[-1].startswith("HUNG:")


@pytest.fixture
def seeded_boards(engine, monkeypatch):
    """Committed test-only rows, removed in FK order even on assertion failure."""
    unique = uuid.uuid4().hex[:12]
    adapter_key = f"parallel-{unique}"
    tier = 32001
    counts = [0, 1, 4, 12, 24, 25, 26, 27, 35, 48, 60, 3]
    listings = {}
    failed_boards = {"board-11"}
    notified = []

    class FakeAdapter:
        source_slug = adapter_key
        requires_browser = False

        def __init__(self, board_token, company_name):
            # An unexpected adapter setup failure escapes _fetch_company_board;
            # prefetch must omit it and the dispatcher must open no session.
            if board_token in failed_boards:
                raise RuntimeError("deterministic prefetch failure")
            self.board_token = board_token
            self.company_name = company_name

        def fetch(self):
            return listings[self.board_token]

        def health(self):
            return "ok"

        def coverage(self):
            return {"expected_total": len(listings[self.board_token]), "mode": "declared_total"}

        def parse(self, raw):
            version = raw.raw_payload["version"]
            return NormalizedListing(
                source_slug=adapter_key,
                external_id=raw.external_id,
                source_url=raw.source_url,
                title=f"Parallel Role {raw.external_id}",
                company_name=self.company_name,
                # Distinct locations prevent fuzzy dedup from merging synthetic roles.
                location=f"Bengaluru, India {raw.external_id}",
                description_raw=f"Python engineering role. Version {version} "
                + "details " * version,
                apply_url=raw.source_url,
            )

    source_id = None
    company_ids = []

    def reset_derived():
        with Session(engine) as session:
            opportunity_ids = select(models.Opportunity.id).where(
                models.Opportunity.company_id.in_(company_ids)
            )
            for model in [
                models.OpportunityTag,
                models.OpportunitySource,
                models.Notification,
                models.OpportunityViewCount,
            ]:
                session.execute(delete(model).where(model.opportunity_id.in_(opportunity_ids)))
            session.execute(
                delete(models.RawListing).where(models.RawListing.source_id == source_id)
            )
            session.execute(delete(models.CrawlRun).where(models.CrawlRun.source_id == source_id))
            session.execute(
                delete(models.SourceState).where(models.SourceState.source_id == source_id)
            )
            session.execute(
                delete(models.Opportunity).where(models.Opportunity.company_id.in_(company_ids))
            )
            session.commit()

    try:
        with Session(engine, expire_on_commit=False) as session:
            source = models.Source(
                slug=f"test-isolation-{unique}",
                name="Parallel test",
                type="ats",
                adapter_key=adapter_key,
                crawl_tier=tier,
            )
            companies = [
                models.Company(
                    slug=f"test-isolation-co-{unique}-{index}",
                    name=f"Parallel Test {unique} {index}",
                    name_normalized=f"parallel test {unique} {index}",
                    ats_type=adapter_key,
                    ats_board_id=f"board-{index}",
                )
                for index in range(len(counts))
            ]
            session.add_all([source, *companies])
            session.commit()
            source_id = source.id
            company_ids = [company.id for company in companies]

        monkeypatch.setitem(runner.ATS_ADAPTERS, adapter_key, FakeAdapter)
        monkeypatch.setattr(runner, "make_engine", lambda: engine)
        monkeypatch.setattr(runner, "verify_connection_guards", lambda _engine: None)
        monkeypatch.setattr(runner, "_refresh_prestige_matches", lambda _engine: None)
        monkeypatch.setattr(runner, "notify_changed", lambda slugs: notified.append(set(slugs)))

        def set_round(round_number):
            listings.clear()
            for index, count in enumerate(counts):
                ids = list(range(count))
                if round_number == 2 and count:
                    ids = ids[1:] + [count, count + 1]  # one removed, two added
                listings[f"board-{index}"] = [
                    _raw(
                        f"{unique}-{index}-{number}", version=round_number if number % 3 == 0 else 1
                    )
                    for number in ids
                ]

        set_round(1)
        yield SimpleNamespace(
            engine=engine,
            source_id=source_id,
            companies=companies,
            tier=tier,
            listings=listings,
            notified=notified,
            set_round=set_round,
            reset_derived=reset_derived,
            failed_boards=failed_boards,
            unique=unique,
        )
    finally:
        reset_derived()
        with Session(engine) as session:
            session.execute(delete(models.Company).where(models.Company.id.in_(company_ids)))
            session.execute(delete(models.Source).where(models.Source.id == source_id))
            session.commit()


def _without_clock(key, value):
    """destination_facts is compared in full except its two clock stamps."""
    if key == "destination_facts" and isinstance(value, dict):
        return {k: v for k, v in value.items() if k not in {"computed_at", "checked_at"}}
    return value


def _snapshot(seed):
    """Stable values only: ids and clock-dependent columns are deliberately absent."""
    with Session(seed.engine) as session:
        companies = {company.id: company.slug for company in seed.companies}
        source_slug = session.get(models.Source, seed.source_id).slug
        opportunities = session.scalars(
            select(models.Opportunity).where(models.Opportunity.company_id.in_(companies))
        ).all()
        slugs = {opportunity.id: opportunity.slug for opportunity in opportunities}
        raw_rows = session.scalars(
            select(models.RawListing).where(models.RawListing.source_id == seed.source_id)
        ).all()
        external_ids = {row.id: row.external_id for row in raw_rows}
        # All non-time opportunity fields, except the trigger-maintained search vector.
        excluded = {
            "id",
            "company_id",
            "search_tsv",
            "posted_at",
            "deadline",
            "closed_at",
            "first_seen_at",
            "last_seen_at",
            "created_at",
            "updated_at",
        }
        return {
            "opportunities": {
                opportunity.slug: {
                    **{
                        column.key: _without_clock(column.key, getattr(opportunity, column.key))
                        for column in models.Opportunity.__table__.columns
                        if column.key not in excluded
                    },
                    "company": companies[opportunity.company_id],
                }
                for opportunity in opportunities
            },
            "raw_listings": {
                (source_slug, row.external_id): (
                    row.source_url,
                    row.content_hash,
                    row.raw_payload,
                    row.processed,
                    slugs.get(row.opportunity_id),
                )
                for row in raw_rows
            },
            "opportunity_sources": sorted(
                (
                    slugs[row.opportunity_id],
                    source_slug,
                    row.source_url,
                    external_ids[row.raw_listing_id],
                    row.is_primary,
                )
                for row in session.scalars(
                    select(models.OpportunitySource).where(
                        models.OpportunitySource.source_id == seed.source_id
                    )
                )
            ),
            "source_state": sorted(
                (source_slug, row.page_key, row.last_content_hash)
                for row in session.scalars(
                    select(models.SourceState).where(models.SourceState.source_id == seed.source_id)
                )
            ),
            "crawl_runs": sorted(
                (row.log["company_slug"], row.status, row.listings_found, row.new_opps, row.errors)
                for row in session.scalars(
                    select(models.CrawlRun).where(models.CrawlRun.source_id == seed.source_id)
                )
            ),
        }


def test_parallel_matches_inline_across_two_committed_crawls(seeded_boards, monkeypatch, capsys):
    seed = seeded_boards
    failed_external_id = f"{seed.unique}-10-26"  # failure in batch two of a 60-listing board

    def ingest(session, *args, **kwargs):
        raw = args[3]
        if raw.external_id == failed_external_id:
            session.execute(text("SELECT 1/0"))  # a real aborted Postgres transaction
        return real_ingest_one(session, *args, **kwargs)

    monkeypatch.setattr(runner, "ingest_one", ingest)
    snapshots = {}
    for workers in [1, 4]:
        seed.reset_derived()
        seed.notified.clear()
        rounds = []
        for round_number in [1, 2]:
            seed.set_round(round_number)
            runner.run_tier(seed.tier, "ats", ats_ingest_workers=workers, ats_max_seconds=10_000)
            coverage = [
                line
                for line in capsys.readouterr().out.splitlines()
                if line.startswith("COVERAGE:")
            ]
            rounds.append((_snapshot(seed), set(seed.notified[-1]), coverage))
        snapshots[workers] = rounds
    assert snapshots[1] == snapshots[4]
    first = snapshots[1][0][0]
    assert any(run[2] == 0 for run in first["crawl_runs"])
    assert any(run[4] == 1 for run in first["crawl_runs"])
    assert any(run[3] >= 25 for run in first["crawl_runs"])
    assert len(first["crawl_runs"]) == 11


def test_tiny_budget_drains_workers_and_leaves_unstarted_boards_untouched(
    seeded_boards, monkeypatch, capsys
):
    seed = seeded_boards
    seed.failed_boards.clear()
    seed.set_round(1)
    # Give every board a listing, including the initially empty board.
    for company in seed.companies:
        seed.listings[company.ats_board_id] = [_raw(f"{seed.unique}-{company.ats_board_id}")]
    both_started = threading.Barrier(2, timeout=10)
    release_second = threading.Event()
    started = set()
    finished = set()
    clock = SimpleNamespace(value=0.0)
    lock = threading.Lock()
    real_crawl = runner.crawl_company_board

    def crawl(session, source, company, *args, **kwargs):
        with lock:
            started.add(company.slug)
            first = len(started) == 1
        both_started.wait()
        if not first:
            assert release_second.wait(10)
        result = real_crawl(session, source, company, *args, **kwargs)
        with lock:
            finished.add(company.slug)
            if first:
                clock.value = 100.0
        return result

    def monotonic():
        assert threading.current_thread() is threading.main_thread()
        if clock.value >= 100:
            release_second.set()  # gate sees expiry while the other board is still in flight
        return clock.value

    monkeypatch.setattr(runner, "crawl_company_board", crawl)
    monkeypatch.setattr(runner, "time", SimpleNamespace(monotonic=monotonic))
    real_emit = runner._emit

    def emit(message, **kwargs):
        if message.startswith("TRUNCATED: ATS"):
            assert finished == started
            assert not any(thread.name.startswith("ats-ingest") for thread in threading.enumerate())
        return real_emit(message, **kwargs)

    monkeypatch.setattr(runner, "_emit", emit)
    try:
        runner.run_tier(seed.tier, "ats", ats_ingest_workers=2, ats_max_seconds=50)
    finally:
        release_second.set()
    output = capsys.readouterr().out.splitlines()
    assert len(started) == 2
    assert finished == started
    assert [line for line in output if line.startswith("TRUNCATED: ATS")] == [
        "TRUNCATED: ATS stopped early after 100.0s (budget 50.0s)"
    ]
    assert sum(line.startswith("  - ATS:") for line in output) == 1
    snapshot = _snapshot(seed)
    assert {run[0] for run in snapshot["crawl_runs"]} == started
    assert len(snapshot["crawl_runs"]) == 2
    for company in seed.companies:
        has_started = company.slug in started
        assert (
            any(value["company"] == company.slug for value in snapshot["opportunities"].values())
            == has_started
        )
        assert (
            any(row[1] == company.ats_board_id for row in snapshot["source_state"]) == has_started
        )
        assert (
            any(
                key[1] == f"{seed.unique}-{company.ats_board_id}"
                for key in snapshot["raw_listings"]
            )
            == has_started
        )
