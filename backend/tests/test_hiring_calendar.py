from datetime import date, datetime
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from api.calendar import build_calendar, router
from api.deps import get_db
from core.hiring_calendar import (
    CALENDAR_META,
    IST,
    ROWS,
    SOURCE,
    at_day,
    month_date,
    parse_calendar_date,
    recurrence_is_official,
    source_window,
)
from core.models import Programme, ProgrammeEdition
from scripts.import_calendar import category_for

WINDOWLESS_ROWS = {
    "OPP-010",
    "OPP-044",
    "OPP-047",
    "OPP-048",
    "OPP-049",
    "OPP-050",
    "OPP-103",
    "OPP-111",
    "OPP-112",
    "OPP-113",
    "OPP-114",
}
RESEARCH_SLUGS = {
    slug for slug, meta in CALENDAR_META.items() if 101 <= int(meta["row_id"].split("-")[1]) < 201
}
EXPANSION_SLUGS = {
    slug for slug, meta in CALENDAR_META.items() if int(meta["row_id"].split("-")[1]) >= 201
}
WINDOWLESS_ROWS |= {
    CALENDAR_META[slug]["row_id"] for slug in EXPANSION_SLUGS if source_window(slug)["rolling"]
}


def source_programme(slug):
    meta = CALENDAR_META[slug]
    window = source_window(slug)
    item = programme(slug, opening=None, closing=None, status=window["status"])
    item.name = meta["name"]
    item.organiser = meta["organiser"]
    item.category = category_for(ROWS[meta["row_id"]])
    edition = item.editions[0]
    edition.year = meta["cycle_year"]
    edition.opens_at = window["opens_at"]
    edition.closes_at = window["closes_at"]
    edition.notes = window["notes"]
    return item


@pytest.mark.parametrize("slug", CALENDAR_META)
def test_every_source_row_has_window_or_rolling(slug):
    window = source_window(slug)
    assert window["rolling"] or window["opens_at"] or window["closes_at"]
    for field in ("opens_at", "closes_at"):
        value = window[field]
        if value:
            assert value.tzinfo is not None
            if window["status"] == "expected":
                assert window[field.replace("_at", "_precision")] == "month"
    if window["opens_at"] and window["closes_at"]:
        assert window["opens_at"] <= window["closes_at"]


def test_source_retains_original_rows_and_adds_researched_programmes():
    assert SOURCE["count"] == len(SOURCE["opportunities"]) == len(ROWS) == len(CALENDAR_META)
    assert len(ROWS) == 64 + len(EXPANSION_SLUGS)
    assert len(RESEARCH_SLUGS) == 14
    assert {f"OPP-{number:03}" for number in range(1, 51)} <= ROWS.keys()
    assert sum(row["category"] == "Tech" for row in ROWS.values()) == 13


@pytest.mark.parametrize("slug", CALENDAR_META)
def test_every_usable_source_date_appears_in_a_cycle_month(slug):
    meta = CALENDAR_META[slug]
    row = ROWS[meta["row_id"]]
    opening = parse_calendar_date(row["application_open"])
    deadline = parse_calendar_date(row["registration_deadline"])
    if opening.start is None and deadline.start is None and not meta.get("recurrence"):
        assert meta["row_id"] in WINDOWLESS_ROWS
        assert source_window(slug)["rolling"]
        return
    assert not source_window(slug)["rolling"]
    with request_client([source_programme(slug)]) as client:
        for year in range(meta["cycle_year"] - 1, meta["cycle_year"] + 1):
            for month in range(1, 13):
                start = month_date(year, month).date().isoformat()
                end = month_date(year, month, end=True).date().isoformat()
                response = client.get("/calendar", params={"from": start, "to": end})
                assert response.status_code == 200
                if any(
                    item["edition"]["year"] == meta["cycle_year"]
                    for item in response.json()["items"]
                ):
                    return
    pytest.fail(f"{meta['row_id']} has a usable date but no calendar month")


def test_source_calendar_and_rolling_counts():
    dated, rolling = set(), set()
    with request_client([source_programme(slug) for slug in CALENDAR_META]) as client:
        for year in (2026, 2027, 2028):
            response = client.get(f"/calendar?from={year}-01-01&to={year}-12-31")
            assert response.status_code == 200
            dated.update(item["metadata"]["row_id"] for item in response.json()["items"])
            rolling.update(item["metadata"]["row_id"] for item in response.json()["rolling"])
    print(f"Calendar source counts: on-calendar={len(dated)}, rolling={len(rolling)}")
    assert len(dated) == len(ROWS) - len(WINDOWLESS_ROWS)
    assert rolling == WINDOWLESS_ROWS
    assert dated.isdisjoint(rolling)
    assert dated | rolling == set(ROWS)


