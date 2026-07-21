"""Unit coverage for crawler prefetching and graceful soft stops."""

import threading
import time
from types import SimpleNamespace

from core import models
from core.adapters import NormalizedListing, RawListing
from crawlers import runner
from crawlers.unstop import UnstopAdapter


def _raw_listing(external_id: str) -> RawListing:
    return RawListing(
        source_slug="greenhouse",
        external_id=external_id,
        source_url=f"https://example.test/{external_id}",
        content_hash=f"hash-{external_id}",
        raw_payload={"id": external_id},
    )


class _MemorySession:
    """Only the Session surface exercised by the runner unit tests."""

    def __init__(self) -> None:
        self.added: list[object] = []
        self.commits = 0
        self.rollbacks = 0
        self.ingested: list[str] = []
        self.scalar_result = None

    def scalar(self, _query):
        return self.scalar_result

    def add(self, value: object) -> None:
        self.added.append(value)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class _BoardAdapter:
    listings: list[RawListing] = []
    fetch_calls = 0

    def __init__(self, board_token: str, company_name: str) -> None:
        self.board_token = board_token
        self.company_name = company_name

    def fetch(self) -> list[RawListing]:
        type(self).fetch_calls += 1
        return list(self.listings)

    def parse(self, raw: RawListing) -> NormalizedListing:
        return NormalizedListing(
            source_slug=raw.source_slug,
            external_id=raw.external_id,
            source_url=raw.source_url,
            title=f"Role {raw.external_id}",
            company_name=self.company_name,
            description_raw="description",
            apply_url=raw.source_url,
        )

    def health(self) -> str:
        return "ok"


def test_prefetched_board_skips_fetch_and_ingests_identically(monkeypatch) -> None:
    listings = [_raw_listing("one"), _raw_listing("two")]
    _BoardAdapter.listings = listings
    _BoardAdapter.fetch_calls = 0
    source = SimpleNamespace(id=1, crawl_tier=1)
    company = SimpleNamespace(
        id=2,
        slug="example-company",
        name="Example Company",
        ats_board_id="example-board",
    )

    def fake_ingest(
        session, _board_state, _source_id, _company_id, raw, _normalized, seen_opportunity_ids=None
    ):
        session.ingested.append(raw.external_id)
        return object(), True

    monkeypatch.setattr(runner, "load_board_state", lambda *_args: object())
    monkeypatch.setattr(runner, "ingest_one", fake_ingest)

    sequential_session = _MemorySession()
    sequential_result = runner.crawl_company_board(
        sequential_session,
        source,
        company,
        _BoardAdapter,
    )

    prefetched_session = _MemorySession()
    prefetched_result = runner.crawl_company_board(
        prefetched_session,
        source,
        company,
        _BoardAdapter,
        prefetched=listings,
        prefetched_health="ok",
    )

    assert sequential_result == prefetched_result
    assert sequential_session.ingested == prefetched_session.ingested == ["one", "two"]
    assert _BoardAdapter.fetch_calls == 1


def test_ats_prefetch_is_bounded_and_isolates_failed_boards(monkeypatch) -> None:
    active_fetches = 0
    peak_fetches = 0
    lock = threading.Lock()

    class _ConcurrentAdapter:
        def __init__(self, board_token: str, company_name: str) -> None:
            self.board_token = board_token
            self.company_name = company_name

        def fetch(self) -> list[RawListing]:
            nonlocal active_fetches, peak_fetches
            if self.board_token == "bad-board":
                raise RuntimeError("expected fetch failure")

            with lock:
                active_fetches += 1
                peak_fetches = max(peak_fetches, active_fetches)
            try:
                time.sleep(0.02)
                return [_raw_listing(self.board_token)]
            finally:
                with lock:
                    active_fetches -= 1

        def health(self) -> str:
            return "ok"

    monkeypatch.setitem(runner.ATS_ADAPTERS, "concurrent-test", _ConcurrentAdapter)
    board_tokens = [*(f"board-{number}" for number in range(12)), "bad-board"]
    jobs = [
        runner._AtsJob(
            company_id=1,
            source_id=1,
            company_slug=f"company-{board_token}",
            adapter_key="concurrent-test",
            board_token=board_token,
            company_name="Example Company",
        )
        for board_token in board_tokens
    ]

    prefetched = runner._prefetch_ats_boards(jobs)

    assert set(prefetched) == {
        f"company-{board_token}" for board_token in board_tokens if board_token != "bad-board"
    }
    assert 1 < peak_fetches <= runner.ATS_FETCH_MAX_WORKERS


