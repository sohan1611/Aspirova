"""Unit tests for JobicyAdapter using a fixture payload."""

import json
from pathlib import Path

import httpx
import pytest

from core.adapters import RawListing
from crawlers.common import content_hash
from crawlers import jobicy
from crawlers.jobicy import JobicyAdapter

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "jobicy_sample.json"


def _load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _raw_listing_for(job: dict) -> RawListing:
    return RawListing(
        source_slug="jobicy",
        external_id=str(job["id"]),
        source_url=job["url"],
        content_hash=content_hash(job),
        raw_payload=job,
    )


@pytest.fixture
def adapter() -> JobicyAdapter:
    return JobicyAdapter()


@pytest.fixture
def fixture_payload() -> dict:
    return _load_fixture()


def test_adapter_identity_and_default_health(adapter: JobicyAdapter) -> None:
    assert adapter.source_slug == "jobicy"
    assert adapter.requires_browser is False
    assert adapter.health() == "ok"


def test_fetch_filters_title_and_level_seniority_before_returning_raw_listings(
    adapter: JobicyAdapter,
    fixture_payload: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_params: list[dict] = []

    def fake_get(url: str, *, params: dict) -> httpx.Response:
        request_params.append(params)
        request = httpx.Request("GET", url, params=params)
        return httpx.Response(200, json=fixture_payload, request=request)

    monkeypatch.setattr(adapter._client, "get", fake_get)

    raw_listings = adapter.fetch()

    assert [listing.external_id for listing in raw_listings] == ["101", "104"]
    assert adapter.filter_counts() == {
        "raw_count": 4,
        "student_relevant_count": 2,
        "filtered_out": 2,
    }
    coverage = adapter.coverage()
    # jobCount is one page's size, never a source total.
    assert coverage["expected_total"] is None
    assert coverage["mode"] == "bounded_window"
    assert coverage["status"] == "complete"
    assert coverage["details"]["window_raw_fetched"] == 4
    assert coverage["details"]["window_raw_expected"] == 4
    assert request_params == [{"count": 100}]


def test_fetch_retries_transient_429_before_succeeding(
    adapter: JobicyAdapter,
    fixture_payload: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = [429, 200]
    request_params: list[dict] = []
    sleep_calls: list[float] = []

    def fake_get(url: str, *, params: dict) -> httpx.Response:
        request_params.append(params)
        request = httpx.Request("GET", url, params=params)
        status_code = responses.pop(0)
        if status_code == 429:
            return httpx.Response(
                429,
                text="Too Many Requests",
                headers={"Retry-After": "3"},
                request=request,
            )
        return httpx.Response(200, json=fixture_payload, request=request)

    monkeypatch.setattr(adapter._client, "get", fake_get)
    monkeypatch.setattr(jobicy, "sleep", lambda seconds: sleep_calls.append(seconds))

    raw_listings = adapter.fetch()

    assert [listing.external_id for listing in raw_listings] == ["101", "104"]
    assert adapter.health() == "ok"
    coverage = adapter.coverage()
    assert coverage["details"]["requests_made"] == 2
    assert coverage["details"]["retry_attempts"] == 1
    assert coverage["details"]["retry_reasons"] == ["http_429"]
    assert coverage["details"]["terminal_reason"] is None
    assert sleep_calls == [3.0]
    assert request_params == [{"count": 100}, {"count": 100}]


def test_parse_keeps_jobicy_original_url_and_level_metadata(
    adapter: JobicyAdapter, fixture_payload: dict
) -> None:
    kept_job = fixture_payload["jobs"][0]
    normalized = adapter.parse(_raw_listing_for(kept_job))

    assert normalized.title == "Entry Junior Product Engineer"
    assert normalized.company_name == "Orbit Labs"
    assert normalized.category == "job"
    assert normalized.apply_url == kept_job["url"]
    assert normalized.is_remote is True
    assert normalized.meta["platform"] == "jobicy"
    assert normalized.meta["job_level"] == "Entry/Junior"


def test_parse_maps_graduate_trainee_to_internship(
    adapter: JobicyAdapter, fixture_payload: dict
) -> None:
    kept_job = fixture_payload["jobs"][3]
    normalized = adapter.parse(_raw_listing_for(kept_job))

    assert normalized.category == "internship"
    assert normalized.apply_url == kept_job["url"]


@pytest.mark.parametrize(
    "title", ["2027 US AI Engineering – New College Graduate", "Graduate Data Analyst"]
)
def test_fetch_keeps_graduate_roles_and_parse_classifies_them_as_jobs(
    adapter: JobicyAdapter, fixture_payload: dict, monkeypatch, title: str
) -> None:
    job = {**fixture_payload["jobs"][0], "jobTitle": title, "jobLevel": "Entry/Junior"}

    def fake_get(url: str, *, params: dict) -> httpx.Response:
        return httpx.Response(
            200, json={"jobs": [job], "jobCount": 1}, request=httpx.Request("GET", url)
        )

    monkeypatch.setattr(adapter._client, "get", fake_get)
    listings = adapter.fetch()
    assert len(listings) == 1
    assert adapter.parse(listings[0]).category == "job"


@pytest.mark.parametrize(
    "logo, expected",
    [
        ("https://images.example/logo.png", "https://images.example/logo.png"),
        (" http://images.example/logo.png ", "http://images.example/logo.png"),
        (None, None),
        ("", None),
        ("  ", None),
        ("ftp://images.example/logo.png", None),
        ("data:image/png;base64,abc", None),
        ("javascript:alert(1)", None),
        ("/logo.png", None),
        ("//images.example/logo.png", None),
        ("https:///", None),
        ("https://[broken", None),
    ],
)
def test_parse_company_logo_requires_http_url(adapter, fixture_payload, logo, expected) -> None:
    job = {**fixture_payload["jobs"][0], "companyLogo": logo}

    assert adapter.parse(_raw_listing_for(job)).company_logo_url == expected


def test_parse_missing_company_logo_is_none(adapter, fixture_payload) -> None:
    job = {**fixture_payload["jobs"][0]}
    job.pop("companyLogo", None)

    assert adapter.parse(_raw_listing_for(job)).company_logo_url is None


def test_parse_ignores_logo_when_company_falls_back_to_source(adapter, fixture_payload) -> None:
    job = {
        **fixture_payload["jobs"][0],
        "company": None,
        "companyName": "",
        "company_name": "",
        "companySlug": "",
        "company_slug": "",
        "companyLogo": "https://images.example/logo.png",
    }
    normalized = adapter.parse(_raw_listing_for(job))

    assert normalized.company_name == "Jobicy"
    assert normalized.company_logo_url is None


def _job(job_id: int, title: str, level: str = "Any") -> dict:
    return {
        "id": job_id,
        "url": f"https://jobicy.com/jobs/{job_id}",
        "jobTitle": title,
        "companyName": "Orbit Labs",
        "jobLevel": level,
        "pubDate": "2026-11-11T10:00:00+00:00",
    }


def _serve_pages(
    adapter: JobicyAdapter,
    monkeypatch: pytest.MonkeyPatch,
    pages: list[dict | int],
) -> tuple[list[tuple[str, dict]], list[float]]:
    """Serve each page in turn: a dict is a 200 payload, an int a bare status."""
    calls: list[tuple[str, dict]] = []
    sleeps: list[float] = []

    def fake_get(url: str, *, params: dict) -> httpx.Response:
        calls.append((url, dict(params)))
        page = pages.pop(0)
        request = httpx.Request("GET", url, params=params)
        if isinstance(page, int):
            return httpx.Response(page, text="unavailable", request=request)
        return httpx.Response(200, json=page, request=request)

    monkeypatch.setattr(adapter._client, "get", fake_get)
    monkeypatch.setattr(jobicy, "sleep", lambda seconds: sleeps.append(seconds))
    return calls, sleeps


def test_fetch_follows_the_cursor_through_the_whole_window(
    adapter: JobicyAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls, sleeps = _serve_pages(
        adapter,
        monkeypatch,
        [
            {
                "jobCount": 2,
                "jobs": [_job(1, "Growth Marketing Intern"), _job(2, "VP Sales")],
                "nextCursor": "c1",
                "hasMore": True,
            },
            {
                "jobCount": 2,
                "jobs": [_job(3, "Data Analyst", "Entry-Level, Junior"), _job(4, "CTO")],
                "nextCursor": "c2",
                "hasMore": True,
            },
            {
                "jobCount": 1,
                "jobs": [_job(5, "Graduate HR Generalist")],
                "nextCursor": None,
                "hasMore": False,
            },
        ],
    )

    listings = adapter.fetch()

    assert [listing.external_id for listing in listings] == ["1", "3", "5"]
    assert calls == [
        ("https://jobicy.com/api/jobs", {"count": 100}),
        ("https://jobicy.com/api/jobs", {"count": 100, "cursor": "c1"}),
        ("https://jobicy.com/api/jobs", {"count": 100, "cursor": "c2"}),
    ]
    assert sleeps == [jobicy._PAGE_DELAY_SECONDS, jobicy._PAGE_DELAY_SECONDS]
    assert adapter.health() == "ok"
    coverage = adapter.coverage()
    assert coverage["status"] == "complete"
    assert coverage["details"]["pages_requested"] == 3
    assert coverage["details"]["window_raw_fetched"] == 5
    assert coverage["details"]["window_raw_expected"] == 5
    assert coverage["details"]["hit_page_cap"] is False


def test_fetch_keeps_earlier_pages_when_a_later_page_fails(
    adapter: JobicyAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    first_page = {"jobs": [_job(1, "Security Intern")], "nextCursor": "c1", "hasMore": True}
    calls, _ = _serve_pages(adapter, monkeypatch, [first_page, 500, 500, 500])

    listings = adapter.fetch()

    assert [listing.external_id for listing in listings] == ["1"]
    assert len(calls) == 4  # page one, then page two with its two retries
    assert adapter.health() == "degraded"
    coverage = adapter.coverage()
    assert coverage["status"] == "partial"
    assert coverage["details"]["terminal_reason"] == "http_500"
    assert coverage["details"]["window_raw_fetched"] == 1
    assert coverage["details"]["window_raw_expected"] is None
    assert "fetch ended with http_500" in coverage["note"]


def test_fetch_first_page_404_is_broken_and_returns_nothing(
    adapter: JobicyAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    _serve_pages(adapter, monkeypatch, [404])

    assert adapter.fetch() == []
    assert adapter.health() == "broken"
    assert adapter.coverage()["details"]["terminal_reason"] == "http_404"


def test_fetch_stops_at_the_page_cap_and_reports_partial(
    adapter: JobicyAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(jobicy, "_MAX_PAGES", 2)
    calls, _ = _serve_pages(
        adapter,
        monkeypatch,
        [
            {"jobs": [_job(1, "Marketing Intern")], "nextCursor": "c1", "hasMore": True},
            {"jobs": [_job(2, "Design Intern")], "nextCursor": "c2", "hasMore": True},
        ],
    )

    listings = adapter.fetch()

    assert [listing.external_id for listing in listings] == ["1", "2"]
    assert len(calls) == 2
    assert adapter.health() == "degraded"
    coverage = adapter.coverage()
    assert coverage["status"] == "partial"
    assert coverage["details"]["hit_page_cap"] is True
    assert coverage["details"]["terminal_reason"] == "page_cap"


def test_fetch_treats_has_more_without_a_cursor_as_partial(
    adapter: JobicyAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    _serve_pages(
        adapter,
        monkeypatch,
        [{"jobs": [_job(1, "Finance Intern")], "nextCursor": None, "hasMore": True}],
    )

    assert [listing.external_id for listing in adapter.fetch()] == ["1"]
    assert adapter.health() == "degraded"
    assert adapter.coverage()["details"]["terminal_reason"] == "missing_cursor"


def test_fetch_dedupes_a_job_repeated_across_pages(
    adapter: JobicyAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    repeated = _job(7, "Content Intern")
    _serve_pages(
        adapter,
        monkeypatch,
        [
            {"jobs": [repeated], "nextCursor": "c1", "hasMore": True},
            {"jobs": [repeated, _job(8, "Ops Intern")], "nextCursor": None, "hasMore": False},
        ],
    )

    assert [listing.external_id for listing in adapter.fetch()] == ["7", "8"]
    assert adapter.filter_counts()["raw_count"] == 2


@pytest.mark.parametrize(
    "title, level, kept",
    [
        # Live 2026-11-11 examples: Jobicy tagged these student titles senior.
        ("Growth Marketing Intern", "Senior", True),
        ("Security Intern, Threat Operations - Winter 2027", "Senior", True),
        ("Customer Success Junior", "Director", True),
        # Without a student word in the title, the level tag still decides.
        ("Platform Engineer", "Entry-Level, Junior", True),
        ("Platform Engineer", "Senior", False),
        ("Product Manager", "Any", False),
        # A senior word in the title still wins over everything.
        ("Junior Customer Success Manager (API)", "Entry-Level, Junior", False),
        ("Graduate Partner Marketing Manager", "Senior", False),
    ],
)
def test_a_student_title_wins_over_a_wrong_level_tag(
    adapter: JobicyAdapter,
    monkeypatch: pytest.MonkeyPatch,
    title: str,
    level: str,
    kept: bool,
) -> None:
    _serve_pages(adapter, monkeypatch, [{"jobs": [_job(9, title, level)], "nextCursor": None}])

    assert len(adapter.fetch()) == (1 if kept else 0)
