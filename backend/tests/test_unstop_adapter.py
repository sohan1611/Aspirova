"""Unit tests for UnstopAdapter using a captured real API response."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from core.adapters import RawListing
from core.eligibility import ELIGIBLE_EXPERIENCED_ONLY_META_KEY
from crawlers import unstop
from crawlers import runner
from crawlers.common import content_hash
from crawlers.unstop import UnstopAdapter, unstop_team_fields
from pipeline.location_country import derive_country

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "unstop_sample.json"


def test_unstop_team_fields_from_fixture():
    payload = json.loads(
        (FIXTURE_PATH.parent / "unstop_team_sample.json").read_text(encoding="utf-8")
    )
    assert unstop_team_fields(payload) == {"team_min": 1, "team_size": 4}


@pytest.mark.parametrize("value", [None, 0, -1, True, False, "4", 1.5, 4.0])
def test_unstop_team_fields_reject_invalid_sizes(value):
    assert (
        unstop_team_fields({"regnRequirements": {"min_team_size": value, "max_team_size": value}})
        == {}
    )


@pytest.mark.parametrize(
    "search_type, expected",
    [
        ("competitions", True),
        ("hackathons", True),
        ("scholarships", True),
        ("internships", False),
        ("jobs", False),
    ],
)
def test_parse_team_fields_only_for_non_roles(adapter, fixture_payload, search_type, expected):
    payload = {
        **_fixture_items(fixture_payload)[0],
        "_aspirova_opportunity": search_type,
        "regnRequirements": {"min_team_size": 1, "max_team_size": 4},
    }
    parsed = adapter.parse(_raw_listing_for(payload))
    assert ("team_min" in parsed.meta) is expected
    assert ("team_size" in parsed.meta) is expected


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


@pytest.mark.parametrize(
    "title",
    [
        pytest.param("X Scholarship 2023", id="single-past-year"),
        pytest.param("X Fellowship 2024-25", id="short-range"),
        pytest.param("X Grant 2024-2025", id="long-range"),
    ],
)
def test_scholarship_quality_rejects_stale_editions(title: str) -> None:
    """A named past edition is stale even when Unstop still reports it open."""
    assert unstop.is_high_quality_scholarship_title(title, current_year=2026) is False


@pytest.mark.parametrize(
    "title",
    [
        pytest.param("X Scholarship 2026", id="current-year"),
        pytest.param("X Fellowship 2026-27", id="future-range"),
    ],
)
def test_scholarship_quality_keeps_current_or_future_editions(title: str) -> None:
    """Edition years at or beyond the crawl year are still current."""
    assert unstop.is_high_quality_scholarship_title(title, current_year=2026) is True


def test_scholarship_quality_keeps_title_with_no_year() -> None:
    """No explicit year is unknown, not stale; the adapter must not guess."""
    assert unstop.is_high_quality_scholarship_title("Merit Scholarship", current_year=2026) is True


@pytest.mark.parametrize(
    "title",
    [
        "Career Reboot Scholarship Bootcamp for Women on Career Break",
        "Full Stack Development Scholarship Bootcamp for Final Years",
        "Data Science Scholarship Masterclass",
        "Interview Scholarship Crash Course",
        "Cloud Scholarship Certification Course",
        "AI Scholarship Workshop",
        "Admissions Scholarship Webinar",
    ],
)
def test_scholarship_quality_rejects_course_shaped_titles(title: str) -> None:
    """Unstop scholarships include training products that are not financial aid."""
    assert unstop.is_high_quality_scholarship_title(title, current_year=2026) is False


def test_scholarship_quality_keeps_course_fee_scholarship() -> None:
    """The word 'course' alone is not enough to reject real financial aid."""
    assert (
        unstop.is_high_quality_scholarship_title(
            "Merit Scholarship for Degree Course Fees",
            current_year=2026,
        )
        is True
    )


def test_scholarship_quality_rejects_generic_study_abroad_lead_title() -> None:
    """A generic admissions lead-gen title is not a named scholarship programme."""
    assert (
        unstop.is_high_quality_scholarship_title(
            "Study in USA - Study Abroad Scholarship",
            current_year=2026,
        )
        is False
    )


_LIVE_UNSTOP_REJECTED_SCHOLARSHIP_TITLES = [
    "Study in USA - Study Abroad Scholarship",
    "Vahani Scholarship 2023",
    "Career Reboot Bootcamp for Women on Career Break",
    "Full Stack Development Bootcamp for Final Years",
    "Abdul Kalam Technology Innovation National Fellowship 2023-24",
    "Fulbright-Nehru Doctoral Research Fellowships 2024-25",
    "Prodigy Finance-GyanDhan Scholarship 2023",
    "Goonj Urban Fellowship 2023-24",
    "State University Research Excellence Fellowship (SERB-SURE) 2023",
    "Supercharge your career with EHAM's 5-month Full Stack Development Bootcamp",
    "IELTS Scholarships 2022",
]

_LIVE_UNSTOP_WRONGLY_KEPT_SCHOLARSHIP_TITLES = [
    "Free Scholarship Test on VLSI",
    "Free Scholarship Test on Digital Marketing",
    "Free Scholarship Test on UI/UX Design with AI",
    "Free Scholarship Test on Full Stack Java",
    "Free Scholarship Test on Medical Coding on 19July2026 at 10:30am onwards",
    "Free Scholarship Test: Digital Marketing with AI Training",
    "MSAT- MissionEd Scholastic Aptitude Test",
    "MissionEd Scholastic Aptitude Test",
    "Future Leaders Assessment 2026",
    "Get Your Admission in Top Universities in Germany with GradSmartly",
    "Welcome to the Study Abroad Festival",
    "Pregrad Mentorship Program",
    "Elite Campus Ambassador - Pan-India Tech Initiative",
    "AI Career Readiness Challenge 2026",
    "Ace engiXplor by NITK",
    # Second live pass, same day, 60-item page: these two survived the aid-noun
    # requirement because "Scholarship" is right there in the title. Marketing
    # funnel vocabulary is the only thing that separates them from real aid.
    "Lead gen - scholarship events",
    "Lead to Win: Scholarship Edition",
]

_LIVE_UNSTOP_CORRECTLY_KEPT_SCHOLARSHIP_TITLES = [
    "IISER Berhampur Post-Doctoral Research Fellowship (PDRF) 2025-26",
    "Bharat Academix National Excellence Scholarship 2026",
    "CPRG - Social Sciences Research Grant",
    "Grant for Educational Development Projects",
    "Commuter Bursary",
    "IBSAT Scholarship",
    "Sage IT Scholarship India - November 2026",
    "Mutual Funds Catalyst Scholarship",
]


@pytest.mark.parametrize(
    ("title", "expected"),
    [(title, False) for title in _LIVE_UNSTOP_REJECTED_SCHOLARSHIP_TITLES]
    + [(title, False) for title in _LIVE_UNSTOP_WRONGLY_KEPT_SCHOLARSHIP_TITLES]
    + [(title, True) for title in _LIVE_UNSTOP_CORRECTLY_KEPT_SCHOLARSHIP_TITLES],
)
def test_scholarship_quality_live_unstop_precision_regression(
    title: str,
    expected: bool,
) -> None:
    """These titles came from a live Unstop page on 2026-09-01.

    They are real production examples, not invented fixtures.
    """
    assert unstop.is_high_quality_scholarship_title(title, current_year=2026) is expected


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
        {
            "opportunity": "scholarships",
            "oppstatus": "open",
            "per_page": 300,
            "page": 1,
        },
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
    assert coverage["details"]["requests_made"] == 6
    assert sleep_calls == [2.0]
    assert [params["opportunity"] for params in request_params] == [
        "internships",
        "internships",
        "competitions",
        "hackathons",
        "jobs",
        "scholarships",
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
        "scholarships",
    ]
    assert coverage["details"]["incomplete_type_reasons"] == {"internships": "request_error"}
    assert coverage["details"]["retry_attempts"] == 2
    assert coverage["details"]["retry_reasons"] == ["request_error", "request_error"]
    assert coverage["details"]["requests_made"] == 7
    assert sleep_calls == [2.0, 4.0]
    assert [params["opportunity"] for params in request_params] == [
        "internships",
        "internships",
        "internships",
        "competitions",
        "hackathons",
        "jobs",
        "scholarships",
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
        "scholarships": "not_reached",
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
        "scholarships": 2383,
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
        "scholarships": 2383,
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
        "scholarships": 2383,
    }
    adapter._fully_paged_types = {
        "internships",
        "competitions",
        "hackathons",
        "scholarships",
    }
    adapter._incomplete_type_reasons = {"jobs": "stopped_early"}

    coverage = adapter.coverage()

    assert coverage["expected_total"] is None
    assert coverage["status"] == "partial"
    assert coverage["details"]["incomplete_type_reasons"] == {"jobs": "stopped_early"}


def test_fetch_counts_rejected_low_quality_scholarships_in_coverage(
    adapter: UnstopAdapter,
    fixture_payload: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Filtered scholarships must be visible in coverage, not look like scarcity."""
    current_year = datetime.now(UTC).year
    good = {
        **_open_fixture_item(fixture_payload, "scholarships", "scholarship-good"),
        "title": f"National Merit Scholarship {current_year}",
    }
    stale = {
        **_open_fixture_item(fixture_payload, "scholarships", "scholarship-stale"),
        "title": f"Legacy Scholarship {current_year - 1}",
    }
    bootcamp = {
        **_open_fixture_item(fixture_payload, "scholarships", "scholarship-bootcamp"),
        "title": "Full Stack Development Bootcamp for Final Years",
    }

    def fake_get(url: str, *, params: dict) -> httpx.Response:
        items = (
            [good, stale, bootcamp]
            if params["opportunity"] == "scholarships" and params["page"] == 1
            else []
        )
        request = httpx.Request("GET", url, params=params)
        return httpx.Response(
            200,
            json=_payload_for(items, total=len(items)),
            request=request,
        )

    monkeypatch.setattr(adapter._client, "get", fake_get)

    raw_listings = adapter.fetch()

    assert [listing.external_id for listing in raw_listings] == ["scholarship-good"]
    assert adapter.health() == "ok"
    assert adapter.coverage()["details"]["rejected_low_quality"] == 2
    assert adapter.coverage()["details"]["rejected_low_quality_by_type"] == {"scholarships": 2}


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
    assert normalized.location is None
    assert normalized.country == "IN"
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
    scholarship_payload = {
        **base,
        "id": 103,
        "title": "National Scholarship 2026",
        "seo_url": "https://unstop.com/scholarships/national-scholarship-103",
        "type": "jobs",
        "_aspirova_opportunity": "scholarships",
    }

    assert adapter.parse(_raw_listing_for(job_payload)).category == "job"
    assert adapter.parse(_raw_listing_for(internship_payload)).category == "internship"
    assert adapter.parse(_raw_listing_for(scholarship_payload)).category == "scholarship"


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


