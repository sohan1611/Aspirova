"""Unit coverage for crawler prefetching and graceful soft stops."""

import io
import threading
import time
from types import SimpleNamespace

import pytest

from core import models
from core.adapters import NormalizedListing, RawListing
from crawlers.common import build_http_timeout
from crawlers import runner
from crawlers.unstop import UnstopAdapter
from crawlers.watchdog import CrawlWatchdog
from pipeline.ingest import RAW_LISTING_EXTERNAL_ID_CHUNK_SIZE, load_source_raw_listings


def _raw_listing(external_id: str) -> RawListing:
    return RawListing(
        source_slug="greenhouse",
        external_id=external_id,
        source_url=f"https://example.test/{external_id}",
        content_hash=f"hash-{external_id}",
        raw_payload={"id": external_id},
    )


def _db_raw_listing(source_id: int, external_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=f"{source_id}:{external_id}",
        source_id=source_id,
        external_id=external_id,
    )


class _ScalarResult:
    """The `.all()` surface of a SQLAlchemy ScalarResult, nothing more."""

    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return list(self._rows)

    def unique(self) -> "_ScalarResult":
        return self

    def __iter__(self):
        return iter(self._rows)


class _MemorySession:
    """Only the Session surface exercised by the runner unit tests."""

    def __init__(self) -> None:
        self.added: list[object] = []
        self.commits = 0
        self.rollbacks = 0
        self.ingested: list[str] = []
        self.scalar_result = None
        self.scalars_result: list[object] = []

    def scalar(self, _query):
        return self.scalar_result

    def scalars(self, _query):
        # crawl_company_board now loads board-scoped raw listings itself, so the
        # fake needs this surface. These tests seed no raw_listings rows, so an
        # empty result is the honest answer - it is not a stub for a real query.
        return _ScalarResult(self.scalars_result)

    def add(self, value: object) -> None:
        self.added.append(value)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class _ScalarRows:
    def __init__(self, values: list[object]) -> None:
        self.values = values

    def all(self) -> list[object]:
        return self.values


def _query_entity_name(query) -> str | None:
    try:
        entity = query.column_descriptions[0]["entity"]
    except (AttributeError, IndexError, KeyError, TypeError):
        return None
    return getattr(entity, "__name__", None)


def _query_source_id(query) -> int | None:
    for key, value in query.compile().params.items():
        if key.startswith("source_id"):
            return value
    return None


def _query_external_ids(query) -> tuple[str, ...] | None:
    batches = [
        tuple(value)
        for key, value in query.compile().params.items()
        if key.startswith("external_id") and isinstance(value, (list, tuple, set))
    ]
    assert len(batches) <= 1
    return batches[0] if batches else None


def _query_sql(query) -> str:
    return str(query.compile(compile_kwargs={"render_postcompile": True}))


class _CountingRawListingSession(_MemorySession):
    def __init__(self, raw_rows: list[object] | None = None) -> None:
        super().__init__()
        self.raw_rows = raw_rows or []
        self.raw_listing_queries = 0
        self.opportunity_queries = 0
        self.provenance_queries = 0
        self.raw_listing_external_id_filters: list[tuple[str, ...] | None] = []
        self.raw_listing_sql: list[str] = []
        self.raw_listing_rows_loaded = 0

    def scalars(self, query) -> _ScalarRows:
        entity_name = _query_entity_name(query)
        if entity_name == "RawListing":
            source_id = _query_source_id(query)
            external_ids = _query_external_ids(query)
            sql = _query_sql(query)
            self.raw_listing_queries += 1
            self.raw_listing_external_id_filters.append(external_ids)
            self.raw_listing_sql.append(sql)
            rows = [raw for raw in self.raw_rows if source_id is None or raw.source_id == source_id]
            if external_ids is not None:
                allowed_external_ids = set(external_ids)
                rows = [raw for raw in rows if raw.external_id in allowed_external_ids]
            self.raw_listing_rows_loaded += len(rows)
            return _ScalarRows(rows)
        if entity_name == "Opportunity":
            self.opportunity_queries += 1
            return _ScalarRows([])
        if entity_name == "OpportunitySource":
            self.provenance_queries += 1
            return _ScalarRows([])
        raise AssertionError(f"unexpected scalar query for {entity_name}")


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
        session,
        _board_state,
        _source_id,
        _company_id,
        raw,
        _normalized,
        seen_opportunity_ids=None,
        changed_slugs=None,
    ):
        session.ingested.append(raw.external_id)
        return object(), True

    monkeypatch.setattr(runner, "load_board_state", lambda *_args: object())
    monkeypatch.setattr(runner, "load_source_raw_listings", lambda *_args, **_kwargs: {})
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


