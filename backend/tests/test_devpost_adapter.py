"""Unit tests for DevpostAdapter using a captured real API response."""

import json
from datetime import datetime
from pathlib import Path

import httpx
import pytest

from core.adapters import RawListing
from crawlers.common import content_hash
from crawlers.devpost import DevpostAdapter

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "devpost_sample.json"


def _load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _raw_listing_for(hackathon: dict) -> RawListing:
    return RawListing(
        source_slug="devpost",
        external_id=str(hackathon["id"]),
        source_url=hackathon["url"],
        content_hash=content_hash(hackathon),
        raw_payload=hackathon,
    )


@pytest.fixture
def adapter() -> DevpostAdapter:
    return DevpostAdapter()


@pytest.fixture
def fixture_payload() -> dict:
    return _load_fixture()


def test_adapter_identity_and_default_health(adapter: DevpostAdapter) -> None:
    assert adapter.source_slug == "devpost"
    assert adapter.requires_browser is False
    assert adapter.health() == "ok"


def test_fetch_returns_fixture_hackathons_without_network(
    adapter: DevpostAdapter,
    fixture_payload: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_params: list[dict] = []

    def fake_get(url: str, *, params: dict) -> httpx.Response:
        request_params.append(params)
        payload = fixture_payload if params["page"] == 1 else {"hackathons": [], "meta": {}}
        request = httpx.Request("GET", url, params=params)
        return httpx.Response(200, json=payload, request=request)

    monkeypatch.setattr(adapter._client, "get", fake_get)

    raw_listings = adapter.fetch()

    assert len(raw_listings) == len(fixture_payload["hackathons"])
    assert {listing.external_id for listing in raw_listings} == {
        str(hackathon["id"]) for hackathon in fixture_payload["hackathons"]
    }
    assert request_params == [
        {"status[]": "open", "page": 1},
        {"status[]": "open", "page": 2},
    ]
    assert adapter.health() == "ok"


def test_fetch_malformed_listing_container_degrades_without_raising(
    adapter: DevpostAdapter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_get(url: str, *, params: dict) -> httpx.Response:
        request = httpx.Request("GET", url, params=params)
        return httpx.Response(200, json={"meta": {}}, request=request)

    monkeypatch.setattr(adapter._client, "get", fake_get)

    assert adapter.fetch() == []
    assert adapter.health() == "degraded"


def test_parse_maps_hackathon_deadline_organizer_and_meta(
    adapter: DevpostAdapter, fixture_payload: dict
) -> None:
    hackathon = fixture_payload["hackathons"][0]
    normalized = adapter.parse(_raw_listing_for(hackathon))

    assert normalized.category == "hackathon"
    assert normalized.company_name == hackathon["organization_name"]
    assert normalized.company_domain is None
    assert normalized.apply_url == hackathon["url"]
    assert normalized.deadline == datetime(2026, 8, 17)
    assert normalized.deadline_confidence == "explicit"
    assert normalized.meta == {
        "platform": "devpost",
        "organizer": hackathon["organization_name"],
        "prize": "$2,000,000",
        "themes": [theme["name"] for theme in hackathon["themes"]],
        "registrations_count": hackathon["registrations_count"],
        "mode": hackathon["displayed_location"]["location"],
        "dates": hackathon["submission_period_dates"],
    }


@pytest.mark.parametrize(
    ("date_value", "expected_deadline"),
    [
        ("Aug 17, 2026", datetime(2026, 8, 17)),
        ("not a real date", None),
        (None, None),
    ],
)
def test_parse_handles_single_missing_and_weird_dates(
    adapter: DevpostAdapter,
    fixture_payload: dict,
    date_value: str | None,
    expected_deadline: datetime | None,
) -> None:
    hackathon = {
        **fixture_payload["hackathons"][0],
        "submission_period_dates": date_value,
    }

    normalized = adapter.parse(_raw_listing_for(hackathon))

    assert normalized.deadline == expected_deadline
    expected_confidence = "explicit" if expected_deadline is not None else "unknown"
    assert normalized.deadline_confidence == expected_confidence
