"""Unit tests for crawler runner helpers and dispatch (no DB/network)."""

from types import SimpleNamespace

import httpx
import pytest

from core.adapters import RawListing
from crawlers.hackerearth import HackerEarthAdapter
from crawlers import runner
from crawlers.runner import _board_fingerprint
from crawlers.student_relevance import is_student_relevant_role
from scripts.crawl_retry import retry_decision


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


def test_new_aggregator_sources_are_registered() -> None:
    assert {
        "arbeitnow",
        "hackerearth",
        "himalayas",
        "jobicy",
    }.issubset(runner.AGGREGATOR_ADAPTERS)


@pytest.mark.parametrize(
    "title",
    [
        "Software Engineer Intern",
        "Graduate Data Analyst",
        "Junior Developer",
        "New Grad Software Engineer",
        "Trainee Consultant",
    ],
)
def test_new_job_aggregator_filter_keeps_positive_student_titles(title: str) -> None:
    assert is_student_relevant_role(title)


@pytest.mark.parametrize(
    "title",
    [
        "Procurement Coordinator",
        "Managed Services Field Engineer",
        "MÜNCHEN - Campervan Reinigung (m/w/d)",
    ],
)
def test_new_job_aggregator_filter_rejects_titles_without_student_signal(title: str) -> None:
    assert not is_student_relevant_role(title)


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        # "campus" alone described a recruiter who VISITS campuses. Seen live on
        # Himalayas as "Campus Recruiter - Dental Hygiene".
        ("Campus Recruiter - Dental Hygiene", False),
        ("Campus Talent Acquisition Specialist", False),
        # Genuine campus programmes must still qualify.
        ("Campus Ambassador", True),
        ("Campus Hiring Program 2027", True),
        ("Campus Internship - Analytics", True),
    ],
)
def test_campus_only_counts_when_it_names_a_student_programme(title: str, expected: bool) -> None:
    assert is_student_relevant_role(title) is expected


@pytest.mark.parametrize("level_field", ["Entry", "Entry-level", ["Junior"]])
def test_new_job_aggregator_filter_keeps_source_entry_level_fields(
    level_field: object,
) -> None:
    assert is_student_relevant_role("Product Analyst", level_field)


def test_hackerearth_keeps_competition_without_entry_level_title(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert not is_student_relevant_role("August Circuits")

    adapter = HackerEarthAdapter()
    payload = {
        "response": [
            {
                "challenge_type": "Monthly Challenges",
                "title": "August Circuits",
                "url": "/challenges/competitive/august-circuits-26/",
                "start_timestamp": 1786934400,
                "end_timestamp": 1789526400,
                "status": "ONGOING",
            }
        ]
    }

    def fake_get(url: str) -> httpx.Response:
        request = httpx.Request("GET", url)
        return httpx.Response(200, json=payload, request=request)

    monkeypatch.setattr(adapter._client, "get", fake_get)

    raw_listings = adapter.fetch()

    assert len(raw_listings) == 1
    assert raw_listings[0].source_url == (
        "https://www.hackerearth.com/challenges/competitive/august-circuits-26/"
    )
    assert adapter.health() == "ok"


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


def test_run_tier_never_lets_one_aggregator_consume_the_group_budget(monkeypatch) -> None:
    """A per-source budget alone is not enough to stop starvation.

    With a 7200s per-source budget under a 900s group ceiling, the first source
    would be handed a deadline 8x past the point at which the group loop breaks,
    so the sources behind it would be skipped entirely - which is what left
    devpost and remoteok 11 days stale while unstop ate the shared budget.

    Each source must instead get the FAIR SHARE of the time still remaining, so
    no source's deadline can ever exceed the group deadline.
    """
    sources = [
        SimpleNamespace(id=1, adapter_key="unstop"),
        SimpleNamespace(id=2, adapter_key="devpost"),
        SimpleNamespace(id=3, adapter_key="remoteok"),
    ]
    session_factory = _SessionFactory(sources, [])
    calls: list[tuple[str, float, float]] = []
    # started, then one reading per iteration; source 1 is slow (0 -> 400s).
    monotonic_values = iter([0.0, 0.0, 400.0, 500.0])

    def fake_crawl_aggregator(
        _session, source, _adapter_class, *, max_seconds, deadline_monotonic, **_kwargs
    ):
        calls.append((source.adapter_key, max_seconds, deadline_monotonic))
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
        aggregator_max_seconds=7_200.0,
        aggregator_group_max_seconds=900.0,
    )

    # Every source ran - none was starved by the one before it. Order is set by
    # _order_aggregator_jobs (stalest-first), so compare as a set, not a sequence.
    assert {call[0] for call in calls} == {"unstop", "devpost", "remoteok"}
    assert len(calls) == 3

    group_deadline = 900.0
    for adapter_key, budget, deadline in calls:
        assert deadline <= group_deadline, (
            f"{adapter_key} was given a deadline past the group ceiling; "
            "it could consume the whole budget and starve the sources behind it"
        )
        assert budget < 7_200.0, f"{adapter_key} got the nominal budget, not its fair share"

    # First source is capped at its share of the group, not the nominal budget.
    assert calls[0][1] == pytest.approx(300.0)


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


def test_crawl_retry_bound_stops_at_attempt_three() -> None:
    decision = retry_decision(
        attempt=3,
        retry_status_lines=["TRUNCATED: ATS stopped early after 7200.0s (budget 7200.0s)"],
    )

    assert decision.should_dispatch is False
    assert decision.next_attempt is None
    assert decision.reason == "Retry suppressed: attempt 3 >= 3"