def test_load_source_raw_listings_without_external_ids_keeps_full_source_scan() -> None:
    session = _CountingRawListingSession(
        [
            _db_raw_listing(1, "board-a"),
            _db_raw_listing(1, "off-board"),
            _db_raw_listing(2, "other-source"),
        ]
    )

    raw_by_external_id = load_source_raw_listings(session, 1)

    assert set(raw_by_external_id) == {"board-a", "off-board"}
    assert session.raw_listing_external_id_filters == [None]
    assert "raw_listings.source_id" in session.raw_listing_sql[0]
    assert "raw_listings.external_id IN" not in session.raw_listing_sql[0]


def test_load_source_raw_listings_chunks_scoped_external_ids() -> None:
    board_external_ids = [
        f"board-{index}" for index in range(RAW_LISTING_EXTERNAL_ID_CHUNK_SIZE + 7)
    ]
    session = _CountingRawListingSession(
        [_db_raw_listing(1, external_id) for external_id in board_external_ids]
        + [
            _db_raw_listing(1, "off-board"),
            _db_raw_listing(2, board_external_ids[0]),
        ]
    )

    raw_by_external_id = load_source_raw_listings(
        session,
        1,
        external_ids=board_external_ids,
    )

    assert set(raw_by_external_id) == set(board_external_ids)
    assert "off-board" not in raw_by_external_id
    assert session.raw_listing_rows_loaded == len(board_external_ids)
    assert [len(batch or ()) for batch in session.raw_listing_external_id_filters] == [
        RAW_LISTING_EXTERNAL_ID_CHUNK_SIZE,
        7,
    ]
    loaded_filter_ids: set[str] = set()
    for batch in session.raw_listing_external_id_filters:
        assert batch is not None
        loaded_filter_ids.update(batch)
    assert loaded_filter_ids == set(board_external_ids)
    assert all("raw_listings.external_id IN" in sql for sql in session.raw_listing_sql)


def test_crawl_company_board_scopes_raw_listing_query_to_board_external_ids(
    monkeypatch,
) -> None:
    board_listings = [_raw_listing("board-a"), _raw_listing("board-b")]
    session = _CountingRawListingSession(
        [
            _db_raw_listing(1, "board-a"),
            _db_raw_listing(1, "board-b"),
            _db_raw_listing(1, "off-board"),
            _db_raw_listing(2, "board-a"),
        ]
    )
    source = SimpleNamespace(id=1, crawl_tier=1, adapter_key="greenhouse")
    company = SimpleNamespace(
        id=2,
        slug="example-company",
        name="Example Company",
        ats_board_id="example-board",
    )

    def fake_ingest(
        _session,
        board_state,
        _source_id,
        _company_id,
        _raw,
        _normalized,
        seen_opportunity_ids=None,
        changed_slugs=None,
    ):
        assert set(board_state.raw_by_external_id) == {"board-a", "board-b"}
        assert "off-board" not in board_state.raw_by_external_id
        return object(), True

    monkeypatch.setattr(runner, "ingest_one", fake_ingest)

    result = runner.crawl_company_board(
        session,
        source,
        company,
        _BoardAdapter,
        prefetched=board_listings,
        prefetched_health="ok",
    )

    assert result["status"] == "success"
    assert session.raw_listing_external_id_filters == [("board-a", "board-b")]
    assert "raw_listings.external_id IN" in session.raw_listing_sql[0]
    assert session.raw_listing_rows_loaded == 2


def test_crawl_company_board_rollback_reloads_scoped_raw_listing_query(
    monkeypatch,
) -> None:
    board_listings = [_raw_listing("first"), _raw_listing("second")]
    session = _CountingRawListingSession(
        [
            _db_raw_listing(1, "first"),
            _db_raw_listing(1, "second"),
            _db_raw_listing(1, "off-board"),
        ]
    )
    source = SimpleNamespace(id=1, crawl_tier=1, adapter_key="greenhouse")
    company = SimpleNamespace(
        id=2,
        slug="example-company",
        name="Example Company",
        ats_board_id="example-board",
    )

    def fake_ingest(
        _session,
        board_state,
        _source_id,
        _company_id,
        raw,
        _normalized,
        seen_opportunity_ids=None,
        changed_slugs=None,
    ):
        assert set(board_state.raw_by_external_id) == {"first", "second"}
        assert "off-board" not in board_state.raw_by_external_id
        if raw.external_id == "first":
            raise RuntimeError("forced rollback")
        return object(), True

    monkeypatch.setattr(runner, "ingest_one", fake_ingest)

    result = runner.crawl_company_board(
        session,
        source,
        company,
        _BoardAdapter,
        prefetched=board_listings,
        prefetched_health="ok",
    )

    assert result["status"] == "partial"
    assert result["errors"] == 1
    assert session.rollbacks == 1
    assert session.raw_listing_external_id_filters == [
        ("first", "second"),
        ("first", "second"),
    ]
    assert all("raw_listings.external_id IN" in sql for sql in session.raw_listing_sql)
    assert session.raw_listing_rows_loaded == 4


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