def test_ats_prefetch_stops_queued_work_after_a_stop_signal(monkeypatch) -> None:
    stop_requested = threading.Event()
    release_fetches = threading.Event()
    started_boards: list[str] = []
    lock = threading.Lock()

    class _BlockingAdapter:
        def __init__(self, board_token: str, company_name: str) -> None:
            self.board_token = board_token
            self.company_name = company_name

        def fetch(self) -> list[RawListing]:
            with lock:
                started_boards.append(self.board_token)
            stop_requested.set()
            release_fetches.wait(timeout=2.0)
            return [_raw_listing(self.board_token)]

        def health(self) -> str:
            return "ok"

    monkeypatch.setitem(runner.ATS_ADAPTERS, "blocking-test", _BlockingAdapter)
    jobs = [
        runner._AtsJob(
            company_id=1,
            source_id=1,
            company_slug=f"company-{number}",
            adapter_key="blocking-test",
            board_token=f"board-{number}",
            company_name="Example Company",
        )
        for number in range(runner.ATS_FETCH_MAX_WORKERS + 3)
    ]

    started_at = time.monotonic()
    try:
        runner._prefetch_ats_boards(jobs, should_stop=stop_requested.is_set)
    finally:
        release_fetches.set()
    elapsed = time.monotonic() - started_at

    assert elapsed < 1.0
    assert len(started_boards) <= runner.ATS_FETCH_MAX_WORKERS


def test_run_tier_ingests_other_boards_when_one_prefetch_fails(monkeypatch) -> None:
    source = SimpleNamespace(id=1, adapter_key="runner-prefetch-test")
    # Descending ids: these boards are all never-crawled, so they tie on the
    # primary staleness key and _order_ats_jobs falls through to -company_id.
    # Numbering them downward keeps crawl order == list order, so this test
    # stays about prefetch isolation rather than about ordering.
    companies = [
        SimpleNamespace(
            id=3,
            slug="good-one",
            name="Good One",
            ats_board_id="good-one",
        ),
        SimpleNamespace(
            id=2,
            slug="bad-one",
            name="Bad One",
            ats_board_id="bad-one",
        ),
        SimpleNamespace(
            id=1,
            slug="good-two",
            name="Good Two",
            ats_board_id="good-two",
        ),
    ]

    class _Result:
        def __init__(self, values: list[object]) -> None:
            self.values = values

        def all(self) -> list[object]:
            return self.values

    class _GatherSession:
        def __init__(self) -> None:
            self.calls = 0

        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
            pass

        def scalars(self, query) -> _Result:
            # Stalest-first ordering reads SourceState; none exist in this test.
            try:
                if query.column_descriptions[0]["entity"].__name__ == "SourceState":
                    return _Result([])
            except (AttributeError, IndexError, KeyError, TypeError):
                pass
            self.calls += 1
            return _Result([source] if self.calls == 1 else companies)

    class _IngestSession:
        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
            pass

        def get(self, _model, _source_id):
            return source

        def scalar(self, _query):
            return companies[0]

        def rollback(self) -> None:
            pass

    class _SessionFactory:
        def __init__(self) -> None:
            self.sessions: list[object] = []

        def __call__(self, _engine, **_kwargs):
            session = _GatherSession() if not self.sessions else _IngestSession()
            self.sessions.append(session)
            return session

    class _Adapter:
        def __init__(self, board_token: str, company_name: str) -> None:
            self.board_token = board_token
            self.company_name = company_name

        def fetch(self) -> list[RawListing]:
            if self.board_token == "bad-one":
                raise RuntimeError("expected fetch failure")
            return [_raw_listing(self.board_token)]

        def health(self) -> str:
            return "ok"

    session_factory = _SessionFactory()
    ingested_ids: list[str] = []

    def fake_crawl(
        _session,
        _source,
        _company,
        _adapter_class,
        *,
        prefetched,
        prefetched_health,
        **_kwargs,
    ):
        assert prefetched_health == "ok"
        ingested_ids.append(prefetched[0].external_id)
        return {}

    monkeypatch.setitem(runner.ATS_ADAPTERS, "runner-prefetch-test", _Adapter)
    monkeypatch.setattr(runner, "make_engine", lambda: object())
    monkeypatch.setattr(runner, "verify_connection_guards", lambda _engine: None)
    monkeypatch.setattr(runner, "Session", session_factory)
    monkeypatch.setattr(runner, "crawl_company_board", fake_crawl)

    runner.run_tier(1, group="ats")

    assert ingested_ids == ["good-one", "good-two"]
    assert len(session_factory.sessions) == 3  # gather + one session per successful board


