"""Unit tests for AmazonAdapter using a captured real search response.

The HTTP client is stubbed, so these tests never access amazon.jobs.
"""

import json
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
