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


def _is_source_state_query(query) -> bool:
    try:
        return query.column_descriptions[0]["entity"].__name__ == "SourceState"
    except (AttributeError, IndexError, KeyError, TypeError):
        return False


class _FakeSession:
    def __init__(self, sources: list[object], companies: list[object]) -> None:
        self.sources = sources
        self.companies = companies
        self.scalars_calls = 0

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
        pass

    def scalars(self, query) -> _ScalarResult:
        # The stalest-first ordering reads SourceState; no prior crawls exist
        # in these unit tests, so return empty and leave the sources/companies
        # positional sequence undisturbed.
        if _is_source_state_query(query):
            return _ScalarResult([])
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


def test_order_ats_jobs_interleaves_sources_to_prevent_source_starvation() -> None:
    from datetime import datetime, timezone

    jobs = [
        runner._AtsJob(
            company_id=3,
            source_id=1,
            company_slug="source-one-oldest",
            adapter_key="ashby",
            board_token="source-one-oldest",
            company_name="Source One Oldest",
        ),
        runner._AtsJob(
            company_id=2,
            source_id=1,
            company_slug="source-one-second",
            adapter_key="ashby",
            board_token="source-one-second",
            company_name="Source One Second",
        ),
        runner._AtsJob(
            company_id=1,
            source_id=2,
            company_slug="source-two-only",
            adapter_key="amazon",
            board_token="source-two-only",
            company_name="Source Two Only",
        ),
    ]
    states = {
        (1, "source-one-oldest"): datetime(2026, 7, 1, tzinfo=timezone.utc),
        (1, "source-one-second"): datetime(2026, 7, 2, tzinfo=timezone.utc),
        (2, "source-two-only"): datetime(2026, 8, 1, tzinfo=timezone.utc),
    }

    ordered = runner._order_ats_jobs(jobs, states)

    assert [job.company_slug for job in ordered] == [
        "source-one-oldest",
        "source-two-only",
        "source-one-second",
    ]


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
        id=1,
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
    monkeypatch.setattr(
        runner, "_refresh_prestige_matches", lambda _engine: events.append("prestige")
    )

    runner.run_tier(1, group=group)

    assert calls == [expected_call]
    assert events == ["guard", "prestige"]
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
    monkeypatch.setattr(runner, "_refresh_prestige_matches", lambda _engine: None)

    runner.run_tier(1, group="aggregator")

    assert set(calls[:-1]) == {"devpost", "unstop"}
    assert calls[-1] == "remoteok"


def test_run_tier_gives_each_aggregator_its_own_time_budget(monkeypatch) -> None:
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
        if source.adapter_key == "devpost":
            return {
                "status": "partial",
                "stopped_early": True,
                "truncation_elapsed_seconds": 600.0,
                "truncation_budget_seconds": 600.0,
            }
        return {}

    monkeypatch.setattr(runner, "make_engine", lambda: object())
    monkeypatch.setattr(runner, "verify_connection_guards", lambda _engine: None)
    monkeypatch.setattr(runner, "Session", session_factory)
    monkeypatch.setattr(runner, "crawl_aggregator", fake_crawl_aggregator)
    monkeypatch.setattr(runner.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(runner, "_refresh_prestige_matches", lambda _engine: None)

    runner.run_tier(
        1,
        group="aggregator",
        aggregator_max_seconds=600.0,
        aggregator_group_max_seconds=5_000.0,
    )

    assert calls == [("devpost", 600.0, 700.0), ("unstop", 600.0, 1301.0)]


def test_run_tier_summarizes_truncated_aggregators(monkeypatch, capsys) -> None:
    source = SimpleNamespace(id=1, adapter_key="unstop")
    session_factory = _SessionFactory([source], [])

    def fake_crawl_aggregator(_session, selected_source, _adapter_class, **_kwargs):
        assert selected_source is source
        return {
            "status": "partial",
            "stopped_early": True,
            "truncation_elapsed_seconds": 7.0,
            "truncation_budget_seconds": 60.0,
        }

    monkeypatch.setattr(runner, "make_engine", lambda: object())
    monkeypatch.setattr(runner, "verify_connection_guards", lambda _engine: None)
    monkeypatch.setattr(runner, "Session", session_factory)
    monkeypatch.setattr(runner, "crawl_aggregator", fake_crawl_aggregator)
    monkeypatch.setattr(runner, "_refresh_prestige_matches", lambda _engine: None)
    monkeypatch.setattr(runner, "notify_changed", lambda _slugs: None)

    runner.run_tier(1, group="aggregator")

    output = capsys.readouterr().out
    assert "TRUNCATION SUMMARY: truncated sources:" in output
    assert "  - unstop: after 7.0s (budget 60.0s)" in output


def test_refresh_prestige_matches_calls_matcher_without_reset(monkeypatch, capsys) -> None:
    fake_engine = object()
    sessions: list[object] = []
    calls: list[dict[str, object]] = []

    class _Session:
        def __init__(self, engine):
            assert engine is fake_engine
            sessions.append(self)

        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
            pass

    def fake_match_prestige(session, **kwargs):
        assert session is sessions[0]
        calls.append(kwargs)
        return {"scanned": 3, "ranked": 2, "unranked": 1}

    monkeypatch.setattr(runner, "Session", _Session)
    monkeypatch.setattr(runner, "match_prestige", fake_match_prestige)

    result = runner._refresh_prestige_matches(fake_engine)

    assert result == {"scanned": 3, "ranked": 2, "unranked": 1}
    assert calls == [{}]
    assert "prestige match after crawl: scanned 3, ranked 2, unranked 1" in capsys.readouterr().out


def test_refresh_prestige_matches_is_non_fatal(monkeypatch, capsys) -> None:
    class _Session:
        def __init__(self, _engine):
            pass

        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
            pass

    def fake_match_prestige(_session, **_kwargs):
        raise RuntimeError("matcher unavailable")

    monkeypatch.setattr(runner, "Session", _Session)
    monkeypatch.setattr(runner, "match_prestige", fake_match_prestige)

    result = runner._refresh_prestige_matches(object())

    assert result is None
    assert "WARNING: prestige match after crawl failed: RuntimeError: matcher unavailable" in (
        capsys.readouterr().out
    )
