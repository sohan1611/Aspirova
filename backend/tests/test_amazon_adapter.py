"""Unit tests for AmazonAdapter using a captured real search response.

The HTTP client is stubbed, so these tests never access amazon.jobs.
"""

import json
from datetime import timezone
from pathlib import Path

import httpx
import pytest

from core.adapters import RawListing
from crawlers.amazon import AmazonAdapter
from crawlers.common import content_hash

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "amazon_search_sample.json"


def _load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _raw_listing_for(job: dict) -> RawListing:
    source_url = f"https://www.amazon.jobs{job['job_path']}"
    return RawListing(
        source_slug="amazon",
        external_id=str(job["id"]),
        source_url=source_url,
        content_hash=content_hash(job),
        raw_payload=job,
    )


@pytest.fixture
def adapter() -> AmazonAdapter:
    return AmazonAdapter(board_token="amazon", company_name="Amazon")


@pytest.fixture
def fixture_payload() -> dict:
    return _load_fixture()


def test_adapter_identity(adapter: AmazonAdapter) -> None:
    assert adapter.source_slug == "amazon"
    assert adapter.requires_browser is False


def test_health_defaults_to_ok_before_any_fetch(adapter: AmazonAdapter) -> None:
    assert adapter.health() == "ok"


def test_fetch_returns_fixture_jobs_without_network(
    adapter: AmazonAdapter,
    fixture_payload: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_params: list[dict] = []

    def fake_get(url: str, *, params: dict) -> httpx.Response:
        request_params.append(params)
        request = httpx.Request("GET", url, params=params)
        return httpx.Response(200, json=fixture_payload, request=request)

    monkeypatch.setattr(adapter._client, "get", fake_get)
    monkeypatch.setattr("crawlers.amazon.time.sleep", lambda _seconds: None)

    raw_listings = adapter.fetch()
    by_id = {listing.external_id: listing for listing in raw_listings}

    assert len(raw_listings) == len(fixture_payload["jobs"])
    assert all(isinstance(listing, RawListing) for listing in raw_listings)
    for job in fixture_payload["jobs"]:
        external_id = str(job["id"])
        assert by_id[external_id].source_url == f"https://www.amazon.jobs{job['job_path']}"

    assert [params["base_query"] for params in request_params] == [
        "intern",
        "new grad",
        "graduate",
    ]
    assert all(params["result_limit"] == 100 for params in request_params)
    assert all(params["offset"] == 0 for params in request_params)
    assert all(params["sort"] == "recent" for params in request_params)
    assert adapter.health() == "ok"


def test_coverage_reports_capped_query_as_partial_without_summed_denominator(
    adapter: AmazonAdapter,
) -> None:
    adapter._declared_hits_by_query = {
        "intern": 192,
        "new grad": 0,
        "graduate": 301,
    }

    coverage = adapter.coverage()

    assert coverage["status"] == "partial"
    assert coverage["expected_total"] is None
    assert coverage["details"]["declared_hits_by_query"]["graduate"] == 301
    assert coverage["details"]["capped_queries"] == ["graduate"]
    assert "overlap" in coverage["note"]
    assert "not a valid distinct-listing denominator" in coverage["note"]


def test_coverage_reports_uncapped_queries_complete_without_summed_denominator(
    adapter: AmazonAdapter,
) -> None:
    adapter._declared_hits_by_query = {
        "intern": 192,
        "new grad": 0,
        "graduate": 293,
    }

    coverage = adapter.coverage()

    assert coverage["status"] == "complete"
    assert coverage["expected_total"] is None
    assert coverage["details"]["declared_hits_by_query"] == {
        "intern": 192,
        "new grad": 0,
        "graduate": 293,
    }
    assert "capped_queries" not in coverage["details"]


def test_parse_internship_job(adapter: AmazonAdapter, fixture_payload: dict) -> None:
    job = next(job for job in fixture_payload["jobs"] if "Intern" in job["title"])
    raw = _raw_listing_for(job)
    normalized = adapter.parse(raw)

    assert normalized.title == job["title"]
    assert normalized.company_name == "Amazon"
    assert normalized.company_name != job["company_name"]
    assert normalized.category == "internship"
    assert normalized.apply_url == raw.source_url
    assert normalized.apply_url != job["url_next_step"]
    assert normalized.location
    assert normalized.external_id == str(job["id"])
    assert normalized.deadline is None
    assert normalized.deadline_confidence == "unknown"
    assert normalized.posted_at is not None
    assert normalized.posted_at.tzinfo is not None
    assert normalized.posted_at.tzinfo == timezone.utc


def test_parse_remote_detection_handles_remote_sensing_and_virtual(
    adapter: AmazonAdapter,
    fixture_payload: dict,
) -> None:
    base_job = fixture_payload["jobs"][0]

    remote_sensing_job = {
        **base_job,
        "id": "remote-sensing",
        "title": "Remote Sensing Engineer",
        "normalized_location": "Seattle, WA, USA",
    }
    remote_sensing = adapter.parse(_raw_listing_for(remote_sensing_job))

    remote_job = {
        **base_job,
        "id": "remote-job",
        "title": "Remote Software Development Engineer",
        "normalized_location": "United States",
    }
    remote = adapter.parse(_raw_listing_for(remote_job))

    virtual_job = {
        **base_job,
        "id": "virtual-job",
        "title": "Software Development Engineer",
        "normalized_location": "Virtual Location - USA",
    }
    virtual = adapter.parse(_raw_listing_for(virtual_job))

    assert remote_sensing.is_remote is False
    assert remote.is_remote is True
    assert virtual.is_remote is True


def test_parse_odd_row_does_not_raise(adapter: AmazonAdapter) -> None:
    raw = RawListing(
        source_slug="amazon",
        external_id=None,
        source_url="https://www.amazon.jobs/en/jobs/unknown",
        content_hash=content_hash({}),
        raw_payload={},
    )

    normalized = adapter.parse(raw)

    assert normalized.title == ""
    assert normalized.location is None
    assert normalized.description_raw == ""
    assert normalized.posted_at is None
    assert normalized.apply_url == raw.source_url
