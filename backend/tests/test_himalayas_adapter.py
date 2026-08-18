"""Unit tests for HimalayasAdapter using a fixture payload."""

import json
from pathlib import Path

import httpx
import pytest

from core.adapters import RawListing
from crawlers.common import content_hash
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
    assert adapter.coverage()["expected_total"] == 102211
    assert request_params == [{"limit": 20, "offset": 0}]


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