def test_zero_listing_board_with_previous_listings_is_retried_once(monkeypatch) -> None:
    fetch_calls = 0

    class _ZeroAfterPreviousAdapter:
        source_slug = "greenhouse"

        def __init__(self, board_token: str, company_name: str) -> None:
            self.board_token = board_token
            self.company_name = company_name

        def fetch(self) -> list[RawListing]:
            nonlocal fetch_calls
            fetch_calls += 1
            return []

        def health(self) -> str:
            return "ok"

    monkeypatch.setitem(runner.ATS_ADAPTERS, "zero-retry-test", _ZeroAfterPreviousAdapter)
    job = runner._AtsJob(
        company_id=1,
        source_id=1,
        company_slug="flexport",
        adapter_key="zero-retry-test",
        board_token="flexport",
        company_name="Flexport",
        previously_had_listings=True,
    )

    board = runner._fetch_company_board(job)

    assert fetch_calls == 2
    assert board is not None
    assert board.listings == []
    assert board.coverage["status"] == "partial"
    assert board.coverage["details"]["incomplete_boards"] == ["flexport"]


def test_zero_listing_board_that_has_always_been_empty_is_not_retried(monkeypatch) -> None:
    fetch_calls = 0

    class _AlwaysEmptyAdapter:
        source_slug = "greenhouse"

        def __init__(self, board_token: str, company_name: str) -> None:
            self.board_token = board_token
            self.company_name = company_name

        def fetch(self) -> list[RawListing]:
            nonlocal fetch_calls
            fetch_calls += 1
            return []

        def health(self) -> str:
            return "ok"

    monkeypatch.setitem(runner.ATS_ADAPTERS, "always-empty-test", _AlwaysEmptyAdapter)
    job = runner._AtsJob(
        company_id=1,
        source_id=1,
        company_slug="empty-board",
        adapter_key="always-empty-test",
        board_token="empty-board",
        company_name="Empty Board",
    )

    board = runner._fetch_company_board(job)

    assert fetch_calls == 1
    assert board is not None
    assert board.listings == []
    assert board.coverage["status"] == "complete"
    assert board.coverage["details"]["boards_complete"] == 1


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
    monkeypatch.setattr(runner, "_refresh_prestige_matches", lambda _engine: None)

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


class _MultiCompanyAggregator:
    companies_by_listing = ["Company A", "Company B", "Company C", "Company A"]

    def fetch(self) -> list[RawListing]:
        return [
            RawListing(
                source_slug="aggregator-test",
                external_id=f"listing-{index}",
                source_url=f"https://example.test/listing-{index}",
                content_hash=f"hash-{index}",
                raw_payload={"company_name": company_name},
            )
            for index, company_name in enumerate(self.companies_by_listing, start=1)
        ]

    def parse(self, raw: RawListing) -> NormalizedListing:
        return NormalizedListing(
            source_slug=raw.source_slug,
            external_id=raw.external_id,
            source_url=raw.source_url,
            title=f"Role {raw.external_id}",
            company_name=raw.raw_payload["company_name"],
            description_raw="description",
            apply_url=raw.source_url,
        )

    def health(self) -> str:
        return "ok"


def _company_for_name(company_name: str) -> SimpleNamespace:
    company_ids = {"Company A": 101, "Company B": 202, "Company C": 303}
    return SimpleNamespace(id=company_ids[company_name])


