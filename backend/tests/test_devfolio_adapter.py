"""Unit tests for DevfolioAdapter using a real-shaped public API payload."""

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from core.adapters import RawListing
from crawlers import devfolio
from crawlers.common import content_hash
from crawlers.devfolio import DevfolioAdapter
from pipeline.location_country import derive_country

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "devfolio_sample.json"


def _load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _raw_listing_for(hackathon: dict) -> RawListing:
    source_url = f"https://{hackathon['slug']}.devfolio.co"
    return RawListing(
        source_slug="devfolio",
        external_id=hackathon["uuid"],
        source_url=source_url,
        content_hash=content_hash(hackathon),
        raw_payload=hackathon,
    )


def _payload_for(items: list[dict], *, count: int | None = None) -> dict:
    return {
        "result": items,
        "count": len(items) if count is None else count,
        "pages": 1 if items else 0,
    }


@pytest.fixture
def adapter() -> DevfolioAdapter:
    return DevfolioAdapter()


@pytest.fixture
def fixture_payload() -> dict:
    return _load_fixture()


def test_adapter_identity_and_default_health(adapter: DevfolioAdapter) -> None:
    assert adapter.source_slug == "devfolio"
    assert adapter.requires_browser is False
    assert adapter.health() == "ok"


def test_parse_maps_real_shaped_record_to_hackathon_with_subdomain_apply_url(
    adapter: DevfolioAdapter,
    fixture_payload: dict,
) -> None:
    hackathon = fixture_payload["result"][0]
    normalized = adapter.parse(_raw_listing_for(hackathon))

    assert normalized.source_slug == "devfolio"
    assert normalized.external_id == hackathon["uuid"]
    assert normalized.category == "hackathon"
    assert normalized.company_name == "Devfolio"
    assert normalized.apply_url == "https://ethkochi.devfolio.co"
    assert normalized.source_url == "https://ethkochi.devfolio.co"
    assert normalized.deadline == datetime(2026, 9, 14, 12, 30, tzinfo=UTC)
    assert normalized.deadline_confidence == "explicit"
    assert normalized.meta["attribution"] == "via Devfolio"


def test_country_none_yields_null_country_not_india(
    adapter: DevfolioAdapter,
    fixture_payload: dict,
) -> None:
    hackathon = fixture_payload["result"][0]
    assert hackathon["city"] == "Kochi"
    assert hackathon["country"] is None

    normalized = adapter.parse(_raw_listing_for(hackathon))

    assert normalized.location is None
    assert derive_country(normalized.location) is None
    assert normalized.meta["country"] is None
    assert normalized.meta["city"] == "Kochi"


def test_state_is_kept_as_geography_not_lifecycle_status(
    adapter: DevfolioAdapter,
    fixture_payload: dict,
) -> None:
    hackathon = fixture_payload["result"][0]
    normalized = adapter.parse(_raw_listing_for(hackathon))

    assert normalized.meta["status"] == "publish"
    assert normalized.meta["geo_state"] == "Kerala"
    assert "state" not in normalized.meta


def test_team_and_popularity_fields_land_in_meta(
    adapter: DevfolioAdapter,
    fixture_payload: dict,
) -> None:
    hackathon = fixture_payload["result"][0]
    normalized = adapter.parse(_raw_listing_for(hackathon))

    assert normalized.meta["team_min"] == 1
    assert normalized.meta["team_size"] == 4
    assert normalized.meta["participants_count"] == 3269
    assert normalized.meta["themes"] == ["Web3", "Ethereum"]


