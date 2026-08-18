"""Unit tests for ArbeitnowAdapter using a fixture payload."""

import json
from pathlib import Path

import httpx
import pytest

from core.adapters import RawListing
from crawlers.arbeitnow import ArbeitnowAdapter
from crawlers.common import content_hash

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "arbeitnow_sample.json"


def _load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _raw_listing_for(job: dict) -> RawListing:
    return RawListing(
        source_slug="arbeitnow",
        external_id=str(job["slug"]),
        source_url=job["url"],
        content_hash=content_hash(job),
        raw_payload=job,
    )


@pytest.fixture
def adapter() -> ArbeitnowAdapter:
    return ArbeitnowAdapter()


@pytest.fixture
def fixture_payload() -> dict:
    return _load_fixture()


def test_adapter_identity_and_default_health(adapter: ArbeitnowAdapter) -> None:
    assert adapter.source_slug == "arbeitnow"
    assert adapter.requires_browser is False
    assert adapter.health() == "ok"


def test_fetch_filters_senior_titles_before_returning_raw_listings(
    adapter: ArbeitnowAdapter,
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

    assert [listing.external_id for listing in raw_listings] == [
        "junior-software-engineer-alpha",
        "graduate-trainee-developer-gamma",
    ]
    assert adapter.filter_counts() == {
        "raw_count": 4,
        "student_relevant_count": 2,
        "filtered_out": 2,
    }
    assert request_params == [{"page": 1, "per_page": 175}]
    assert adapter.health() == "ok"


def test_fetch_retries_transient_rate_limit_before_marking_degraded(
    adapter: ArbeitnowAdapter,
    fixture_payload: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page_one = {
        "data": [fixture_payload["data"][0]],
        "links": {"next": "https://www.arbeitnow.com/api/job-board-api?page=2"},
    }
    page_two = {"data": [fixture_payload["data"][2]], "links": {"next": None}}
    responses = [(200, page_one), (429, None), (200, page_two)]
    request_params: list[dict] = []

    def fake_get(url: str, *, params: dict) -> httpx.Response:
        request_params.append(params)
        status_code, payload = responses.pop(0)
        request = httpx.Request("GET", url, params=params)
        if payload is None:
            return httpx.Response(status_code, text="Too Many Requests", request=request)
        return httpx.Response(status_code, json=payload, request=request)

    monkeypatch.setattr(adapter._client, "get", fake_get)
    monkeypatch.setattr("crawlers.arbeitnow.sleep", lambda _seconds: None)

    raw_listings = adapter.fetch()

    assert [listing.external_id for listing in raw_listings] == [
        "junior-software-engineer-alpha",
        "graduate-trainee-developer-gamma",
    ]
    assert request_params == [
        {"page": 1, "per_page": 175},
        {"page": 2, "per_page": 175},
        {"page": 2, "per_page": 175},
    ]
    coverage = adapter.coverage()
    assert coverage["details"]["requests_made"] == 3
    assert coverage["details"]["retry_attempts"] == 1
    assert coverage["details"]["retry_reasons"] == ["http_429"]
    assert coverage["details"]["terminal_reason"] is None
    assert adapter.health() == "ok"


def test_parse_maps_original_url_category_and_remote_flag(
    adapter: ArbeitnowAdapter, fixture_payload: dict
) -> None:
    kept_job = fixture_payload["data"][2]
    normalized = adapter.parse(_raw_listing_for(kept_job))

    assert normalized.title == "Graduate Trainee Developer"
    assert normalized.company_name == "Gamma GmbH"
    assert normalized.category == "internship"
    assert normalized.apply_url == kept_job["url"]
    assert normalized.is_remote is False
    assert normalized.meta == {
        "platform": "arbeitnow",
        "tags": ["Graduate"],
        "job_types": ["Trainee"],
    }
