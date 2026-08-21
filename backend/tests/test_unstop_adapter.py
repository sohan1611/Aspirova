"""Unit tests for UnstopAdapter using a captured real API response."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from core.adapters import RawListing
from crawlers import unstop
from crawlers import runner
from crawlers.common import content_hash
from crawlers.unstop import UnstopAdapter
from pipeline.location_country import derive_country

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


def _payload_for(items: list[dict], *, total: int | None = None) -> dict:
    data: dict[str, object] = {"data": items}
    if total is not None:
        data["total"] = total
    return {"data": data}


def _open_fixture_item(fixture_payload: dict, opportunity_type: str, item_id: object) -> dict:
    deadline = datetime.now(UTC) + timedelta(days=30)
    return {
        **_fixture_items(fixture_payload)[0],
        "id": item_id,
        "seo_url": f"https://unstop.com/{opportunity_type}/fixture-{item_id}",
        "end_date": deadline.isoformat(),
        "regnRequirements": {"end_regn_dt": deadline.isoformat()},
    }


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


def test_fetch_stops_at_its_deadline_before_requesting_the_next_page(
    adapter: UnstopAdapter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_params: list[dict] = []

    def fake_get(url: str, *, params: dict) -> httpx.Response:
        request_params.append(params)
        request = httpx.Request("GET", url, params=params)
        return httpx.Response(200, json={"data": {"data": []}}, request=request)

    monkeypatch.setattr(adapter._client, "get", fake_get)
    clock_values = iter([0.0, 1.0])
    monkeypatch.setattr(unstop, "monotonic", lambda: next(clock_values))

    raw_listings = adapter.fetch(deadline_monotonic=0.5)

    assert raw_listings == []
    assert adapter.stopped_early is True
    assert request_params == [
        {
            "opportunity": "internships",
            "oppstatus": "open",
            "per_page": 300,
            "page": 1,
        },
    ]


def test_fetch_returns_fixture_opportunities_and_deduplicates_across_types(
    adapter: UnstopAdapter,
    fixture_payload: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_params: list[dict] = []
    fixture_items = _fixture_items(fixture_payload)
    now = datetime.now(UTC)
    for days_until_deadline, opportunity in enumerate(fixture_items, start=1):
        opportunity["end_date"] = (now + timedelta(days=days_until_deadline)).isoformat()

    def fake_get(url: str, *, params: dict) -> httpx.Response:
        request_params.append(params)
        payload = fixture_payload if params["page"] == 1 else {"data": {"data": []}}
        request = httpx.Request("GET", url, params=params)
        return httpx.Response(200, json=payload, request=request)

    monkeypatch.setattr(adapter._client, "get", fake_get)

    raw_listings = adapter.fetch()

    assert len(raw_listings) == len(fixture_items)
    assert {listing.external_id for listing in raw_listings} == {
        str(opportunity["id"]) for opportunity in fixture_items
    }
    assert request_params == [
        {
            "opportunity": "internships",
            "oppstatus": "open",
            "per_page": 300,
            "page": 1,
        },
        {
            "opportunity": "competitions",
            "oppstatus": "open",
            "per_page": 300,
            "page": 1,
        },
        {
            "opportunity": "hackathons",
            "oppstatus": "open",
            "per_page": 300,
            "page": 1,
        },
        {"opportunity": "jobs", "oppstatus": "open", "per_page": 300, "page": 1},
    ]
    assert adapter.health() == "ok"


def test_fetch_retries_transient_request_error_and_completes_type(
    adapter: UnstopAdapter,
    fixture_payload: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    internship = _open_fixture_item(fixture_payload, "internships", "internship-1")
    request_params: list[dict] = []
    sleep_calls: list[float] = []
    failed_once = False

    def fake_get(url: str, *, params: dict) -> httpx.Response:
        nonlocal failed_once
        request_params.append(params)
        request = httpx.Request("GET", url, params=params)
        if params["opportunity"] == "internships" and not failed_once:
            failed_once = True
            raise httpx.RequestError("temporary network blip", request=request)

        payload = (
            _payload_for([internship], total=1)
            if params["opportunity"] == "internships"
            else _payload_for([], total=0)
        )
        return httpx.Response(200, json=payload, request=request)

    monkeypatch.setattr(adapter._client, "get", fake_get)
    monkeypatch.setattr(unstop, "sleep", lambda seconds: sleep_calls.append(seconds))
    monkeypatch.setattr("crawlers.common.random.uniform", lambda _start, _end: 0.0)

    raw_listings = adapter.fetch()

    assert [listing.external_id for listing in raw_listings] == ["internship-1"]
    assert adapter.health() == "ok"
    coverage = adapter.coverage()
    assert coverage["status"] == "complete"
    assert coverage["details"]["fully_paged_types"] == list(unstop._OPPORTUNITY_TYPES)
    assert coverage["details"]["retry_attempts"] == 1
    assert coverage["details"]["retry_reasons"] == ["request_error"]
    assert coverage["details"]["requests_made"] == 5
    assert sleep_calls == [2.0]
    assert [params["opportunity"] for params in request_params] == [
        "internships",
        "internships",
        "competitions",
        "hackathons",
        "jobs",
    ]


def test_fetch_persistent_request_error_marks_one_type_incomplete_and_continues(
    adapter: UnstopAdapter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_params: list[dict] = []
    sleep_calls: list[float] = []

    def fake_get(url: str, *, params: dict) -> httpx.Response:
        request_params.append(params)
        request = httpx.Request("GET", url, params=params)
        if params["opportunity"] == "internships":
            raise httpx.RequestError("network unavailable", request=request)
        return httpx.Response(200, json=_payload_for([], total=0), request=request)

    monkeypatch.setattr(adapter._client, "get", fake_get)
    monkeypatch.setattr(unstop, "sleep", lambda seconds: sleep_calls.append(seconds))
    monkeypatch.setattr("crawlers.common.random.uniform", lambda _start, _end: 0.0)

    raw_listings = adapter.fetch()

    assert raw_listings == []
    assert adapter.health() == "degraded"
    coverage = adapter.coverage()
    assert coverage["status"] == "partial"
    assert coverage["details"]["fully_paged_types"] == [
        "competitions",
        "hackathons",
        "jobs",
    ]
    assert coverage["details"]["incomplete_type_reasons"] == {"internships": "request_error"}
    assert coverage["details"]["retry_attempts"] == 2
    assert coverage["details"]["retry_reasons"] == ["request_error", "request_error"]
    assert coverage["details"]["requests_made"] == 6
    assert sleep_calls == [2.0, 4.0]
    assert [params["opportunity"] for params in request_params] == [
        "internships",
        "internships",
        "internships",
        "competitions",
        "hackathons",
        "jobs",
    ]


def test_fetch_http_404_marks_source_broken_and_stops(
    adapter: UnstopAdapter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_params: list[dict] = []

    def fake_get(url: str, *, params: dict) -> httpx.Response:
        request_params.append(params)
        request = httpx.Request("GET", url, params=params)
        return httpx.Response(404, text="Not Found", request=request)

    monkeypatch.setattr(adapter._client, "get", fake_get)

    assert adapter.fetch() == []
    assert adapter.health() == "broken"
    coverage = adapter.coverage()
    assert coverage["status"] == "partial"
    assert coverage["details"]["fully_paged_types"] == []
    assert coverage["details"]["incomplete_type_reasons"] == {
        "internships": "http_404",
        "competitions": "not_reached",
        "hackathons": "not_reached",
        "jobs": "not_reached",
    }
    assert coverage["details"]["requests_made"] == 1
    assert "retry_attempts" not in coverage["details"]
    assert [params["opportunity"] for params in request_params] == ["internships"]


def test_coverage_reports_overlapping_type_totals_without_summed_denominator(
    adapter: UnstopAdapter,
) -> None:
    adapter._declared_totals = {
        "internships": 786,
        "competitions": 305,
        "hackathons": 104,
        "jobs": 1097,
    }
    adapter._fully_paged_types = set(unstop._OPPORTUNITY_TYPES)

    coverage = adapter.coverage()

    assert coverage["mode"] == "declared_type_totals"
    assert coverage["expected_total"] is None
    assert coverage["status"] == "complete"
    assert coverage["details"]["declared_totals_by_type"] == {
        "internships": 786,
        "competitions": 305,
        "hackathons": 104,
        "jobs": 1097,
    }
    assert "types overlap" in coverage["note"]
    assert "not a valid distinct-listing denominator" in coverage["note"]

    record = runner._coverage_from_adapter(adapter, "unstop", 2186, health="ok")
    line = runner._coverage_line("unstop", record)
    assert record["expected_total"] is None
    assert "2186/2292" not in line
    assert line == (
        "COVERAGE: unstop 2186 (complete - Unstop opportunity types overlap, "
        "so summed per-type totals are not a valid distinct-listing denominator.)"
    )


def test_coverage_reports_unpaged_unstop_type_as_partial_without_ratio(
    adapter: UnstopAdapter,
) -> None:
    adapter._declared_totals = {
        "internships": 786,
        "competitions": 305,
        "hackathons": 104,
        "jobs": 1097,
    }
    adapter._fully_paged_types = {"internships", "competitions", "hackathons"}
    adapter._incomplete_type_reasons = {"jobs": "stopped_early"}

    coverage = adapter.coverage()

    assert coverage["expected_total"] is None
    assert coverage["status"] == "partial"
    assert coverage["details"]["incomplete_type_reasons"] == {"jobs": "stopped_early"}


def test_fetch_skips_internship_deadlines_older_than_grace_period(
    adapter: UnstopAdapter,
    fixture_payload: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture_item = {
        **_fixture_items(fixture_payload)[0],
        "type": "internships",
    }
    now = datetime.now(UTC)
    items = [
        {
            **fixture_item,
            "id": 1,
            "seo_url": "https://unstop.com/internships/future-aware-1",
            "end_date": (now + timedelta(days=1)).isoformat(),
        },
        {
            **fixture_item,
            "id": 2,
            "regn_open": 0,
            "status": "CLOSED",
            "seo_url": "https://unstop.com/internships/recently-closed-2",
            "end_date": (now - timedelta(days=3)).isoformat(),
        },
        {
            **fixture_item,
            "id": 3,
            "seo_url": "https://unstop.com/internships/expired-3",
            "end_date": (now - timedelta(days=20)).isoformat(),
        },
        {
            **fixture_item,
            "id": 4,
            "regn_open": 0,
            "status": "CLOSED",
            "seo_url": "https://unstop.com/internships/missing-4",
            "end_date": None,
        },
        {
            **fixture_item,
            "id": 5,
            "seo_url": "https://unstop.com/internships/invalid-5",
            "end_date": "not a real date",
        },
        {
            **fixture_item,
            "id": 6,
            "seo_url": "https://unstop.com/internships/future-naive-6",
            "end_date": (now + timedelta(days=2)).replace(tzinfo=None).isoformat(),
        },
    ]

    def fake_get(url: str, *, params: dict) -> httpx.Response:
        is_first_internship_page = params["opportunity"] == "internships" and params["page"] == 1
        payload = {"data": {"data": items if is_first_internship_page else []}}
        request = httpx.Request("GET", url, params=params)
        return httpx.Response(200, json=payload, request=request)

    monkeypatch.setattr(adapter._client, "get", fake_get)

    raw_listings = adapter.fetch()

    assert {listing.external_id for listing in raw_listings} == {
        "1",
        "2",
        "4",
        "5",
        "6",
    }
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
        "offers_ppi": False,
        "offers_ppo": False,
        "register_count": opportunity["registerCount"],
        "skills": [skill["skill_name"] for skill in opportunity["required_skills"]],
        "is_paid": opportunity["isPaid"],
    }


def test_parse_uses_address_country_name_for_offline_location(
    adapter: UnstopAdapter,
    fixture_payload: dict,
) -> None:
    opportunity = _fixture_items(fixture_payload)[1]

    normalized = adapter.parse(_raw_listing_for(opportunity))

    assert normalized.location == "Ghaziabad, Uttar Pradesh, India"
    assert normalized.is_remote is False
    assert derive_country(normalized.location) == "IN"


def test_parse_maps_online_location_without_country(
    adapter: UnstopAdapter,
    fixture_payload: dict,
) -> None:
    opportunity = _fixture_items(fixture_payload)[0]

    normalized = adapter.parse(_raw_listing_for(opportunity))

    assert normalized.location == "Online"
    assert normalized.is_remote is True
    assert derive_country(normalized.location) is None


@pytest.mark.parametrize(
    "address",
    [
        None,
        {"city": " ", "state": "", "country": {"name": " "}},
    ],
)
def test_parse_maps_offline_missing_or_blank_address_to_no_location(
    adapter: UnstopAdapter,
    fixture_payload: dict,
    address: dict | None,
) -> None:
    opportunity = {
        **_fixture_items(fixture_payload)[1],
        "region": "offline",
    }
    if address is None:
        opportunity.pop("address_with_country_logo", None)
    else:
        opportunity["address_with_country_logo"] = address

    normalized = adapter.parse(_raw_listing_for(opportunity))

    assert normalized.location is None
    assert normalized.is_remote is False


@pytest.mark.parametrize(
    ("address", "expected_location"),
    [
        (None, None),
        ("not an object", None),
        ({"city": "Kyoto", "state": "Kyoto", "country": None}, "Kyoto, Kyoto"),
        ({"city": "Tokyo", "state": "", "country": "Japan"}, "Tokyo, Japan"),
        ({"city": "Pune", "state": "Maharashtra", "country": "IN"}, "Pune, Maharashtra"),
    ],
)
def test_parse_handles_malformed_address_payload_without_raising(
    adapter: UnstopAdapter,
    fixture_payload: dict,
    address: object,
    expected_location: str | None,
) -> None:
    opportunity = {
        **_fixture_items(fixture_payload)[1],
        "region": "offline",
        "address_with_country_logo": address,
    }

    normalized = adapter.parse(_raw_listing_for(opportunity))

    assert normalized.location == expected_location
    assert normalized.is_remote is False


def test_parse_maps_internship_deadline_organizer_and_meta(
    adapter: UnstopAdapter,
    fixture_payload: dict,
) -> None:
    opportunity = {
        **_fixture_items(fixture_payload)[0],
        "title": "Software Development Internship",
        "seo_url": "https://unstop.com/internships/software-development-internship-1716244",
        # Unstop returns internships with type="jobs"; the adapter records the
        # search opportunity it came from so category is derived correctly.
        "type": "jobs",
        "_aspirova_opportunity": "internships",
        "prizes": [
            {"pre_placement_internship": 1},
            {"pre_placement_opportunity": 1},
        ],
    }

    normalized = adapter.parse(_raw_listing_for(opportunity))

    assert normalized.category == "internship"
    assert normalized.company_name == opportunity["organisation"]["name"]
    assert normalized.location == "Online"
    assert normalized.deadline == datetime.fromisoformat(opportunity["end_date"])
    assert normalized.deadline_confidence == "explicit"
    assert normalized.meta == {
        "platform": "unstop",
        "organizer": opportunity["organisation"]["name"],
        "type": "jobs",
        "subtype": opportunity["subtype"],
        "mode": opportunity["region"],
        "prizes": [
            {
                "rank": prize.get("rank"),
                "cash": prize.get("cash"),
                "currency": prize.get("currency"),
            }
            for prize in opportunity["prizes"]
        ],
        "offers_ppi": True,
        "offers_ppo": True,
        "register_count": opportunity["registerCount"],
        "skills": [skill["skill_name"] for skill in opportunity["required_skills"]],
        "is_paid": opportunity["isPaid"],
    }


def test_parse_search_opportunity_wins_over_unreliable_item_type(
    adapter: UnstopAdapter,
    fixture_payload: dict,
) -> None:
    base = _fixture_items(fixture_payload)[0]
    job_payload = {
        **base,
        "id": 101,
        "seo_url": "https://unstop.com/jobs/software-engineer-101",
        "type": "competitions",
        "_aspirova_opportunity": "jobs",
    }
    internship_payload = {
        **base,
        "id": 102,
        "seo_url": "https://unstop.com/internships/software-intern-102",
        "type": "jobs",
        "_aspirova_opportunity": "internships",
    }

    assert adapter.parse(_raw_listing_for(job_payload)).category == "job"
    assert adapter.parse(_raw_listing_for(internship_payload)).category == "internship"


def test_parse_maps_pre_placement_prizes_to_offer_flags(
    adapter: UnstopAdapter,
    fixture_payload: dict,
) -> None:
    opportunity = {
        **_fixture_items(fixture_payload)[0],
        "prizes": [
            {"pre_placement_internship": 1},
            {"pre_placement_opportunity": 1},
        ],
    }

    normalized = adapter.parse(_raw_listing_for(opportunity))

    assert normalized.meta["offers_ppi"] is True
    assert normalized.meta["offers_ppo"] is True


def test_parse_keeps_near_future_registration_deadline_explicit(
    adapter: UnstopAdapter,
    fixture_payload: dict,
) -> None:
    deadline = datetime.now(UTC) + timedelta(days=90)
    opportunity = {
        **_fixture_items(fixture_payload)[0],
        "end_date": "2059-01-01T00:00:00+05:30",
        "regnRequirements": {"end_regn_dt": deadline.isoformat()},
    }

    normalized = adapter.parse(_raw_listing_for(opportunity))

    assert normalized.deadline == deadline
    assert normalized.deadline_confidence == "explicit"


@pytest.mark.parametrize(
    "date_overrides",
    [
        {
            "end_date": "2059-01-01T00:00:00+05:30",
            "regnRequirements": {},
        },
        {
            "end_date": (datetime.now(UTC) + timedelta(days=90)).isoformat(),
            "regnRequirements": {"end_regn_dt": "2059-01-01T00:00:00+05:30"},
        },
    ],
)
def test_parse_marks_implausible_unstop_deadlines_unknown(
    adapter: UnstopAdapter,
    fixture_payload: dict,
    date_overrides: dict,
) -> None:
    opportunity = {
        **_fixture_items(fixture_payload)[0],
        **date_overrides,
    }

    normalized = adapter.parse(_raw_listing_for(opportunity))

    assert normalized.deadline is None
    assert normalized.deadline_confidence == "unknown"


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


def test_parse_assumes_utc_for_plausible_naive_date(
    adapter: UnstopAdapter,
    fixture_payload: dict,
) -> None:
    deadline = (datetime.now(UTC) + timedelta(days=90)).replace(tzinfo=None)
    opportunity = {
        **_fixture_items(fixture_payload)[0],
        "end_date": deadline.isoformat(),
    }

    normalized = adapter.parse(_raw_listing_for(opportunity))

    assert normalized.deadline == deadline.replace(tzinfo=UTC)
    assert normalized.deadline_confidence == "explicit"