def test_aggregator_loads_source_raw_listings_once_for_multi_company_batch(monkeypatch) -> None:
    session = _CountingRawListingSession()
    source = SimpleNamespace(id=1, crawl_tier=1, adapter_key="aggregator-test")

    monkeypatch.setattr(
        runner, "resolve_company", lambda _session, name, _domain: _company_for_name(name)
    )
    monkeypatch.setattr(
        runner,
        "ingest_one",
        lambda *_args, seen_opportunity_ids=None, changed_slugs=None: (object(), True),
    )

    result = runner.crawl_aggregator(session, source, _MultiCompanyAggregator)

    assert result["status"] == "success"
    assert result["listings_found"] == 4
    assert session.raw_listing_queries == 1
    assert session.opportunity_queries == 3


def test_aggregator_new_raw_listing_is_visible_across_company_states(monkeypatch) -> None:
    class _TwoCompanyAggregator(_MultiCompanyAggregator):
        companies_by_listing = ["Company A", "Company B"]

    session = _CountingRawListingSession()
    source = SimpleNamespace(id=1, crawl_tier=1, adapter_key="aggregator-test")
    seen_shared_raw = []

    def fake_ingest(
        _session,
        board_state,
        _source_id,
        _company_id,
        raw,
        _normalized,
        seen_opportunity_ids=None,
        changed_slugs=None,
    ):
        if raw.external_id == "listing-1":
            board_state.raw_by_external_id[raw.external_id] = SimpleNamespace(
                external_id=raw.external_id
            )
        else:
            seen_shared_raw.append(board_state.raw_by_external_id.get("listing-1"))
        return object(), True

    monkeypatch.setattr(
        runner, "resolve_company", lambda _session, name, _domain: _company_for_name(name)
    )
    monkeypatch.setattr(runner, "ingest_one", fake_ingest)

    result = runner.crawl_aggregator(session, source, _TwoCompanyAggregator)

    assert result["status"] == "success"
    assert session.raw_listing_queries == 1
    assert seen_shared_raw and seen_shared_raw[0].external_id == "listing-1"


def test_aggregator_reloads_shared_raw_listing_map_after_rollback(monkeypatch) -> None:
    class _TwoListingAggregator(_MultiCompanyAggregator):
        companies_by_listing = ["Company A", "Company A"]

    session = _CountingRawListingSession()
    source = SimpleNamespace(id=1, crawl_tier=1, adapter_key="aggregator-test")
    raw_maps = []

    def fake_ingest(
        _session,
        board_state,
        _source_id,
        _company_id,
        raw,
        _normalized,
        seen_opportunity_ids=None,
        changed_slugs=None,
    ):
        raw_maps.append(board_state.raw_by_external_id)
        if raw.external_id == "listing-1":
            board_state.raw_by_external_id["rolled-back"] = SimpleNamespace()
            raise RuntimeError("forced rollback")
        assert "rolled-back" not in board_state.raw_by_external_id
        return object(), True

    monkeypatch.setattr(
        runner, "resolve_company", lambda _session, name, _domain: _company_for_name(name)
    )
    monkeypatch.setattr(runner, "ingest_one", fake_ingest)

    result = runner.crawl_aggregator(session, source, _TwoListingAggregator)

    assert result["status"] == "partial"
    assert result["errors"] == 1
    assert session.rollbacks == 1
    assert session.raw_listing_queries == 2
    assert raw_maps[0] is not raw_maps[1]