def test_research_rows_reuse_canonical_registry_slugs_and_have_provenance():
    from core.hiring_calendar import DATA_DIR, METADATA

    registry = json.loads((DATA_DIR / "programmes.json").read_text(encoding="utf-8"))
    registry_slugs = [entry["slug"] for entry in registry["programmes"]]
    assert len(registry_slugs) == len(set(registry_slugs))
    assert {"gsoc", "hacktoberfest", "mlh-fellowship", "outreachy", "lfx-mentorship"} <= (
        RESEARCH_SLUGS & set(registry_slugs)
    )
    row_ids = [meta["row_id"] for meta in CALENDAR_META.values()]
    assert len(row_ids) == len(set(row_ids))
    assert set(row_ids) == set(ROWS)
    for slug in RESEARCH_SLUGS:
        meta = CALENDAR_META[slug]
        row = ROWS[meta["row_id"]]
        assert row["official_portal"].startswith("https://")
        assert date.fromisoformat(row["source_checked_on"]) == date(2026, 11, 13)
        assert row["verification_note"] == meta["verification_note"]
        assert row["verification_note"]
        assert row["date_basis"] == "Tentative (Historical Annual Trend)"
        assert source_window(slug)["status"] == "expected"
        assert category_for(row) in {"open_source", "early_career"}
        if meta["row_id"] in WINDOWLESS_ROWS:
            assert source_window(slug)["rolling"]
            assert "rolling" in row["application_open"].lower()
    for item in METADATA["watchlist"]:
        assert item["status"] == "unverified/legacy watchlist"
        assert item["reason"]
        assert item["source_url"].startswith("https://")
        assert item["source_checked_on"] == "2026-11-13"
        assert not {"opens_at", "closes_at", "row_id"} & item.keys()
        assert item["name"] not in {meta["name"] for meta in CALENDAR_META.values()}


@pytest.mark.parametrize(
    "slug,months",
    [
        ("gsoc", [3, 4]),
        ("hacktoberfest", [10]),
        ("outreachy", [2, 8]),
        ("lfx-mentorship", [1, 2, 4, 5, 7, 8]),
        ("girlscript-summer-of-code", [3]),
        ("summer-of-bitcoin", [2]),
        ("season-of-kde", [1]),
        ("women-techmakers-ambassadors", [5]),
        ("amazon-ml-summer-school", [8, 9]),
    ],
)
def test_research_windows_have_only_supported_months_and_remain_tentative(slug, months):
    item = source_programme(slug)
    for month in range(1, 13):
        result = build_calendar(
            [item],
            date(2027, month, 1),
            month_date(2027, month, end=True).date(),
            categories=[],
            statuses=[],
            q="",
            now=datetime(2027, month, 15, tzinfo=IST),
        )
        assert bool(result.items) == (month in months)
        assert not result.rolling
        for occurrence in result.items:
            assert occurrence.edition.status == "expected"
            assert occurrence.edition.basis == "tentative"
            assert occurrence.edition.opens_precision == "month"
            assert occurrence.edition.closes_precision == "month"
            assert not occurrence.is_open_now


def test_season_of_kde_intake_starts_in_preceding_december():
    window = source_window("season-of-kde")
    assert window["opens_at"].date() == date(2026, 12, 1)
    assert window["closes_at"].date() == date(2027, 1, 31)
    with request_client([source_programme("season-of-kde")]) as client:
        result = client.get("/calendar?from=2026-12-01&to=2026-12-31").json()
    assert result["items"][0]["edition"]["year"] == 2027


@pytest.mark.parametrize("slug", RESEARCH_SLUGS)
def test_research_rows_are_visible_under_their_real_category(slug):
    item = source_programme(slug)
    with request_client([item]) as client:
        base = "/calendar?from=2026-12-01&to=2027-12-31"
        result = client.get(base + f"&category={item.category}").json()
        assert result["items"] or result["rolling"]
        other = "early_career" if item.category == "open_source" else "open_source"
        result = client.get(base + f"&category={other}").json()
        assert not result["items"] and not result["rolling"]
        result = client.get(base + "&status=open").json()
        assert not result["items"] and not result["rolling"]


