"""New-source freshness/coverage guards using an in-memory session seam."""

from datetime import UTC, datetime
from types import SimpleNamespace

from core import models
from core.adapters import NormalizedListing, RawListing
from crawlers import runner
from scripts import seed_companies


class _MemorySession:
    def __init__(self, state):
        self.state = state
        self.added = []
        self.executed = []

    def scalar(self, _query):
        return self.state

    def add(self, item):
        self.added.append(item)

    def execute(self, query):
        self.executed.append(query)

    def commit(self):
        pass

    def rollback(self):
        pass


def _raw(source):
    return RawListing(
        source_slug=source,
        external_id="R123",
        source_url="https://employer.example/job/123",
        content_hash="stable",
        raw_payload={},
    )


def test_capped_workday_search_cannot_advance_source_state_even_if_prefetched_health_ok(
    monkeypatch,
):
    raw = _raw("workday")
    before = datetime(2026, 11, 1, tzinfo=UTC)
    state = SimpleNamespace(last_crawled_at=before, last_content_hash="previous")
    session = _MemorySession(state)

    class Adapter:
        def __init__(self, **_kwargs):
            pass

        def parse(self, item):
            return NormalizedListing(
                source_slug="workday",
                external_id=item.external_id,
                source_url=item.source_url,
                title="Software Intern",
                company_name="Acme",
                description_raw="Public employer description",
                apply_url=item.source_url,
            )

    monkeypatch.setattr(runner, "load_source_raw_listings", lambda *args, **kwargs: {})
    monkeypatch.setattr(runner, "load_board_state", lambda *args, **kwargs: object())
    monkeypatch.setattr(runner, "ingest_one", lambda *args, **kwargs: (object(), False))
    result = runner.crawl_company_board(
        session,
        SimpleNamespace(id=1, adapter_key="workday", crawl_tier=1),
        SimpleNamespace(id=2, slug="acme", name="Acme", ats_board_id="acme|wd5|Careers"),
        Adapter,
        prefetched=[raw],
        prefetched_health="ok",
        prefetched_coverage={
            "mode": "search",
            "status": "partial",
            "fetched": 1,
            "expected_total": None,
            "details": {"capped_terms": ["intern"]},
        },
    )
    assert result["status"] == "partial"
    assert state.last_crawled_at == before and state.last_content_hash == "previous"
    assert not any(isinstance(item, models.SourceState) for item in session.added)
    assert not session.executed
    crawl = next(item for item in session.added if isinstance(item, models.CrawlRun))
    assert crawl.log["coverage"]["status"] == "partial"


def test_unchanged_github_inventory_refreshes_only_returned_external_ids(monkeypatch):
    raw = _raw("github_lists")
    state = SimpleNamespace(
        last_content_hash=runner._board_fingerprint([raw]), last_crawled_at=None
    )
    session = _MemorySession(state)

    class Adapter:
        def fetch(self):
            return [raw]

        def health(self):
            return "ok"

        def coverage(self):
            return {"mode": "full_list", "status": "complete", "expected_total": None}

        def parse(self, _raw):
            raise AssertionError("unchanged inventory must not parse or ingest")

    result = runner.crawl_aggregator(
        session, SimpleNamespace(id=1, adapter_key="github_lists", crawl_tier=1), Adapter
    )
    assert result["status"] == "success"
    assert state.last_crawled_at is not None
    assert len(session.executed) == 1
    query = session.executed[0]
    sql = str(query)
    assert "raw_listings" in sql and "external_id" in sql and "last_seen_at" in sql
    params = query.compile().params
    assert [raw.external_id] in params.values()
    assert 1 in params.values()


def test_github_ingestion_failure_records_partial_retirement_coverage():
    before = datetime(2026, 11, 1, tzinfo=UTC)
    state = SimpleNamespace(last_crawled_at=before, last_content_hash="previous")
    session = _MemorySession(state)

    class Adapter:
        def fetch(self):
            return [_raw("github_lists")]

        def health(self):
            return "ok"

        def coverage(self):
            return {"mode": "full_list", "status": "complete", "expected_total": None}

        def parse(self, _raw):
            raise ValueError("fixture ingestion failure")

    result = runner.crawl_aggregator(
        session, SimpleNamespace(id=1, adapter_key="github_lists", crawl_tier=1), Adapter
    )
    assert result["status"] == "partial"
    assert result["errors"] == 1
    assert result["coverage"]["status"] == "partial"
    assert state.last_crawled_at == before and state.last_content_hash == "previous"
    crawl = next(item for item in session.added if isinstance(item, models.CrawlRun))
    assert crawl.log["coverage"]["status"] == "partial"


def test_source_only_seed_never_creates_companies_or_overrides_legal_switch(monkeypatch):
    existing = models.Source(
        slug="github_lists", adapter_key="github_lists", enabled=False, legal_status="paused"
    )

    class Session(_MemorySession):
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def scalar(self, query):
            return existing if "github_lists" in query.compile().params.values() else None

    session = Session(None)
    monkeypatch.setattr(seed_companies, "make_engine", lambda: object())
    monkeypatch.setattr(seed_companies, "Session", lambda _engine: session)
    monkeypatch.setattr(
        seed_companies,
        "_ADAPTER_SOURCES",
        {
            "workday": (
                "workday",
                "Workday",
                "https://www.myworkdayjobs.com",
                [("acme|wd5|Careers", "Acme", "acme.example")],
            )
        },
    )
    monkeypatch.setattr(
        seed_companies,
        "_AGGREGATOR_SOURCES",
        {"github_lists": ("github_lists", "GitHub lists", "https://github.com/SimplifyJobs")},
    )
    seed_companies.seed(sources_only=True)
    assert len(session.added) == 1
    assert isinstance(session.added[0], models.Source)
    assert session.added[0].adapter_key == "workday"
    assert existing.enabled is False and existing.legal_status == "paused"