def test_parse_records_unstop_eligibility_and_categories_verbatim(
    adapter: UnstopAdapter,
    fixture_payload: dict,
) -> None:
    opportunity = {
        **_fixture_items(fixture_payload)[0],
        "filters": [
            {"id": 426, "name": "Undergraduate", "type": "eligible"},
            {"id": 424, "name": "Postgraduate", "type": "eligible"},
            {"id": 701, "name": "Hackathon", "type": "category"},
            {"id": 999, "name": "Ignore Me", "type": "industry"},
        ],
    }

    normalized = adapter.parse(_raw_listing_for(opportunity))

    assert normalized.meta["eligibility"] == ["Undergraduate", "Postgraduate"]
    assert normalized.meta["categories"] == ["Hackathon"]
    assert normalized.meta[ELIGIBLE_EXPERIENCED_ONLY_META_KEY] is False


def test_parse_marks_experienced_professionals_only_eligibility(
    adapter: UnstopAdapter,
    fixture_payload: dict,
) -> None:
    opportunity = {
        **_fixture_items(fixture_payload)[0],
        "filters": [
            {"id": 430, "name": "Experienced Professionals", "type": "eligible"},
            {"id": 702, "name": "Case Study", "type": "category"},
        ],
    }

    normalized = adapter.parse(_raw_listing_for(opportunity))

    assert normalized.meta["eligibility"] == ["Experienced Professionals"]
    assert normalized.meta["categories"] == ["Case Study"]
    assert normalized.meta[ELIGIBLE_EXPERIENCED_ONLY_META_KEY] is True