def test_ats_path_still_loads_board_state_per_board(monkeypatch) -> None:
    source = SimpleNamespace(id=1, crawl_tier=1, adapter_key="greenhouse")
    companies = [
        SimpleNamespace(
            id=101,
            slug="company-a",
            name="Company A",
            ats_board_id="board-a",
        ),
        SimpleNamespace(
            id=202,
            slug="company-b",
            name="Company B",
            ats_board_id="board-b",
        ),
    ]
    raw_load_calls: list[tuple[int, int, tuple[str, ...], int]] = []
    board_state_calls: list[tuple[int, int, int, tuple[str, ...], int]] = []

    def fake_source_raw_loader(session, source_id, *, external_ids=None):
        raw_map = {
            external_id: SimpleNamespace(external_id=external_id)
            for external_id in external_ids or []
        }
        raw_load_calls.append(
            (
                id(session),
                source_id,
                tuple(external_ids or ()),
                id(raw_map),
            )
        )
        return raw_map

    def fake_load_board_state(session, source_id, company_id, raw_by_external_id):
        # Hold the objects, not id(). id() is a memory address that CPython
        # reuses once an object becomes unreachable, and each loop iteration
        # drops its session before the next is created - so two genuinely
        # distinct sessions can report the same id and the assertion below
        # would fail against correct code.
        board_state_calls.append(
            (
                session,
                source_id,
                company_id,
                tuple(raw_by_external_id),
                raw_by_external_id,
            )
        )
        return object()

    def fake_ingest(
        _session,
        _board_state,
        _source_id,
        _company_id,
        _raw,
        _normalized,
        seen_opportunity_ids=None,
        changed_slugs=None,
    ):
        return object(), True

    monkeypatch.setattr(runner, "load_source_raw_listings", fake_source_raw_loader)
    monkeypatch.setattr(runner, "load_board_state", fake_load_board_state)
    monkeypatch.setattr(runner, "ingest_one", fake_ingest)
    _BoardAdapter.listings = [_raw_listing("one")]

    sessions: list[_MemorySession] = []
    for company in companies:
        session = _MemorySession()
        sessions.append(session)
        runner.crawl_company_board(session, source, company, _BoardAdapter)

    assert [(source_id, company_id) for _, source_id, company_id, _, _ in board_state_calls] == [
        (1, 101),
        (1, 202),
    ]
    assert [external_ids for _, _, external_ids, _ in raw_load_calls] == [
        ("one",),
        ("one",),
    ]
    assert [external_ids for _, _, _, external_ids, _ in board_state_calls] == [
        ("one",),
        ("one",),
    ]
    assert board_state_calls[0][0] is not board_state_calls[1][0]
    assert board_state_calls[0][4] is not board_state_calls[1][4]


def test_bounded_by_design_aggregator_records_success_outcome(monkeypatch) -> None:
    class _BoundedWindowAggregator(_AggregatorAdapter):
        def coverage(self) -> dict[str, object]:
            return {
                "mode": "bounded_window",
                "expected_total": None,
                "status": "complete",
                "note": "bounded by design to the most recent Himalayas jobs window",
                "details": {
                    "raw_count": 3,
                    "student_relevant_count": 3,
                    "filtered_out": 0,
                    "catalogue_total": 101767,
                    "request_cap": 250,
                    "page_size_requested": 20,
                    "requests_made": 1,
                    "bounded_by_design": True,
                    "hit_request_cap": False,
                    "terminal_reason": "short_page",
                    "terminal_offset": 0,
                    "window_raw_fetched": 3,
                    "window_raw_expected": 3,
                },
            }

    session = _MemorySession()
    source = SimpleNamespace(id=1, crawl_tier=1, adapter_key="himalayas")

    monkeypatch.setattr(runner, "load_source_raw_listings", lambda *_args: {})
    monkeypatch.setattr(runner, "load_board_state", lambda *_args: object())
    monkeypatch.setattr(runner, "resolve_company", lambda *_args: SimpleNamespace(id=2))
    monkeypatch.setattr(
        runner,
        "ingest_one",
        lambda *_args, seen_opportunity_ids=None, changed_slugs=None: (object(), True),
    )

    result = runner.crawl_aggregator(session, source, _BoundedWindowAggregator)

    assert result["status"] == "success"
    assert result["coverage"]["mode"] == "bounded_window"
    assert result["coverage"]["status"] == "complete"
    crawl_runs = [value for value in session.added if isinstance(value, models.CrawlRun)]
    assert crawl_runs[-1].status == "success"
    assert crawl_runs[-1].log["coverage_status"] == "complete"


def test_aggregator_deadline_commits_completed_work_and_returns_partial(monkeypatch) -> None:
    session = _MemorySession()
    source = SimpleNamespace(id=1, crawl_tier=1)
    previous_state = SimpleNamespace(
        last_content_hash="full-feed-fingerprint",
        last_crawled_at="before-partial-run",
    )
    session.scalar_result = previous_state

    def fake_ingest(
        _session,
        _board_state,
        _source_id,
        _company_id,
        raw,
        _normalized,
        seen_opportunity_ids=None,
        changed_slugs=None,
    ):
        session.ingested.append(raw.external_id)
        return object(), True

    def fake_monotonic() -> float:
        # The deadline begins at 10. Once the first listing has been
        # ingested, the next loop check crosses it and triggers a clean stop.
        return 11.0 if session.ingested else 0.0

    monkeypatch.setattr(runner, "load_source_raw_listings", lambda *_args: {})
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

    assert result == {
        "listings_found": 3,
        "new_opps": 1,
        "errors": 0,
        "status": "partial",
        "changed_slugs": 0,
        "stopped_early": True,
        "coverage": {
            "fetched": 3,
            "expected_total": None,
            "mode": "unknown",
            "status": "unknown",
            "note": "source declares no total",
        },
        "truncation_elapsed_seconds": 11.0,
        "truncation_budget_seconds": 10.0,
    }
    assert session.ingested == ["one"]
    assert session.commits >= 3  # trailing batch, final state, and CrawlRun
    crawl_runs = [value for value in session.added if isinstance(value, models.CrawlRun)]
    assert [crawl_run.status for crawl_run in crawl_runs] == ["partial"]
    assert not any(isinstance(value, models.SourceState) for value in session.added)
    assert previous_state.last_content_hash == "full-feed-fingerprint"
    assert previous_state.last_crawled_at == "before-partial-run"