@pytest.mark.parametrize(
    "slug,start,end,months",
    [
        ("goldman-sachs-india-summer-analyst", "2027-07-01", "2027-07-31", [7]),
        ("atlassian-india-internship", "2027-07-01", "2027-07-31", [7]),
        ("microsoft-swe-india", "2027-08-01", "2027-11-30", [8, 9, 10, 11]),
        ("de-shaw-india-campus", "2027-07-01", "2027-10-31", [7, 8, 9, 10]),
        ("dpiit-internship", "2027-03-01", "2027-03-31", [3]),
    ],
)
def test_rolling_deadline_intersects_only_the_opening_window(slug, start, end, months):
    source = source_programme(slug)
    edition = source.editions[0]
    assert edition.opens_at.date().isoformat() == start
    assert edition.closes_at.date().isoformat() == end
    with request_client([source]) as client:
        for month in range(1, 13):
            result = client.get(
                "/calendar",
                params={
                    "from": month_date(2027, month).date().isoformat(),
                    "to": month_date(2027, month, end=True).date().isoformat(),
                },
            ).json()
            assert bool(result["items"]) == (month in months)
            assert result["rolling"] == []
            assert result["months"][0]["count"] == int(month in months)
            if result["items"]:
                assert result["items"][0]["metadata"]["deadline_rolling"] is True
                if edition.status == "expected":
                    assert result["items"][0]["edition"]["opens_precision"] == "month"
                    assert result["items"][0]["is_open_now"] is False


def test_deadline_only_row_appears_at_its_deadline():
    with request_client([source_programme("oist-research-internship")]) as client:
        assert client.get("/calendar?from=2027-04-15&to=2027-04-15").json()["items"]
        assert client.get("/calendar?from=2027-04-14&to=2027-04-14").json()["items"] == []


def test_extracted_official_deadline_supersedes_rolling_metadata():
    source = source_programme("microsoft-swe-india")
    edition = source.editions[0]
    edition.status = "announced"
    edition.closes_at = at_day(date(2027, 10, 15), end=True)
    edition.notes += "\ncalendar_exact_closes_at"
    with request_client([source]) as client:
        item = client.get("/calendar?from=2027-10-01&to=2027-10-31").json()["items"][0]
    assert item["metadata"]["deadline_rolling"] is False
    assert item["edition"]["closes_precision"] == "day"


@pytest.mark.parametrize(
    "text,precision,start,end",
    [
        ("4 Dec 2026 (official)", "day", "2026-12-04", "2026-12-04"),
        ("Jan–Feb 2027", "month", "2027-01-01", "2027-02-28"),
        ("Feb–Mar 2027", "month", "2027-02-01", "2027-03-31"),
        ("Sep–Dec 2027 (variable)", "month", "2027-09-01", "2027-12-31"),
        ("Listed by Nov 2026", "month", "2026-11-01", "2026-11-30"),
        ("15 Oct 2026 (official annual rule)", "day", "2026-10-15", "2026-10-15"),
        ("Early Mar 2027", "month", "2027-03-01", "2027-03-31"),
    ],
)
def test_parser_formats(text, precision, start, end):
    parsed = parse_calendar_date(text)
    assert parsed.precision == precision
    assert parsed.start.date().isoformat() == start
    assert parsed.end.date().isoformat() == end


@pytest.mark.parametrize(
    "text",
    [
        "Rolling…",
        "Lab-dependent / rolling",
        "Campus-dependent",
        "Advertisement-specific",
        "Event-specific",
        "See live CERN vacancy; no fixed deadline",
        "unknown",
        "31 Feb 2027",
        "Application round before Apr 2027",
        "Variable; 2026 lab notices May–Nov",
    ],
)
def test_unfixed_dates_have_no_fake_date(text):
    parsed = parse_calendar_date(text)
    assert parsed.start is parsed.end is None
    assert parsed.note


def programme(
    slug="test-research", *, opening="2027-01-10", closing="2027-03-20", status="expected"
):
    return Programme(
        id=1,
        slug=slug,
        name="Research programme",
        organiser="Institute",
        category="research_internship",
        url="https://example.org/",
        tags=[],
        is_active=True,
        editions=[
            ProgrammeEdition(
                id=1,
                year=2027,
                status=status,
                opens_at=at_day(date.fromisoformat(opening)) if opening else None,
                closes_at=at_day(date.fromisoformat(closing), end=True) if closing else None,
            )
        ],
    )


def request_client(programmes):
    class FakeDB:
        def scalars(self, statement):
            return programmes

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: FakeDB()
    return TestClient(app)


@pytest.mark.parametrize(
    "start,end",
    [
        ("2027-01-01", "2027-12-31"),
        ("2027-02-01", "2027-02-28"),
        ("2027-02-01", "2027-02-07"),
        ("2027-02-17", "2027-03-08"),
    ],
)
def test_calendar_ranges_and_spanning_boundaries(start, end):
    with request_client([programme()]) as client:
        response = client.get("/calendar", params={"from": start, "to": end})
    assert response.status_code == 200
    assert len(response.json()["items"]) == 1
    assert response.json()["from"] == start
    assert response.json()["to"] == end