def test_parse_keeps_experienced_professionals_when_student_eligible(
    adapter: UnstopAdapter,
    fixture_payload: dict,
) -> None:
    opportunity = {
        **_fixture_items(fixture_payload)[0],
        "filters": [
            {"id": 430, "name": "Experienced Professionals", "type": "eligible"},
            {"id": 426, "name": "Undergraduate", "type": "eligible"},
        ],
    }

    normalized = adapter.parse(_raw_listing_for(opportunity))

    assert normalized.meta["eligibility"] == [
        "Experienced Professionals",
        "Undergraduate",
    ]
    assert normalized.meta[ELIGIBLE_EXPERIENCED_ONLY_META_KEY] is False


def test_parse_absent_or_empty_filters_set_no_eligibility_flag(
    adapter: UnstopAdapter,
    fixture_payload: dict,
) -> None:
    without_filters = {**_fixture_items(fixture_payload)[0]}
    without_filters.pop("filters", None)

    for opportunity in [without_filters, {**_fixture_items(fixture_payload)[0], "filters": []}]:
        normalized = adapter.parse(_raw_listing_for(opportunity))

        assert "eligibility" not in normalized.meta
        assert "categories" not in normalized.meta
        assert ELIGIBLE_EXPERIENCED_ONLY_META_KEY not in normalized.meta


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