def test_fetch_requests_only_open_and_upcoming_filters(
    adapter: DevfolioAdapter,
    fixture_payload: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_params: list[dict] = []
    sleep_calls: list[float] = []

    def fake_get(url: str, *, params: dict) -> httpx.Response:
        request_params.append(params)
        payload = (
            fixture_payload if params["filter"] == "application_open" else _payload_for([], count=0)
        )
        request = httpx.Request("GET", url, params=params)
        return httpx.Response(200, json=payload, request=request)

    monkeypatch.setattr(adapter._client, "get", fake_get)
    monkeypatch.setattr(devfolio, "sleep", lambda seconds: sleep_calls.append(seconds))

    raw_listings = adapter.fetch()

    assert [listing.external_id for listing in raw_listings] == [
        "devfolio-ethkochi-2026",
        "devfolio-codestorm-2026",
    ]
    assert [params["filter"] for params in request_params] == [
        "application_open",
        "upcoming",
    ]
    assert all(params["limit"] == 30 for params in request_params)
    assert request_params == [
        {"filter": "application_open", "page": 1, "limit": 30},
        {"filter": "upcoming", "page": 1, "limit": 30},
    ]
    assert sleep_calls == [1.0]
    assert adapter.health() == "ok"


def test_empty_well_formed_result_is_ok_not_broken(
    adapter: DevfolioAdapter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_get(url: str, *, params: dict) -> httpx.Response:
        request = httpx.Request("GET", url, params=params)
        return httpx.Response(200, json=_payload_for([], count=0), request=request)

    monkeypatch.setattr(adapter._client, "get", fake_get)
    monkeypatch.setattr(devfolio, "sleep", lambda _seconds: None)

    assert adapter.fetch() == []
    assert adapter.health() == "ok"
    assert adapter.coverage()["status"] == "complete"


@pytest.mark.parametrize("payload", [["not", "an", "object"], {"count": 1, "pages": 1}])
def test_malformed_response_shape_is_broken(
    adapter: DevfolioAdapter,
    payload: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_get(url: str, *, params: dict) -> httpx.Response:
        request = httpx.Request("GET", url, params=params)
        return httpx.Response(200, json=payload, request=request)

    monkeypatch.setattr(adapter._client, "get", fake_get)

    assert adapter.fetch() == []
    assert adapter.health() == "broken"
    assert adapter.coverage()["status"] == "partial"


def test_transient_429_is_retried_by_shared_helper_then_succeeds(
    adapter: DevfolioAdapter,
    fixture_payload: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_params: list[dict] = []
    sleep_calls: list[float] = []
    first_attempt = True

    def fake_get(url: str, *, params: dict) -> httpx.Response:
        nonlocal first_attempt
        request_params.append(params)
        request = httpx.Request("GET", url, params=params)
        if params["filter"] == "application_open" and first_attempt:
            first_attempt = False
            return httpx.Response(429, text="Too Many Requests", request=request)
        payload = (
            _payload_for([fixture_payload["result"][0]], count=1)
            if params["filter"] == "application_open"
            else _payload_for([], count=0)
        )
        return httpx.Response(200, json=payload, request=request)

    monkeypatch.setattr(adapter._client, "get", fake_get)
    monkeypatch.setattr(devfolio, "sleep", lambda seconds: sleep_calls.append(seconds))
    monkeypatch.setattr("crawlers.common.random.uniform", lambda _start, _end: 0.0)

    raw_listings = adapter.fetch()

    assert [listing.external_id for listing in raw_listings] == ["devfolio-ethkochi-2026"]
    assert [params["filter"] for params in request_params] == [
        "application_open",
        "application_open",
        "upcoming",
    ]
    assert sleep_calls == [2.0, 1.0]
    assert adapter.health() == "ok"
    coverage = adapter.coverage()
    assert coverage["details"]["requests_made"] == 3
    assert coverage["details"]["retry_attempts"] == 1
    assert coverage["details"]["retry_reasons"] == ["http_429"]


def test_coverage_reports_per_filter_fetched_and_declared_without_total(
    adapter: DevfolioAdapter,
    fixture_payload: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_get(url: str, *, params: dict) -> httpx.Response:
        payload = (
            {"result": fixture_payload["result"], "count": 27, "pages": 1}
            if params["filter"] == "application_open"
            else {"result": [fixture_payload["result"][0]], "count": 5, "pages": 1}
        )
        request = httpx.Request("GET", url, params=params)
        return httpx.Response(200, json=payload, request=request)

    monkeypatch.setattr(adapter._client, "get", fake_get)
    monkeypatch.setattr(devfolio, "sleep", lambda _seconds: None)

    adapter.fetch()
    coverage = adapter.coverage()

    assert coverage["mode"] == "declared_filter_totals"
    assert coverage["expected_total"] is None
    assert coverage["status"] == "complete"
    assert "filters overlap" in coverage["note"]
    assert coverage["details"]["filters"] == {
        "application_open": {"fetched": 2, "declared": 27},
        "upcoming": {"fetched": 1, "declared": 5},
    }


def test_dedupe_same_uuid_across_filters_yields_one_listing(
    adapter: DevfolioAdapter,
    fixture_payload: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    duplicate = fixture_payload["result"][0]

    def fake_get(url: str, *, params: dict) -> httpx.Response:
        request = httpx.Request("GET", url, params=params)
        return httpx.Response(200, json=_payload_for([duplicate], count=1), request=request)

    monkeypatch.setattr(adapter._client, "get", fake_get)
    monkeypatch.setattr(devfolio, "sleep", lambda _seconds: None)

    raw_listings = adapter.fetch()

    assert [listing.external_id for listing in raw_listings] == ["devfolio-ethkochi-2026"]
    assert adapter.health() == "ok"
    assert adapter.coverage()["details"]["fetched_by_filter"] == {
        "application_open": 1,
        "upcoming": 1,
    }


def test_location_does_not_repeat_city_state_country_from_the_venue_address() -> None:
    """Devfolio's `location` is a full venue address that already ends in
    city/state/country. Appending those again produced a doubled string on the
    live API:

        "Mar Athanasius College of Engineering Kothamangalam, Road,
         Kothamangalam, Kerala, India, Kothamangalam, Kerala, India"

    Exact-match de-duplication cannot catch it, because "Kothamangalam" is
    embedded inside the longer address rather than being an equal part.
    """
    from crawlers.devfolio import _display_location

    location = _display_location(
        {
            "is_online": False,
            "location": (
                "Mar Athanasius College of Engineering Kothamangalam, Road, "
                "Kothamangalam, Kerala, India"
            ),
            "city": "Kothamangalam",
            "state": "Kerala",
            "country": "India",
        }
    )

    assert location == "Kothamangalam, Kerala, India"
    assert location.lower().count("kerala") == 1
    assert location.lower().count("india") == 1
    assert "Road" not in location