@pytest.mark.parametrize(
    "start,end",
    [
        ("2027-01-01", "2029-01-02"),
        ("2027-04-01", "2027-03-01"),
        ("oops", "2027-03-01"),
    ],
)
def test_invalid_ranges_are_422(start, end):
    with request_client([]) as client:
        assert client.get("/calendar", params={"from": start, "to": end}).status_code == 422
        assert client.get("/calendar").status_code == 422


def test_recurrence_rolling_counts_and_precision():
    niti = programme("niti-aayog-internship", status="announced")
    niti.category = "government_internship"
    rbi = programme("rbi-research-internship", status="announced")
    rolling = programme("kaust-vsrp", opening=None, closing=None)
    with request_client([niti, rbi, rolling]) as client:
        year = client.get("/calendar?from=2027-01-01&to=2027-12-31").json()
        month = client.get("/calendar?from=2027-03-01&to=2027-03-31").json()
    assert len([item for item in year["items"] if item["programme"]["slug"] == niti.slug]) == 12
    assert len([item for item in month["items"] if item["programme"]["slug"] == niti.slug]) == 1
    assert len([item for item in year["items"] if item["programme"]["slug"] == rbi.slug]) == 2
    assert year["months"][0] == {"month": "2027-01", "count": 2}
    assert year["months"][5]["count"] == 1
    assert len(year["rolling"]) == len(month["rolling"]) == 1
    assert year["rolling"][0]["edition"]["opens_at"] is None


def test_filters_and_tentative_never_open():
    item = programme()
    result = build_calendar(
        [item],
        date(2027, 1, 1),
        date(2027, 12, 31),
        categories=[],
        statuses=[],
        q="institute",
        now=datetime(2027, 2, 1, tzinfo=IST),
    )
    assert result.items[0].edition.basis == "tentative"
    assert result.items[0].is_open_now is False
    assert result.items[0].edition.opens_precision == "month"
    with request_client([item]) as client:
        base = "/calendar?from=2027-01-01&to=2027-12-31"
        assert not client.get(base + "&category=early_career").json()["items"]
        assert not client.get(base + "&status=open").json()["items"]
        assert not client.get(base + "&q=other").json()["items"]
        assert client.get(
            base + "&category=research_internship&category=early_career&q=Institute"
        ).json()["items"]
        assert client.get(base + "&category=unknown").status_code == 422
        assert client.get(base + "&status=unknown").status_code == 422


def test_source_month_ranges_remain_month_precision():
    item = programme("iitk-surge", opening="2027-01-01", closing="2027-03-31")
    result = build_calendar(
        [item],
        date(2027, 1, 1),
        date(2027, 12, 31),
        categories=[],
        statuses=[],
        q="",
        now=datetime(2027, 2, 1, tzinfo=IST),
    )
    assert result.items[0].edition.opens_until.month == 2
    assert result.items[0].edition.closes_from.month == 2


def test_recurring_rule_covers_requested_year_without_saved_edition():
    niti = programme("niti-aayog-internship", status="announced")
    with request_client([niti]) as client:
        result = client.get("/calendar?from=2026-12-01&to=2026-12-31").json()
        future = client.get("/calendar?from=2028-01-01&to=2028-12-31").json()
    assert len(result["items"]) == 1
    assert result["items"][0]["edition"]["year"] == 2026
    assert len(future["items"]) == 12


@pytest.mark.parametrize(
    "basis,official",
    [
        ("Official Annual Rule", True),
        ("official standing rule", True),
        ("Official Monthly Rule", True),
        ("Official Standing Annual Recruitment Pattern", True),
        ("Tentative (Historical Annual Trend)", False),
        ("Official 2027 Published", False),
    ],
)
def test_recurrence_recognises_standing_source_basis(basis, official, monkeypatch):
    row = {**ROWS["OPP-045"], "date_basis": basis}
    monkeypatch.setitem(ROWS, "OPP-045", row)
    meta = {"row_id": "OPP-045", "recurrence": {}}
    assert recurrence_is_official(meta) is official
    meta["recurrence"]["basis"] = "tentative"
    assert not recurrence_is_official(meta)
    meta["recurrence"]["basis"] = "official"
    assert recurrence_is_official(meta)


