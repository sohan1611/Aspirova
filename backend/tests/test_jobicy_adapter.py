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
    assert adapter.coverage()["expected_total"] == 4
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