@pytest.mark.parametrize("health", ["degraded", "broken"])
def test_errored_aggregator_fetch_records_partial_outcome(monkeypatch, health: str) -> None:
    class _DegradedFetchAggregator:
        def fetch(self) -> list[RawListing]:
            return []

        def parse(self, raw: RawListing) -> NormalizedListing:
            raise AssertionError(f"parse should not be called for {raw.external_id}")

        def health(self) -> str:
            return health

        def coverage(self) -> dict[str, object]:
            return {
                "mode": "bounded_window",
                "expected_total": None,
                "status": "partial",
                "note": "bounded by design; fetch ended with http_503",
                "details": {
                    "raw_count": 0,
                    "student_relevant_count": 0,
                    "filtered_out": 0,
                    "request_cap": 250,
                    "page_size_requested": 20,
                    "requests_made": 1,
                    "bounded_by_design": True,
                    "hit_request_cap": False,
                    "terminal_reason": "http_503",
                    "terminal_offset": 0,
                    "window_raw_fetched": 0,
                    "window_raw_expected": 5000,
                },
            }

    session = _MemorySession()
    source = SimpleNamespace(id=1, crawl_tier=1, adapter_key="himalayas")

    result = runner.crawl_aggregator(session, source, _DegradedFetchAggregator)

    assert result["status"] == "partial"
    assert result["stopped_early"] is False
    assert result["coverage"]["status"] == "partial"
    crawl_runs = [value for value in session.added if isinstance(value, models.CrawlRun)]
    assert crawl_runs[-1].status == "partial"
    assert not any(isinstance(value, models.SourceState) for value in session.added)


def test_coverage_unknown_for_source_without_declared_total(monkeypatch, capsys) -> None:
    class _NoTotalAggregator:
        def fetch(self) -> list[RawListing]:
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

        def health(self) -> str:
            return "ok"

    session = _MemorySession()
    source = SimpleNamespace(id=1, crawl_tier=1, adapter_key="no-total")

    monkeypatch.setattr(runner, "load_source_raw_listings", lambda *_args: {})
    monkeypatch.setattr(runner, "load_board_state", lambda *_args: object())
    monkeypatch.setattr(runner, "resolve_company", lambda *_args: SimpleNamespace(id=2))
    monkeypatch.setattr(
        runner,
        "ingest_one",
        lambda *_args, seen_opportunity_ids=None, changed_slugs=None: (object(), True),
    )

    result = runner.crawl_aggregator(session, source, _NoTotalAggregator)

    assert result["coverage"] == {
        "fetched": 1,
        "expected_total": None,
        "mode": "unknown",
        "status": "unknown",
        "note": "source declares no total",
    }
    crawl_runs = [value for value in session.added if isinstance(value, models.CrawlRun)]
    assert crawl_runs[-1].log["coverage_status"] == "unknown"
    assert crawl_runs[-1].log["coverage_expected_total"] is None
    assert crawl_runs[-1].log["coverage"]["note"] == "source declares no total"

    runner._print_coverage_summary({"no-total": [result["coverage"]]})

    assert "COVERAGE: no-total 1/? (UNKNOWN - source declares no total)" in capsys.readouterr().out