class _AggregatorAdapter:
    def fetch(self) -> list[RawListing]:
        return [_raw_listing("one"), _raw_listing("two"), _raw_listing("three")]

    def parse(self, raw: RawListing) -> NormalizedListing:
        return NormalizedListing(
            source_slug=raw.source_slug,
            external_id=raw.external_id,
            source_url=raw.source_url,
            title=f"Role {raw.external_id}",
            company_name="Example Company",
            description_raw="description",
            apply_url=raw.source_url,
        )

    def health(self) -> str:
        return "ok"


def test_aggregator_deadline_commits_completed_work_and_returns_partial(monkeypatch) -> None:
    session = _MemorySession()
    source = SimpleNamespace(id=1, crawl_tier=1)
    previous_state = SimpleNamespace(
        last_content_hash="full-feed-fingerprint",
        last_crawled_at="before-partial-run",
    )
    session.scalar_result = previous_state

    def fake_ingest(
        _session, _board_state, _source_id, _company_id, raw, _normalized, seen_opportunity_ids=None
    ):
        session.ingested.append(raw.external_id)
        return object(), True

    def fake_monotonic() -> float:
        # The deadline begins at 10. Once the first listing has been
        # ingested, the next loop check crosses it and triggers a clean stop.
        return 11.0 if session.ingested else 0.0

    monkeypatch.setattr(runner, "load_board_state", lambda *_args: object())
    monkeypatch.setattr(runner, "resolve_company", lambda *_args: SimpleNamespace(id=2))
    monkeypatch.setattr(runner, "ingest_one", fake_ingest)
    monkeypatch.setattr(runner.time, "monotonic", fake_monotonic)

    result = runner.crawl_aggregator(
        session,
        source,
        _AggregatorAdapter,
        max_seconds=10.0,
    )

    assert result == {"listings_found": 3, "new_opps": 1, "errors": 0, "status": "partial"}
    assert session.ingested == ["one"]
    assert session.commits >= 3  # trailing batch, final state, and CrawlRun
    crawl_runs = [value for value in session.added if isinstance(value, models.CrawlRun)]
    assert [crawl_run.status for crawl_run in crawl_runs] == ["partial"]
    assert not any(isinstance(value, models.SourceState) for value in session.added)
    assert previous_state.last_content_hash == "full-feed-fingerprint"
    assert previous_state.last_crawled_at == "before-partial-run"


def test_aggregator_forwards_deadline_controls_to_unstop(monkeypatch) -> None:
    class _DeadlineAwareUnstop(UnstopAdapter):
        instance = None

        def __init__(self) -> None:
            self._last_health = "ok"
            self._stopped_early = False
            type(self).instance = self

        def fetch(self, *, deadline_monotonic=None, should_stop=None) -> list[RawListing]:
            self.received_deadline = deadline_monotonic
            self.received_should_stop = should_stop
            self._stopped_early = True
            return [_raw_listing("one")]

        def parse(self, raw: RawListing) -> NormalizedListing:
            return NormalizedListing(
                source_slug=raw.source_slug,
                external_id=raw.external_id,
                source_url=raw.source_url,
                title="Role one",
                company_name="Example Company",
                description_raw="description",
                apply_url=raw.source_url,
            )

    session = _MemorySession()
    source = SimpleNamespace(id=1, crawl_tier=1)
    deadline = runner.time.monotonic() + 60.0

    monkeypatch.setattr(runner, "load_board_state", lambda *_args: object())
    monkeypatch.setattr(runner, "resolve_company", lambda *_args: SimpleNamespace(id=2))
    monkeypatch.setattr(
        runner,
        "ingest_one",
        lambda *_args, seen_opportunity_ids=None: (object(), True),
    )

    result = runner.crawl_aggregator(
        session,
        source,
        _DeadlineAwareUnstop,
        deadline_monotonic=deadline,
        should_stop=lambda: False,
    )

    adapter = _DeadlineAwareUnstop.instance
    assert adapter.received_deadline == deadline
    assert adapter.received_should_stop() is False
    assert result["status"] == "partial"
    assert result["new_opps"] == 1


