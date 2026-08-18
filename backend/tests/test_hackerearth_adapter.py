"""Unit tests for HackerEarthAdapter using a fixture payload."""

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from core.adapters import RawListing
from crawlers.common import content_hash
from crawlers.hackerearth import HackerEarthAdapter

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "hackerearth_sample.json"


def _load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _raw_listing_for(event: dict) -> RawListing:
    source_url = event["url"]
    if source_url.startswith("/"):
        source_url = f"https://www.hackerearth.com{source_url}"
    return RawListing(
        source_slug="hackerearth",
        external_id=source_url,
        source_url=source_url,
        content_hash=content_hash(event),
        raw_payload=event,
    )


@pytest.fixture
def adapter() -> HackerEarthAdapter:
    return HackerEarthAdapter()


@pytest.fixture
def fixture_payload() -> dict:
    return _load_fixture()


def test_adapter_identity_and_default_health(adapter: HackerEarthAdapter) -> None:
    assert adapter.source_slug == "hackerearth"
    assert adapter.requires_browser is False
    assert adapter.health() == "ok"


def test_fetch_returns_fixture_events_without_network(
    adapter: HackerEarthAdapter,
    fixture_payload: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_get(url: str) -> httpx.Response:
        request = httpx.Request("GET", url)
        return httpx.Response(200, json=fixture_payload, request=request)

    monkeypatch.setattr(adapter._client, "get", fake_get)

    raw_listings = adapter.fetch()

    assert len(raw_listings) == 3
    assert raw_listings[0].source_url == (
        "https://www.hackerearth.com/challenges/competitive/august-circuits-26/"
    )
    assert adapter.coverage()["details"] == {"raw_count": 3}
    assert adapter.health() == "ok"


def test_parse_maps_monthly_challenge_to_competition(
    adapter: HackerEarthAdapter, fixture_payload: dict
) -> None:
    event = fixture_payload["response"][0]
    normalized = adapter.parse(_raw_listing_for(event))

    assert normalized.category == "competition"
    assert normalized.company_name == "HackerEarth"
    assert normalized.location == "Online"
    assert normalized.is_remote is True
    assert (
        normalized.apply_url
        == "https://www.hackerearth.com/challenges/competitive/august-circuits-26/"
    )
    assert normalized.deadline == datetime(2026, 9, 16, 2, 40, tzinfo=UTC)
    assert normalized.deadline_confidence == "explicit"


def test_parse_maps_hackathon_challenge_type_to_hackathon(
    adapter: HackerEarthAdapter, fixture_payload: dict
) -> None:
    event = fixture_payload["response"][1]
    normalized = adapter.parse(_raw_listing_for(event))

    assert normalized.category == "hackathon"
    assert normalized.apply_url == event["url"]