def test_all_recurrence_rules_have_reviewed_basis_and_source_precision():
    expected = {
        "niti-aayog-internship": True,
        "rbi-research-internship": True,
        "nicsi-paid-internship": False,
        "outreachy": False,
        "lfx-mentorship": False,
    }
    assert {slug for slug, meta in CALENDAR_META.items() if meta.get("recurrence")} == set(expected)
    for slug, official in expected.items():
        meta = CALENDAR_META[slug]
        assert meta["recurrence"]["basis"] == ("official" if official else "tentative")
        assert recurrence_is_official(meta) is official
        window = source_window(slug)
        assert window["status"] == ("announced" if official else "expected")
        assert (
            window["opens_precision"]
            == window["closes_precision"]
            == ("day" if official else "month")
        )


@pytest.mark.parametrize("stored_year", [2026, 2027])
@pytest.mark.parametrize("stored_status", ["expected", "closed"])
@pytest.mark.parametrize(
    "today,status,label",
    [
        ("2026-11-30", "announced", "Official"),
        ("2026-12-05", "open", "Open now"),
        ("2026-12-11", "closed", "Closed"),
    ],
)
def test_niti_december_official_occurrence_uses_window_dates(
    stored_year, stored_status, today, status, label, monkeypatch
):
    from api import calendar as calendar_api

    now = datetime.fromisoformat(today).replace(hour=12, tzinfo=IST)

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz)

    monkeypatch.setattr(calendar_api, "datetime", FixedDatetime)
    item = source_programme("niti-aayog-internship")
    item.url = ROWS["OPP-045"]["official_portal"]
    item.editions[0].year = stored_year
    item.editions[0].status = stored_status
    query = "/calendar?from=2026-12-01&to=2026-12-31&q=NITI"
    with request_client([item]) as client:
        response = client.get(query)
        assert response.status_code == 200
        result = response.json()
        assert len(result["items"]) == 1
        occurrence = result["items"][0]
        edition = occurrence["edition"]
        assert edition["year"] == 2026
        assert edition["basis"] == "official"
        assert edition["opens_precision"] == edition["closes_precision"] == "day"
        assert datetime.fromisoformat(edition["opens_at"]).date() == date(2026, 12, 1)
        assert datetime.fromisoformat(edition["closes_at"]).date() == date(2026, 12, 10)
        assert edition["status"] == status
        assert edition["status_label"] == label
        assert occurrence["is_open_now"] is (status == "open")
        assert occurrence["programme"]["url"] == ROWS["OPP-045"]["official_portal"]
        assert len(client.get(query + f"&status={status}").json()["items"]) == 1
        assert bool(client.get(query + "&status=open").json()["items"]) is (status == "open")


@pytest.mark.parametrize("stored_status", ["expected", "announced", "open", "closed"])
def test_historical_recurrence_stays_tentative_despite_saved_status(stored_status):
    item = source_programme("outreachy")
    item.editions[0].status = stored_status
    result = build_calendar(
        [item],
        date(2027, 8, 1),
        date(2027, 8, 31),
        categories=[],
        statuses=[],
        q="",
        now=datetime(2027, 8, 5, tzinfo=IST),
    )
    assert len(result.items) == 1
    occurrence = result.items[0]
    assert occurrence.edition.basis == "tentative"
    assert occurrence.edition.status == "expected"
    assert occurrence.edition.opens_precision == occurrence.edition.closes_precision == "month"
    assert not occurrence.is_open_now


def test_public_cache_keys_include_ranges_filters_and_repeated_categories(monkeypatch):
    from api import middleware

    cache = {}

    async def get_cached(redis, key, **kwargs):
        return cache.get(key)

    async def set_cached(redis, key, value, ttl, **kwargs):
        cache[key] = value

    monkeypatch.setattr(middleware, "cache_get", get_cached)
    monkeypatch.setattr(middleware, "cache_set", set_cached)
    monkeypatch.setattr(middleware, "get_redis", lambda: None)
    client = request_client([programme()])
    client.app.add_middleware(middleware.ReadCacheMiddleware)
    base = "/calendar?from=2027-01-01&to=2027-12-31"
    with client:
        first = client.get(base)
        assert first.headers["x-cache"] == "MISS"
        assert first.headers["cache-control"].startswith("public,")
        assert client.get(base).headers["x-cache"] == "HIT"
        assert client.get(base + "&q=unmatched").json()["items"] == []
        assert client.get(base + "&category=early_career").json()["items"] == []
        assert client.get(base + "&category=early_career&category=research_internship").json()[
            "items"
        ]
        assert client.get(base.replace("2027-12-31", "2027-01-05")).json()["items"] == []
    assert len(cache) == 5
