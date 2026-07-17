"""Unit tests for crawler runner helpers and dispatch (no DB/network)."""

from types import SimpleNamespace

import pytest

from core.adapters import RawListing
from crawlers import runner
from crawlers.runner import _board_fingerprint


class _ScalarResult:
    def __init__(self, values: list[object]) -> None:
        self.values = values

    def all(self) -> list[object]:
        return self.values


class _FakeSession:
    def __init__(self, sources: list[object], companies: list[object]) -> None:
        self.sources = sources
        self.companies = companies
        self.scalars_calls = 0

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
        pass

    def scalars(self, _query) -> _ScalarResult:
        self.scalars_calls += 1
        values = self.sources if self.scalars_calls == 1 else self.companies
        return _ScalarResult(values)

    def get(self, _model, source_id: int):
        return next(source for source in self.sources if source.id == source_id)

    def scalar(self, _query):
        return self.companies[0]


class _SessionFactory:
    def __init__(self, sources: list[object], companies: list[object]) -> None:
        self.sources = sources
        self.companies = companies
        self.sessions: list[_FakeSession] = []

    def __call__(self, _engine, **_kwargs) -> _FakeSession:
        session = _FakeSession(self.sources, self.companies)
        self.sessions.append(session)
        return session


def _listing(external_id: str, content_hash: str) -> RawListing:
    return RawListing(
        source_slug="greenhouse",
        external_id=external_id,
        source_url=f"https://example.test/{external_id}",
        content_hash=content_hash,
        raw_payload={},
    )


def test_fingerprint_stable_regardless_of_input_order() -> None:
    a = [_listing("1", "h1"), _listing("2", "h2")]
    b = [_listing("2", "h2"), _listing("1", "h1")]
    assert _board_fingerprint(a) == _board_fingerprint(b)


def test_fingerprint_changes_when_a_job_is_updated() -> None:
    before = [_listing("1", "h1"), _listing("2", "h2")]
    after = [_listing("1", "h1"), _listing("2", "h2-updated")]
    assert _board_fingerprint(before) != _board_fingerprint(after)


def test_fingerprint_changes_when_a_job_is_added() -> None:
    before = [_listing("1", "h1")]
    after = [_listing("1", "h1"), _listing("2", "h2")]
    assert _board_fingerprint(before) != _board_fingerprint(after)


def test_fingerprint_empty_list_is_deterministic() -> None:
    assert _board_fingerprint([]) == _board_fingerprint([])


@pytest.mark.parametrize(
    ("group", "expected_call", "expected_gather_queries"),
    [("ats", "ats", 2), ("aggregator", "aggregator", 1)],
)
def test_run_tier_processes_only_selected_group(
    monkeypatch, group: str, expected_call: str, expected_gather_queries: int
) -> None:
    ats_source = SimpleNamespace(id=1, adapter_key="greenhouse")
    aggregator_source = SimpleNamespace(id=2, adapter_key="remoteok")
    company = SimpleNamespace(
        slug="example-company",
        name="Example Company",
        ats_board_id="example-board",
    )
    session_factory = _SessionFactory([ats_source, aggregator_source], [company])
    calls: list[str] = []
    events: list[str] = []

    def fake_crawl_company_board(_session, source, selected_company, adapter_class, **kwargs):
        assert source is ats_source
        assert selected_company is company
        assert adapter_class is runner.ATS_ADAPTERS["greenhouse"]
        assert kwargs["prefetched"] == []
        assert kwargs["prefetched_health"] == "ok"
        assert events == ["guard"]
        calls.append("ats")
        return {}

    def fake_crawl_aggregator(_session, source, adapter_class, **_kwargs):
        assert source is aggregator_source
        assert adapter_class is runner.AGGREGATOR_ADAPTERS["remoteok"]
        assert events == ["guard"]
        calls.append("aggregator")
        return {}

    def fake_prefetch(jobs, **_kwargs):
        assert events == ["guard"]
        return {job.company_slug: runner._PrefetchedBoard(listings=[], health="ok") for job in jobs}

    def fake_verify_connection_guards(engine) -> None:
        assert engine is fake_engine
        events.append("guard")

    fake_engine = object()
    monkeypatch.setattr(runner, "make_engine", lambda: fake_engine)
    monkeypatch.setattr(runner, "verify_connection_guards", fake_verify_connection_guards)
    monkeypatch.setattr(runner, "Session", session_factory)
    monkeypatch.setattr(runner, "crawl_company_board", fake_crawl_company_board)
    monkeypatch.setattr(runner, "crawl_aggregator", fake_crawl_aggregator)
    monkeypatch.setattr(runner, "_prefetch_ats_boards", fake_prefetch)

    runner.run_tier(1, group=group)

    assert calls == [expected_call]
    assert events == ["guard"]
    assert len(session_factory.sessions) == 2  # gather + exactly one selected job
    assert session_factory.sessions[0].scalars_calls == expected_gather_queries


def test_run_tier_processes_remoteok_after_competition_aggregators(monkeypatch) -> None:
    sources = [
        SimpleNamespace(id=1, adapter_key="remoteok"),
        SimpleNamespace(id=2, adapter_key="unstop"),
        SimpleNamespace(id=3, adapter_key="devpost"),
    ]
    session_factory = _SessionFactory(sources, [])
    calls: list[str] = []

    def fake_crawl_aggregator(_session, source, adapter_class, **_kwargs):
        assert adapter_class is runner.AGGREGATOR_ADAPTERS[source.adapter_key]
        calls.append(source.adapter_key)
        return {}

    monkeypatch.setattr(runner, "make_engine", lambda: object())
    monkeypatch.setattr(runner, "verify_connection_guards", lambda _engine: None)
    monkeypatch.setattr(runner, "Session", session_factory)
    monkeypatch.setattr(runner, "crawl_aggregator", fake_crawl_aggregator)

    runner.run_tier(1, group="aggregator")

    assert set(calls[:-1]) == {"devpost", "unstop"}
    assert calls[-1] == "remoteok"


def test_run_tier_shares_the_aggregator_time_budget(monkeypatch) -> None:
    sources = [
        SimpleNamespace(id=1, adapter_key="devpost"),
        SimpleNamespace(id=2, adapter_key="unstop"),
    ]
    session_factory = _SessionFactory(sources, [])
    calls: list[tuple[str, float, float]] = []
    monotonic_values = iter([100.0, 100.0, 701.0])

    def fake_crawl_aggregator(
        _session,
        source,
        _adapter_class,
        *,
        max_seconds,
        deadline_monotonic,
        **_kwargs,
    ):
        calls.append((source.adapter_key, max_seconds, deadline_monotonic))
        return {}

    monkeypatch.setattr(runner, "make_engine", lambda: object())
    monkeypatch.setattr(runner, "verify_connection_guards", lambda _engine: None)
    monkeypatch.setattr(runner, "Session", session_factory)
    monkeypatch.setattr(runner, "crawl_aggregator", fake_crawl_aggregator)
    monkeypatch.setattr(runner.time, "monotonic", lambda: next(monotonic_values))

    runner.run_tier(1, group="aggregator", aggregator_max_seconds=600.0)

    assert calls == [("devpost", 600.0, 700.0)]
