"""Unit tests for UnstopAdapter using a captured real API response."""

import json
from datetime import datetime
from pathlib import Path

import httpx
import pytest

from core.adapters import RawListing
from crawlers.common import content_hash
from crawlers.unstop import UnstopAdapter

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "unstop_sample.json"


def _load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _fixture_items(payload: dict) -> list[dict]:
    return payload["data"]["data"]


def _raw_listing_for(opportunity: dict) -> RawListing:
    return RawListing(
        source_slug="unstop",
        external_id=str(opportunity["id"]),
        source_url=opportunity["seo_url"],
        content_hash=content_hash(opportunity),
        raw_payload=opportunity,
    )


@pytest.fixture
def adapter() -> UnstopAdapter:
    return UnstopAdapter()


@pytest.fixture
def fixture_payload() -> dict:
    return _load_fixture()


def test_adapter_identity_and_default_health(adapter: UnstopAdapter) -> None:
    assert adapter.source_slug == "unstop"
    assert adapter.requires_browser is False
    assert adapter.health() == "ok"


def test_fetch_returns_fixture_opportunities_and_deduplicates_across_types(
    adapter: UnstopAdapter,
    fixture_payload: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_params: list[dict] = []

    def fake_get(url: str, *, params: dict) -> httpx.Response:
        request_params.append(params)
        payload = fixture_payload if params["page"] == 1 else {"data": {"data": []}}
        request = httpx.Request("GET", url, params=params)
        return httpx.Response(200, json=payload, request=request)

    monkeypatch.setattr(adapter._client, "get", fake_get)

    raw_listings = adapter.fetch()
    fixture_items = _fixture_items(fixture_payload)

    assert len(raw_listings) == len(fixture_items)
    assert {listing.external_id for listing in raw_listings} == {
        str(opportunity["id"]) for opportunity in fixture_items
    }
    assert request_params == [
        {"opportunity": "competitions", "per_page": 100, "page": 1},
        {"opportunity": "competitions", "per_page": 100, "page": 2},
        {"opportunity": "hackathons", "per_page": 100, "page": 1},
        {"opportunity": "hackathons", "per_page": 100, "page": 2},
    ]
    assert adapter.health() == "ok"


def test_fetch_malformed_listing_container_degrades_without_raising(
    adapter: UnstopAdapter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_get(url: str, *, params: dict) -> httpx.Response:
        request = httpx.Request("GET", url, params=params)
        return httpx.Response(200, json={"data": {}}, request=request)

    monkeypatch.setattr(adapter._client, "get", fake_get)

    assert adapter.fetch() == []
    assert adapter.health() == "degraded"


@pytest.mark.parametrize(
    ("fixture_index", "expected_category"),
    [(0, "competition"), (1, "hackathon")],
)
def test_parse_maps_category_deadline_organizer_and_meta(
    adapter: UnstopAdapter,
    fixture_payload: dict,
    fixture_index: int,
    expected_category: str,
) -> None:
    opportunity = _fixture_items(fixture_payload)[fixture_index]
    normalized = adapter.parse(_raw_listing_for(opportunity))

    assert normalized.category == expected_category
    assert normalized.company_name == opportunity["organisation"]["name"]
    assert normalized.company_domain is None
    assert normalized.apply_url == opportunity["seo_url"]
    assert normalized.deadline == datetime.fromisoformat(opportunity["end_date"])
    assert normalized.deadline_confidence == "explicit"
    assert normalized.meta == {
        "platform": "unstop",
        "organizer": opportunity["organisation"]["name"],
        "type": opportunity["type"],
        "subtype": opportunity["subtype"],
        "mode": opportunity["region"],
        "prizes": opportunity["prizes"],
        "register_count": opportunity["registerCount"],
        "skills": opportunity["required_skills"],
        "is_paid": opportunity["isPaid"],
    }


@pytest.mark.parametrize("date_value", [None, "not a real date"])
def test_parse_handles_missing_and_weird_dates_without_raising(
    adapter: UnstopAdapter,
    fixture_payload: dict,
    date_value: str | None,
) -> None:
    opportunity = {
        **_fixture_items(fixture_payload)[0],
        "end_date": date_value,
    }

    normalized = adapter.parse(_raw_listing_for(opportunity))

    assert normalized.deadline is None
    assert normalized.deadline_confidence == "unknown"