def _run_tier_ats_scaffold(monkeypatch, companies, source_states, crawl_order):
    """Shared harness: run_tier(group='ats') with prefetch + DB mocked out so
    only run_tier's own time.monotonic calls are observable."""
    source = SimpleNamespace(id=1, adapter_key="order-test")

    class _Result:
        def __init__(self, values):
            self.values = values

        def all(self):
            return self.values

    class _GatherSession:
        def __init__(self):
            self.calls = 0

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def scalars(self, query):
            try:
                if query.column_descriptions[0]["entity"].__name__ == "SourceState":
                    return _Result(list(source_states))
            except (AttributeError, IndexError, KeyError, TypeError):
                pass
            self.calls += 1
            return _Result([source] if self.calls == 1 else companies)

    class _IngestSession:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def get(self, _model, _sid):
            return source

        def scalar(self, _query):
            return companies[0]

        def rollback(self):
            pass

    class _Factory:
        def __init__(self):
            self.sessions = []

        def __call__(self, _engine, **_kwargs):
            s = _GatherSession() if not self.sessions else _IngestSession()
            self.sessions.append(s)
            return s

    by_slug = {c.slug: c for c in companies}
    prefetched = {
        c.slug: runner._PrefetchedBoard(listings=[_raw_listing(c.slug)], health="ok")
        for c in companies
    }

    def fake_crawl(_session, _source, _company, _adapter_class, **kwargs):
        # Record from the prefetched listing (keyed per job/board), not the
        # company object - the simplified fake session returns companies[0] for
        # every scalar() lookup, so company identity there is not per-job.
        crawl_order.append(kwargs["prefetched"][0].external_id)
        return {}

    monkeypatch.setitem(runner.ATS_ADAPTERS, "order-test", object)
    monkeypatch.setattr(runner, "make_engine", lambda: object())
    monkeypatch.setattr(runner, "verify_connection_guards", lambda _e: None)
    monkeypatch.setattr(runner, "Session", _Factory())
    monkeypatch.setattr(runner, "_prefetch_ats_boards", lambda jobs, should_stop=None: prefetched)
    monkeypatch.setattr(
        runner,
        "crawl_company_board",
        lambda s, src, company, ac, **kw: fake_crawl(s, src, company, ac, **kw),
    )
    monkeypatch.setattr(runner, "resolve_company", lambda *_a, **_k: SimpleNamespace(id=2))
    return by_slug


def test_run_tier_ats_stops_cleanly_at_time_budget(monkeypatch) -> None:
    # Descending ids so the never-crawled tie-break (-company_id) preserves
    # list order; this test is about the time budget, not about ordering.
    companies = [
        SimpleNamespace(id=3, slug="c1", name="C1", ats_board_id="c1"),
        SimpleNamespace(id=2, slug="c2", name="C2", ats_board_id="c2"),
        SimpleNamespace(id=1, slug="c3", name="C3", ats_board_id="c3"),
    ]
    crawl_order: list[str] = []
    _run_tier_ats_scaffold(monkeypatch, companies, [], crawl_order)
    # ATS deadline setup -> 0.0 (=> deadline 50); iter1 check 1.0 (<50, process
    # c1); iter2 check 100.0 (>=50, break); 4th value = the aggregator deadline
    # setup that still runs for a group='ats' run (empty aggregator loop).
    monkeypatch.setattr(runner.time, "monotonic", iter([0.0, 1.0, 100.0, 200.0]).__next__)

    runner.run_tier(1, group="ats", ats_max_seconds=50.0)  # must NOT raise

    assert crawl_order == ["c1"]  # stopped cleanly after the budget, not all 3


def test_run_tier_ats_crawls_stalest_boards_first(monkeypatch) -> None:
    from datetime import datetime, timezone

    # Ids are irrelevant here: all three have DISTINCT primary staleness keys,
    # so -company_id is never reached.
    companies = [
        SimpleNamespace(id=1, slug="fresh", name="Fresh", ats_board_id="fresh"),
        SimpleNamespace(id=2, slug="never", name="Never", ats_board_id="never"),
        SimpleNamespace(id=3, slug="old", name="Old", ats_board_id="old"),
    ]
    # fresh crawled today, old crawled long ago, never has no SourceState row.
    states = [
        SimpleNamespace(
            source_id=1,
            page_key="fresh",
            last_crawled_at=datetime(2026, 7, 18, tzinfo=timezone.utc),
        ),
        SimpleNamespace(
            source_id=1, page_key="old", last_crawled_at=datetime(2026, 7, 1, tzinfo=timezone.utc)
        ),
    ]
    crawl_order: list[str] = []
    _run_tier_ats_scaffold(monkeypatch, companies, states, crawl_order)

    runner.run_tier(1, group="ats", ats_max_seconds=10_000.0)  # big budget: all run

    # never-crawled first, then oldest, then freshest.
    assert crawl_order == ["never", "old", "fresh"]