def test_failed_type_still_reports_degraded_when_a_later_type_runs_out_of_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A type that already failed must not be reported healthy.

    Health is applied after the type loop, but the stopped_early path returns
    early and skips it. unstop hits stopped_early on most runs (it is budget
    bound), so without applying health on that path a real failure in an
    earlier type is silently reported as 'ok'.
    """
    adapter = UnstopAdapter()

    calls: list[str] = []

    def fake_get(url: str, *, params: dict) -> httpx.Response:
        opportunity_type = params["opportunity"]
        calls.append(opportunity_type)
        request = httpx.Request("GET", url, params=params)
        # The FIRST type fails outright; a later type is cut short by budget.
        if opportunity_type == "internships":
            raise httpx.ConnectError("simulated transient failure")
        return httpx.Response(
            200,
            json={"data": {"data": [], "total": 0}},
            request=request,
        )

    # Trip the deadline once the first type has been abandoned, so the run
    # exits through the stopped_early return rather than the loop end.
    stop_after = {"n": 0}

    def fake_should_stop() -> bool:
        stop_after["n"] += 1
        return stop_after["n"] > 3

    monkeypatch.setattr(adapter._client, "get", fake_get)
    monkeypatch.setattr(unstop, "sleep", lambda _seconds: None)

    adapter.fetch(should_stop=fake_should_stop)

    assert adapter._incomplete_type_reasons.get("internships") == "request_error"
    assert adapter.stopped_early is True
    # The regression: this reported "ok" while internships had genuinely failed.
    assert adapter.health() == "degraded"


# ------------------------------------------------- jobs/internships separation

# Real titles Unstop's *jobs* search returned on 2026-09-01. Filed under Jobs,
# they put an internship in front of someone browsing full-time roles.
_JOBS_SEARCH_TITLES_THAT_ARE_INTERNSHIPS = [
    "Business Development Internship",
    "Campus Ambassador Internship",
    "AI Backend Internship",
    "Content Development Intern",
    "Campus Relations Internship",
    "EHS Intern_Shenzhen",
]

# The lookalikes that must NOT be reclassified. "International" and "Internal"
# both contain "intern"; a substring match would move real jobs into the
# internships tab, which is the same failure in the opposite direction.
_JOBS_SEARCH_TITLES_THAT_STAY_JOBS = [
    "International Sales Manager",
    "Internal Auditor",
    "Software Engineer",
    "Senior Backend Developer",
    "Interndom Analyst",
]


@pytest.mark.parametrize("title", _JOBS_SEARCH_TITLES_THAT_ARE_INTERNSHIPS)
def test_title_says_internship_catches_real_mislabelled_rows(title: str) -> None:
    assert unstop._title_says_internship(title) is True


@pytest.mark.parametrize("title", _JOBS_SEARCH_TITLES_THAT_STAY_JOBS)
def test_title_says_internship_ignores_lookalikes(title: str) -> None:
    """Word-boundary anchored on both sides, like the reputed-organiser regex."""
    assert unstop._title_says_internship(title) is False


def test_title_says_internship_handles_missing_titles() -> None:
    for value in (None, "", "   "):
        assert unstop._title_says_internship(value) is False


@pytest.mark.parametrize("second_page_size", [282, 200, 0])
def test_short_page_with_declared_total_still_fetches_page_two(
    adapter: UnstopAdapter,
    fixture_payload: dict,
    monkeypatch: pytest.MonkeyPatch,
    second_page_size: int,
) -> None:
    calls: list[tuple[str, int]] = []

    def fake_get(url: str, *, params: dict) -> httpx.Response:
        kind, page = params["opportunity"], params["page"]
        calls.append((kind, page))
        if kind == "internships":
            count = 293 if page == 1 else second_page_size
            items = [
                _open_fixture_item(fixture_payload, kind, f"{page}-{index}")
                for index in range(count)
            ]
            payload = _payload_for(items, total=592)
        else:
            payload = _payload_for([], total=0)
        return httpx.Response(200, json=payload, request=httpx.Request("GET", url))

    monkeypatch.setattr(adapter._client, "get", fake_get)
    adapter.fetch()

    assert calls[:2] == [("internships", 1), ("internships", 2)]
    assert ("internships", 3) not in calls
    coverage = adapter.coverage()
    if second_page_size == 282:
        assert coverage["status"] == "complete"
        assert adapter.health() == "ok"
    else:
        assert coverage["status"] == "partial"
        assert coverage["details"]["incomplete_type_reasons"] == {
            "internships": "short_of_declared_total"
        }


@pytest.mark.parametrize(
    ("detail", "locations", "expected_location", "expected_remote"),
    [
        (
            {"type": "in_office", "locations": ["Bangalore", "Hyderabad", "Bangalore"]},
            [],
            "Bangalore; Hyderabad",
            False,
        ),
        (
            {"type": "hybrid", "locations": []},
            [{"city": "Mohali", "state": "Punjab", "country": "India"}] * 2,
            "Mohali, Punjab",
            False,
        ),
        ({"type": "wfh", "locations": []}, [], "Work from home", True),
        ({"type": "in_office", "locations": []}, [], None, False),
        ({"type": "on_field", "locations": ["Delhi"]}, [], "Delhi", False),
    ],
)
@pytest.mark.parametrize("search_type", ["internships", "jobs"])
def test_role_location_and_remote_use_job_detail(
    adapter: UnstopAdapter,
    fixture_payload: dict,
    detail: dict,
    locations: list,
    expected_location: str | None,
    expected_remote: bool,
    search_type: str,
) -> None:
    payload = {
        **_fixture_items(fixture_payload)[0],
        "_aspirova_opportunity": search_type,
        "jobDetail": {**detail, "timing": "full_time"},
        "locations": locations,
    }
    normalized = adapter.parse(_raw_listing_for(payload))
    assert normalized.location == expected_location
    assert normalized.country == "IN"
    assert normalized.is_remote is expected_remote
    assert normalized.meta["work_mode"] == detail["type"]
    assert normalized.meta["timing"] == "full_time"


def test_role_country_does_not_override_explicit_foreign_country() -> None:
    fields = unstop.unstop_role_fields(
        {
            "jobDetail": {"type": "in_office", "locations": ["Berlin"]},
            "locations": [{"city": "Berlin", "country": "Germany"}],
        }
    )
    assert fields["country"] is None
    assert derive_country(fields["location"]) == "DE"


def test_role_without_job_detail_keeps_region_remote_behavior() -> None:
    assert unstop.unstop_role_fields({"region": "online"})["is_remote"] is True
    assert unstop.unstop_role_fields({"region": "offline"})["is_remote"] is False


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, {"min": 5000, "max": 15000, "currency": "INR", "period": "month", "source": "unstop"}),
        ({"paid_unpaid": "unpaid"}, {"unpaid": True, "source": "unstop"}),
        ({"show_salary": 0}, None),
        ({"not_disclosed": True}, None),
        ({"currency": "USD"}, None),
        ({"pay_in": "weekly"}, None),
        ({"max_salary": 0}, None),
        (
            {"pay_in": "annually", "min_salary": 0, "max_salary": 300000},
            {"min": 300000, "max": 300000, "currency": "INR", "period": "year", "source": "unstop"},
        ),
        # Real rows: ₹4,000 "annually", and exactly a lakh still counts as a salary.
        (
            {"pay_in": "annually", "min_salary": 4000, "max_salary": 4000},
            {"paid": True, "source": "unstop"},
        ),
        (
            {"pay_in": "annually", "min_salary": 100000, "max_salary": 100000},
            {"min": 100000, "max": 100000, "currency": "INR", "period": "year", "source": "unstop"},
        ),
    ],
)
def test_role_compensation_uses_only_disclosed_rupee_pay(
    overrides: dict,
    expected: dict | None,
) -> None:
    detail = {
        "type": "in_office",
        "timing": "full_time",
        "paid_unpaid": "paid",
        "pay_in": "monthly",
        "currency": "fa-rupee",
        "min_salary": 5000,
        "max_salary": 15000,
        "show_salary": 1,
        "not_disclosed": False,
        "locations": ["Bangalore", "Hyderabad"],
        **overrides,
    }
    meta = unstop.unstop_role_fields({"jobDetail": detail})["meta"]
    assert meta.get("compensation") == expected
    assert ("compensation" in meta) is (expected is not None)


@pytest.mark.parametrize(
    ("payload", "maximum", "expected"),
    [
        # Real row: "stipend of up to ₹75,000" for a 75-day programme, entered as monthly.
        ({"subtype": "internships", "title": "Intern with the Indian Army"}, 75000, None),
        ({"subtype": "jobs", "title": "Business Development Internship"}, 60000, None),
        ({"subtype": "internships", "title": "Data Intern"}, 59999, 59999),
        ({"subtype": "jobs", "title": "Chartered Accountant"}, 100000, 100000),
    ],
)
def test_implausible_internship_monthly_pay_shows_as_paid(
    payload: dict, maximum: int, expected: int | None
) -> None:
    detail = {
        "paid_unpaid": "paid",
        "pay_in": "monthly",
        "currency": "fa-rupee",
        "max_salary": maximum,
        "show_salary": 1,
    }
    compensation = unstop.unstop_role_fields({**payload, "jobDetail": detail})["meta"][
        "compensation"
    ]
    if expected is None:
        assert compensation == {"paid": True, "source": "unstop"}
    else:
        assert compensation["max"] == expected


def test_competition_keeps_online_behavior_even_with_job_detail(
    adapter: UnstopAdapter,
    fixture_payload: dict,
) -> None:
    payload = {
        **_fixture_items(fixture_payload)[0],
        "_aspirova_opportunity": "competitions",
        "jobDetail": {"type": "in_office", "locations": ["Delhi"], "paid_unpaid": "unpaid"},
    }
    normalized = adapter.parse(_raw_listing_for(payload))
    assert normalized.location == "Online"
    assert normalized.is_remote is True
    assert normalized.country is None
    assert "work_mode" not in normalized.meta
    assert "compensation" not in normalized.meta


@pytest.mark.parametrize("fixture_index", [0, 1])
def test_parse_company_logo_from_fixture(adapter, fixture_payload, fixture_index) -> None:
    opportunity = _fixture_items(fixture_payload)[fixture_index]
    normalized = adapter.parse(_raw_listing_for(opportunity))
    organization = opportunity["organisation"]

    assert normalized.company_logo_url == (
        organization.get("logoUrl2") or organization.get("logoUrl") or None
    )
    if fixture_index == 1:
        assert organization["logoUrl"] == ""
        assert normalized.company_logo_url is None


@pytest.mark.parametrize(
    "preferred, fallback, expected",
    [
        (
            "https://images.example/large.png",
            "https://images.example/small.png",
            "https://images.example/large.png",
        ),
        (None, "http://images.example/small.png", "http://images.example/small.png"),
        ("  ", "https://images.example/small.png", "https://images.example/small.png"),
        (
            "ftp://images.example/large.png",
            "https://images.example/small.png",
            "https://images.example/small.png",
        ),
        ("data:image/png;base64,abc", None, None),
        ("/logo.png", "//images.example/logo.png", None),
        ("https:///", "javascript:alert(1)", None),
        ("https://[broken", "", None),
    ],
)
def test_parse_company_logo_requires_http_url(
    adapter, fixture_payload, preferred, fallback, expected
) -> None:
    opportunity = {
        **_fixture_items(fixture_payload)[0],
        "organisation": {"name": "Example", "logoUrl2": preferred, "logoUrl": fallback},
    }

    assert adapter.parse(_raw_listing_for(opportunity)).company_logo_url == expected


def test_parse_ignores_logo_when_company_falls_back_to_unstop(adapter, fixture_payload) -> None:
    opportunity = {
        **_fixture_items(fixture_payload)[0],
        "organisation": {"logoUrl2": "https://images.example/logo.png"},
    }
    normalized = adapter.parse(_raw_listing_for(opportunity))

    assert normalized.company_name == "Unstop"
    assert normalized.company_logo_url is None


@pytest.mark.parametrize(
    "approved, expected",
    [
        # The live search API's format (checked 2026-11-10).
        ("2026-11-10 17:47:40 GMT+0530", datetime(2026, 11, 10, 12, 17, 40, tzinfo=UTC)),
        ("2026-11-10T17:47:40+05:30", datetime(2026, 11, 10, 12, 17, 40, tzinfo=UTC)),
        # No offset is ambiguous (IST or UTC); future and junk values are unknown.
        ("2026-11-10 17:47:40", None),
        ("2100-01-01 00:00:00 GMT+0530", None),
        ("soon", None),
        (None, None),
    ],
)
def test_parse_reads_approved_date_as_the_posting_date(
    adapter, fixture_payload, approved, expected
):
    payload = {
        **_open_fixture_item(fixture_payload, "jobs", "approved-date"),
        "_aspirova_opportunity": "jobs",
        "approved_date": approved,
    }

    assert adapter.parse(_raw_listing_for(payload)).posted_at == expected