def test_aggregator_forwards_deadline_controls_to_unstop(monkeypatch, capsys) -> None:
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
    deadline = 160.0

    monkeypatch.setattr(runner, "load_source_raw_listings", lambda *_args: {})
    monkeypatch.setattr(runner, "load_board_state", lambda *_args: object())
    monkeypatch.setattr(runner, "resolve_company", lambda *_args: SimpleNamespace(id=2))
    monkeypatch.setattr(
        runner,
        "ingest_one",
        lambda *_args, seen_opportunity_ids=None, changed_slugs=None: (object(), True),
    )
    monkeypatch.setattr(
        runner.time,
        "monotonic",
        iter([100.0, 100.0, 100.0, 100.0, 105.0, 100.0]).__next__,
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
    assert result["stopped_early"] is True
    assert result["truncation_elapsed_seconds"] == 5.0
    assert result["truncation_budget_seconds"] == 60.0
    assert "TRUNCATED: unstop stopped early after 5.0s (budget 60.0s)" in capsys.readouterr().out


class _FakeClock:
    def __init__(self, value: float = 0.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def test_watchdog_steady_beats_never_trigger_false_hang() -> None:
    clock = _FakeClock()
    output = io.StringIO()
    soft_calls: list[float] = []
    hard_calls: list[float] = []
    watchdog = CrawlWatchdog(
        hang_after_seconds=10.0,
        hard_after_seconds=5.0,
        on_soft_hang=lambda: soft_calls.append(clock.value),
        hard_exit=lambda: hard_calls.append(clock.value),
        clock=clock,
        output=output,
    )
    watchdog.beat("greenhouse:stripe")

    for index in range(5):
        clock.value += 9.0
        watchdog.check_once()
        watchdog.beat(f"greenhouse:stripe:batch-{index}")

    assert soft_calls == []
    assert hard_calls == []
    assert output.getvalue() == ""


def test_watchdog_silence_past_soft_threshold_requests_graceful_stop() -> None:
    clock = _FakeClock()
    output = io.StringIO()
    soft_calls: list[float] = []
    hard_calls: list[float] = []
    watchdog = CrawlWatchdog(
        hang_after_seconds=10.0,
        hard_after_seconds=5.0,
        on_soft_hang=lambda: soft_calls.append(clock.value),
        hard_exit=lambda: hard_calls.append(clock.value),
        clock=clock,
        output=output,
    )
    watchdog.beat("greenhouse:stripe")

    clock.value = 11.0
    watchdog.check_once()

    assert soft_calls == [11.0]
    assert hard_calls == []
    assert "HUNG: no progress for 11s; last activity was greenhouse:stripe" in output.getvalue()


def test_watchdog_continued_silence_past_hard_threshold_exits() -> None:
    clock = _FakeClock()
    output = io.StringIO()
    soft_calls: list[float] = []
    hard_calls: list[float] = []
    watchdog = CrawlWatchdog(
        hang_after_seconds=10.0,
        hard_after_seconds=5.0,
        on_soft_hang=lambda: soft_calls.append(clock.value),
        hard_exit=lambda: hard_calls.append(clock.value),
        clock=clock,
        output=output,
    )
    watchdog.beat("greenhouse:stripe")

    clock.value = 11.0
    watchdog.check_once()
    clock.value = 16.0
    watchdog.check_once()

    assert soft_calls == [11.0]
    assert hard_calls == [16.0]
    assert "HUNG: hard exit after 16s without progress; last activity was greenhouse:stripe" in (
        output.getvalue()
    )


def test_http_timeout_sets_connect_and_read_limits() -> None:
    timeout = build_http_timeout(7.0)

    assert timeout.connect == 7.0
    assert timeout.read == 7.0


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
    monkeypatch.setattr(runner, "_refresh_prestige_matches", lambda _engine: None)
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


def test_a_failed_source_records_why_it_failed(monkeypatch) -> None:
    """Regression for crawl 32183933552.

    himalayas, mongodb and vercel all reported `errors: 1, status: failed`
    with COMPLETE coverage and no cause recorded anywhere - the outer handler
    was a bare `except Exception:` that discarded the exception. A failure you
    cannot diagnose is the same blindness the coverage work exists to remove.
    """

    class _ExplodingAggregator:
        source_slug = "exploder"

        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def fetch(self) -> list:
            raise RuntimeError("boom: simulated source failure")

        def health(self) -> str:
            return "ok"

        def coverage(self) -> dict[str, object]:
            return {
                "fetched": 0,
                "expected_total": None,
                "mode": "unknown",
                "status": "unknown",
            }

    session = _MemorySession()
    source = SimpleNamespace(id=1, crawl_tier=1, adapter_key="himalayas")

    recorded: dict = {}

    def fake_record(_session, **kwargs):
        recorded.update(kwargs)

    monkeypatch.setattr(runner, "load_board_state", lambda *_args: object())
    monkeypatch.setattr(runner, "resolve_company", lambda *_args: SimpleNamespace(id=2))
    monkeypatch.setattr(runner, "_record_crawl_run", fake_record)

    result = runner.crawl_aggregator(session, source, _ExplodingAggregator)

    assert result["status"] == "failed"
    assert result["errors"] >= 1
    # The cause must survive in the result AND in the durable crawl_runs log,
    # because CI workflow logs age out and crawl_runs does not.
    assert "RuntimeError" in result["failure_reason"]
    assert "boom: simulated source failure" in result["failure_reason"]
    assert "boom: simulated source failure" in recorded["log"]["failure_reason"]


def test_no_transaction_is_held_open_across_the_aggregator_fetch(monkeypatch) -> None:
    """Regression for crawl 32193971487.

    The caller opens a Session and reads `Source`, starting a read-only
    transaction. A paced aggregator then fetches for many minutes (himalayas
    is ~750s) with that transaction IDLE, far past the 120s
    idle_in_transaction_session_timeout in core/db.py. Postgres terminated the
    connection and the first query after the fetch died:

        IdleInTransactionSessionTimeout: terminating connection due to
        idle-in-transaction timeout
        [SQL: SELECT source_state ... page_key = 'aggregator']

    All 71 student-relevant himalayas listings were lost that way - fetched
    cleanly, coverage complete, ingested zero.
    """

    class _SlowFetchAggregator:
        source_slug = "slowpoke"

        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def fetch(self) -> list:
            # The transaction must already be closed by the time a slow fetch
            # starts - that is the whole point.
            assert session.commits >= 1, "a transaction was still open across the fetch"
            return []

        def health(self) -> str:
            return "ok"

        def coverage(self) -> dict[str, object]:
            return {
                "fetched": 0,
                "expected_total": None,
                "mode": "unknown",
                "status": "unknown",
            }

    session = _MemorySession()
    source = SimpleNamespace(id=1, crawl_tier=1, adapter_key="himalayas")

    monkeypatch.setattr(runner, "load_board_state", lambda *_args: object())
    monkeypatch.setattr(runner, "resolve_company", lambda *_args: SimpleNamespace(id=2))
    monkeypatch.setattr(runner, "_record_crawl_run", lambda _session, **_kwargs: None)

    result = runner.crawl_aggregator(session, source, _SlowFetchAggregator)

    # The assert inside fetch() would have surfaced as a failed run.
    assert result["status"] != "failed", result.get("failure_reason")


def test_aggregator_stamps_last_seen_at_in_bulk_not_once_per_listing(monkeypatch) -> None:
    """Regression for a live N+1 write.

    ingest_one falls back to `opportunity.last_seen_at = func.now()` per
    listing whenever `seen_opportunity_ids` is not supplied. crawl_company_board
    supplied it ("Lever 1"); crawl_aggregator did not, so every aggregator
    listing cost its own UPDATE round trip to Mumbai. pg_stat_statements
    recorded 147,937 single-row `UPDATE opportunities SET last_seen_at=now()
    WHERE id = $1` calls over 60 days - roughly one per aggregator listing per
    crawl.
    """

    class _ThreeListingAggregator(_AggregatorAdapter):
        listings = [_raw_listing("a"), _raw_listing("b"), _raw_listing("c")]

    session = _MemorySession()
    source = SimpleNamespace(id=1, crawl_tier=1, adapter_key="devpost")

    passed_sets: list[object] = []

    def fake_ingest(
        _session,
        _board_state,
        _source_id,
        _company_id,
        raw,
        _normalized,
        seen_opportunity_ids=None,
        changed_slugs=None,
    ):
        passed_sets.append(seen_opportunity_ids)
        # Mirror ingest_one's batched branch.
        if seen_opportunity_ids is not None:
            seen_opportunity_ids.add(hash(raw.external_id) % 10_000)
        return object(), True

    monkeypatch.setattr(runner, "load_source_raw_listings", lambda *_a, **_k: {})
    monkeypatch.setattr(runner, "load_board_state", lambda *_a, **_k: object())
    monkeypatch.setattr(runner, "resolve_company", lambda *_a: SimpleNamespace(id=2))
    monkeypatch.setattr(runner, "ingest_one", fake_ingest)
    monkeypatch.setattr(runner, "_record_crawl_run", lambda _s, **_k: None)

    runner.crawl_aggregator(session, source, _ThreeListingAggregator)

    # Every listing must receive the shared set - never None, which is the
    # per-row fallback this test exists to prevent.
    assert len(passed_sets) == 3
    assert all(
        s is not None for s in passed_sets
    ), "an aggregator listing fell back to a per-row UPDATE"
    assert len({id(s) for s in passed_sets}) == 1, "listings must share ONE set, not one each"
