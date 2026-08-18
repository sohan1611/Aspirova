"""Unit tests for HimalayasAdapter using a fixture payload."""

import json
from pathlib import Path

import httpx
import pytest

from core.adapters import RawListing
from crawlers import runner
from crawlers.common import content_hash
from crawlers import himalayas
from crawlers.himalayas import HimalayasAdapter

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "himalayas_sample.json"


def _load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _raw_listing_for(job: dict) -> RawListing:
    return RawListing(
        source_slug="himalayas",
        external_id=str(job["id"]),
        source_url=job.get("url") or job["applicationLink"],
        content_hash=content_hash(job),
        raw_payload=job,
    )


@pytest.fixture
def adapter() -> HimalayasAdapter:
    return HimalayasAdapter()


@pytest.fixture
def fixture_payload() -> dict:
    return _load_fixture()


def test_adapter_identity_and_default_health(adapter: HimalayasAdapter) -> None:
    assert adapter.source_slug == "himalayas"
    assert adapter.requires_browser is False
    assert adapter.health() == "ok"


def test_fetch_filters_title_only_before_returning_raw_listings(
    adapter: HimalayasAdapter,
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

    assert [listing.external_id for listing in raw_listings] == ["hm-101", "hm-104"]
    assert adapter.filter_counts() == {
        "raw_count": 4,
        "student_relevant_count": 2,
        "filtered_out": 2,
    }
    coverage = adapter.coverage()
    assert coverage["mode"] == "bounded_window"
    assert coverage["expected_total"] is None
    assert coverage["status"] == "complete"
    assert coverage["note"] == "bounded by design to the most recent Himalayas jobs window"
    assert coverage["details"] == {
        "raw_count": 4,
        "student_relevant_count": 2,
        "filtered_out": 2,
        "catalogue_total": 102211,
        "request_cap": 250,
        "page_size_requested": 20,
        "requests_made": 1,
        "pages_requested": 1,
        "bounded_by_design": True,
        "hit_request_cap": False,
        "terminal_reason": "short_page",
        "terminal_offset": 0,
        "window_raw_fetched": 4,
        "window_raw_expected": 4,
    }
    assert (
        runner._coverage_line(
            "himalayas",
            runner._coverage_from_adapter(adapter, "himalayas", len(raw_listings), health="ok"),
        )
        == "COVERAGE: himalayas 2 kept from 4/4 raw window (complete; catalogue total 102211)"
    )
    assert request_params == [{"limit": 20, "offset": 0}]


def test_fetch_reports_empty_terminal_page_as_complete_bounded_window(
    adapter: HimalayasAdapter,
    fixture_payload: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    full_page_jobs = [
        {
            **fixture_payload["jobs"][0],
            "id": f"hm-page-{index}",
            "url": f"https://himalayas.app/companies/nimbus/jobs/page-{index}",
            "applicationLink": (f"https://himalayas.app/companies/nimbus/jobs/page-{index}/apply"),
        }
        for index in range(20)
    ]
    request_params: list[dict] = []

    def fake_get(url: str, *, params: dict) -> httpx.Response:
        request_params.append(params)
        jobs = full_page_jobs if params["offset"] == 0 else []
        request = httpx.Request("GET", url, params=params)
        return httpx.Response(200, json={"totalCount": 101767, "jobs": jobs}, request=request)

    monkeypatch.setattr(adapter._client, "get", fake_get)
    monkeypatch.setattr(himalayas, "sleep", lambda _seconds: None)

    raw_listings = adapter.fetch()

    assert len(raw_listings) == 20
    coverage = adapter.coverage()
    assert coverage["status"] == "complete"
    assert coverage["details"]["bounded_by_design"] is True
    assert coverage["details"]["terminal_reason"] == "empty_page"
    assert coverage["details"]["terminal_offset"] == 20
    assert coverage["details"]["requests_made"] == 2
    assert coverage["details"]["pages_requested"] == 2
    assert coverage["details"]["window_raw_fetched"] == 20
    assert coverage["details"]["window_raw_expected"] == 20
    assert request_params == [{"limit": 20, "offset": 0}, {"limit": 20, "offset": 20}]


def test_fetch_reports_degraded_terminal_reason_as_partial_window(
    adapter: HimalayasAdapter,
    fixture_payload: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    full_page_jobs = [
        {
            **fixture_payload["jobs"][0],
            "id": f"hm-error-{index}",
            "url": f"https://himalayas.app/companies/nimbus/jobs/error-{index}",
            "applicationLink": (f"https://himalayas.app/companies/nimbus/jobs/error-{index}/apply"),
        }
        for index in range(20)
    ]

    def fake_get(url: str, *, params: dict) -> httpx.Response:
        request = httpx.Request("GET", url, params=params)
        if params["offset"] == 0:
            return httpx.Response(
                200, json={"totalCount": 101767, "jobs": full_page_jobs}, request=request
            )
        return httpx.Response(503, json={"error": "try later"}, request=request)

    monkeypatch.setattr(adapter._client, "get", fake_get)
    monkeypatch.setattr(himalayas, "sleep", lambda _seconds: None)

    raw_listings = adapter.fetch()

    assert len(raw_listings) == 20
    assert adapter.health() == "degraded"
    coverage = adapter.coverage()
    assert coverage["status"] == "partial"
    assert coverage["note"].endswith("fetch ended with http_503")
    assert coverage["details"]["terminal_reason"] == "http_503"
    assert coverage["details"]["terminal_offset"] == 20
    assert coverage["details"]["requests_made"] == 5
    assert coverage["details"]["pages_requested"] == 2
    assert coverage["details"]["retry_attempts"] == 3
    assert coverage["details"]["retry_reasons"] == ["http_503", "http_503", "http_503"]


def test_fetch_retries_429_retry_after_before_succeeding(
    adapter: HimalayasAdapter,
    fixture_payload: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_params: list[dict] = []
    sleep_calls: list[float] = []
    responses = [429, 200]

    def fake_get(url: str, *, params: dict) -> httpx.Response:
        request_params.append(params)
        request = httpx.Request("GET", url, params=params)
        status_code = responses.pop(0)
        if status_code == 429:
            return httpx.Response(
                429,
                text="Too Many Requests",
                headers={"Retry-After": "7"},
                request=request,
            )
        return httpx.Response(200, json=fixture_payload, request=request)

    monkeypatch.setattr(adapter._client, "get", fake_get)
    monkeypatch.setattr(himalayas, "sleep", lambda seconds: sleep_calls.append(seconds))

    raw_listings = adapter.fetch()

    assert [listing.external_id for listing in raw_listings] == ["hm-101", "hm-104"]
    assert adapter.health() == "ok"
    coverage = adapter.coverage()
    assert coverage["status"] == "complete"
    assert coverage["details"]["requests_made"] == 2
    assert coverage["details"]["pages_requested"] == 1
    assert coverage["details"]["retry_attempts"] == 1
    assert coverage["details"]["retry_reasons"] == ["http_429"]
    assert sleep_calls == [7.0]
    assert request_params == [
        {"limit": 20, "offset": 0},
        {"limit": 20, "offset": 0},
    ]


def test_fetch_reports_persistent_429_after_retry_bound_as_partial_window(
    adapter: HimalayasAdapter,
    fixture_payload: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    full_page_jobs = [
        {
            **fixture_payload["jobs"][0],
            "id": f"hm-rate-limit-{index}",
            "url": f"https://himalayas.app/companies/nimbus/jobs/rate-limit-{index}",
            "applicationLink": (
                f"https://himalayas.app/companies/nimbus/jobs/rate-limit-{index}/apply"
            ),
        }
        for index in range(20)
    ]
    request_params: list[dict] = []
    sleep_calls: list[float] = []

    def fake_get(url: str, *, params: dict) -> httpx.Response:
        request_params.append(params)
        request = httpx.Request("GET", url, params=params)
        if params["offset"] == 0:
            return httpx.Response(
                200, json={"totalCount": 101767, "jobs": full_page_jobs}, request=request
            )
        return httpx.Response(
            429,
            text="Too Many Requests",
            headers={"Retry-After": "1"},
            request=request,
        )

    monkeypatch.setattr(adapter._client, "get", fake_get)
    monkeypatch.setattr(himalayas, "sleep", lambda seconds: sleep_calls.append(seconds))

    raw_listings = adapter.fetch()

    assert len(raw_listings) == 20
    assert adapter.health() == "degraded"
    coverage = adapter.coverage()
    assert coverage["status"] == "partial"
    assert coverage["note"].endswith("fetch ended with http_429")
    assert coverage["details"]["terminal_reason"] == "http_429"
    assert coverage["details"]["terminal_offset"] == 20
    assert coverage["details"]["requests_made"] == 5
    assert coverage["details"]["pages_requested"] == 2
    assert coverage["details"]["retry_attempts"] == 3
    assert coverage["details"]["retry_reasons"] == ["http_429", "http_429", "http_429"]
    assert coverage["details"]["window_raw_fetched"] == 20
    assert coverage["details"]["window_raw_expected"] == 5000
    assert sleep_calls == [3.0, 1.0, 1.0, 1.0]
    assert request_params == [
        {"limit": 20, "offset": 0},
        {"limit": 20, "offset": 20},
        {"limit": 20, "offset": 20},
        {"limit": 20, "offset": 20},
        {"limit": 20, "offset": 20},
    ]


def test_fetch_rejects_source_entry_level_without_himalayas_title_signal(
    adapter: HimalayasAdapter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "totalCount": 2,
        "jobs": [
            {
                "id": "hm-entry-noise",
                "url": "https://himalayas.app/companies/acme/jobs/customer-service-assistant",
                "applicationLink": (
                    "https://himalayas.app/companies/acme/jobs/customer-service-assistant/apply"
                ),
                "title": "Customer Service Assistant",
                "companyName": "Acme",
                "description": "<p>Support customers.</p>",
                "publishedDate": "2026-08-16T09:00:00Z",
                "seniority": "Entry-level",
            },
            {
                "id": "hm-intern",
                "url": "https://himalayas.app/companies/acme/jobs/data-science-intern",
                "applicationLink": (
                    "https://himalayas.app/companies/acme/jobs/data-science-intern/apply"
                ),
                "title": "Data Science Intern",
                "companyName": "Acme",
                "description": "<p>Student internship.</p>",
                "publishedDate": "2026-08-16T09:00:00Z",
                "seniority": "Entry-level",
            },
        ],
    }

    def fake_get(url: str, *, params: dict) -> httpx.Response:
        request = httpx.Request("GET", url, params=params)
        return httpx.Response(200, json=payload, request=request)

    monkeypatch.setattr(adapter._client, "get", fake_get)

    raw_listings = adapter.fetch()

    assert [listing.external_id for listing in raw_listings] == ["hm-intern"]
    assert adapter.filter_counts() == {
        "raw_count": 2,
        "student_relevant_count": 1,
        "filtered_out": 1,
    }


def test_parse_keeps_original_urls_company_and_bounded_coverage_details(
    adapter: HimalayasAdapter, fixture_payload: dict
) -> None:
    kept_job = fixture_payload["jobs"][0]
    normalized = adapter.parse(_raw_listing_for(kept_job))

    assert normalized.title == "Junior Frontend Engineer"
    assert normalized.company_name == "Nimbus"
    assert normalized.company_domain == "https://nimbus.example"
    assert normalized.category == "job"
    assert normalized.apply_url == kept_job["applicationLink"]
    assert normalized.source_url == kept_job["url"]
    assert normalized.is_remote is True
    assert normalized.meta["seniority"] == "Entry"


def test_parse_maps_graduate_trainee_to_internship(
    adapter: HimalayasAdapter, fixture_payload: dict
) -> None:
    kept_job = fixture_payload["jobs"][3]
    normalized = adapter.parse(_raw_listing_for(kept_job))

    assert normalized.category == "internship"
    assert normalized.apply_url == kept_job["applicationLink"]


def test_parse_falls_back_from_placeholder_company_name_to_slug(
    adapter: HimalayasAdapter, fixture_payload: dict
) -> None:
    live_shape_job = {
        **fixture_payload["jobs"][0],
        "id": "hm-live-shape",
        "guid": "hm-live-shape",
        "url": None,
        "applicationLink": "https://himalayas.app/companies/circular-action-alliance/jobs/procurement-coordinator",
        "company": None,
        "companyName": "name",
        "companySlug": "circular-action-alliance",
        "seniority": ["Mid-level"],
        "employmentType": "Full-time",
        "pubDate": "2026-08-17T02:40:00Z",
    }

    normalized = adapter.parse(_raw_listing_for(live_shape_job))

    assert normalized.company_name == "Circular Action Alliance"
    assert normalized.apply_url == live_shape_job["applicationLink"]
    assert normalized.source_url == live_shape_job["applicationLink"]
    assert normalized.meta["seniority"] == "Mid-level"


def test_fetch_beats_the_watchdog_on_every_completed_page(
    adapter: HimalayasAdapter,
    fixture_payload: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression for crawl 32170763256.

    The runner only beats around the whole fetch() call, so this adapter's
    paced window (~250 requests, 3s apart) ran far past the watchdog's 600s
    no-progress threshold without reaching an ingest batch. The watchdog
    hard-exited the aggregator phase - "last activity was
    himalayas:fetch-start" - and devpost, remoteok, arbeitnow and jobicy
    never got to run at all.
    """
    from crawlers import watchdog

    full_page_jobs = [
        {
            **fixture_payload["jobs"][0],
            "id": f"hm-beat-{index}",
            "url": f"https://himalayas.app/companies/nimbus/jobs/beat-{index}",
            "applicationLink": (f"https://himalayas.app/companies/nimbus/jobs/beat-{index}/apply"),
        }
        for index in range(20)
    ]

    def fake_get(url: str, *, params: dict) -> httpx.Response:
        jobs = full_page_jobs if params["offset"] < 40 else []
        request = httpx.Request("GET", url, params=params)
        return httpx.Response(200, json={"totalCount": 101767, "jobs": jobs}, request=request)

    beats: list[str] = []
    monkeypatch.setattr(adapter._client, "get", fake_get)
    monkeypatch.setattr(himalayas, "sleep", lambda _seconds: None)
    monkeypatch.setattr(watchdog, "beat", lambda activity: beats.append(activity))
    monkeypatch.setattr(himalayas, "watchdog_beat", lambda activity: beats.append(activity))

    adapter.fetch()

    # One beat per completed page request - the signal the watchdog needs to
    # tell "slow but alive" from "hung".
    assert beats == ["himalayas:page-1", "himalayas:page-2", "himalayas:page-3"]


def test_pacing_sleep_alone_does_not_beat_the_watchdog(
    adapter: HimalayasAdapter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A source that stops actually fetching must still be caught.

    Beats come from COMPLETED pages only, never from a pacing sleep, so
    silencing the watchdog cannot be bought with delay alone.
    """
    from crawlers import watchdog

    def dead_get(url: str, *, params: dict) -> httpx.Response:
        raise httpx.ConnectError("simulated dead source")

    beats: list[str] = []
    monkeypatch.setattr(adapter._client, "get", dead_get)
    monkeypatch.setattr(himalayas, "sleep", lambda _seconds: None)
    monkeypatch.setattr(watchdog, "beat", lambda activity: beats.append(activity))
    monkeypatch.setattr(himalayas, "watchdog_beat", lambda activity: beats.append(activity))

    adapter.fetch()

    assert beats == []
