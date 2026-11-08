"""Recorded NVIDIA career-site JSON; mutations exercise paging/failure edges."""

import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from crawlers import workday
from crawlers import runner
from crawlers.runner import ATS_ADAPTERS, _coverage_from_adapter
from scripts.seed_companies import _ADAPTER_SOURCES

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def captures():
    return (
        json.loads((FIXTURES / "workday_search_sample.json").read_text(encoding="utf-8-sig")),
        json.loads((FIXTURES / "workday_detail_sample.json").read_text(encoding="utf-8-sig")),
    )


def _adapter(monkeypatch, handler):
    adapter = workday.WorkdayAdapter("nvidia|wd5|NVIDIAExternalCareerSite", "NVIDIA")
    adapter._client.close()
    adapter._client = httpx.Client(
        transport=httpx.MockTransport(handler), headers={"User-Agent": workday.USER_AGENT}
    )
    monkeypatch.setattr(workday, "sleep", lambda _delay: None)
    return adapter


def _robots():
    return httpx.Response(
        200, text="User-agent: *\nAllow: /NVIDIAExternalCareerSite/\nDisallow: /talentcommunity/\n"
    )


def test_search_paging_union_student_filter_and_detail(monkeypatch, captures):
    captured_search, captured_detail = captures
    template = captured_search["jobPostings"][0]
    postings = [
        template
        | {
            "externalPath": f"/job/Shanghai/Intern_JR{index}",
            "title": "Software Engineering Intern",
        }
        for index in range(21)
    ]
    false_positive = template | {
        "externalPath": "/job/Shanghai/International_Manager",
        "title": "International Sales Manager",
    }
    calls = []
    details = []

    def respond(request):
        calls.append(request)
        if request.url.path == "/robots.txt":
            return _robots()
        if request.method == "POST":
            body = json.loads(request.content)
            assert body["limit"] == 20 and body["appliedFacets"] == {}
            term, offset = body["searchText"], body["offset"]
            if term == "intern":
                return httpx.Response(
                    200, json={"total": 21, "jobPostings": postings[offset : offset + 20]}
                )
            if term == "graduate":
                return httpx.Response(
                    200, json={"total": 2, "jobPostings": [postings[0], false_positive]}
                )
            return httpx.Response(200, json={"total": 0, "jobPostings": []})
        details.append(request.url.path)
        suffix = request.url.path.rsplit("/", 1)[-1]
        info = captured_detail["jobPostingInfo"] | {
            "title": "Software Engineering Intern",
            "jobReqId": suffix,
            "externalUrl": f"https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/job/Shanghai/{suffix}",
        }
        return httpx.Response(200, json={"jobPostingInfo": info})

    adapter = _adapter(monkeypatch, respond)
    listings = adapter.fetch()
    assert len(listings) == 21
    assert len(details) == 21 and not any("International_Manager" in path for path in details)
    assert adapter.health() == "ok"
    assert adapter.coverage()["status"] == "complete"
    assert adapter.coverage()["mode"] == "search"
    assert adapter.coverage()["expected_total"] is None
    search_bodies = [json.loads(request.content) for request in calls if request.method == "POST"]
    assert [body["offset"] for body in search_bodies if body["searchText"] == "intern"] == [0, 20]
    assert set(body["searchText"] for body in search_bodies) == set(workday.SEARCH_TERMS)
    parsed = adapter.parse(listings[0])
    info = captured_detail["jobPostingInfo"]
    assert parsed.company_name == "NVIDIA"
    assert parsed.posted_at == datetime.fromisoformat(info["startDate"]).replace(tzinfo=UTC)
    assert parsed.location == info["location"] and parsed.country == "CN"
    assert "<p>" not in parsed.description_raw and "DFT" in parsed.description_raw
    assert parsed.apply_url == listings[0].source_url
    assert parsed.deadline is None and parsed.deadline_confidence == "unknown"
    assert parsed.category == "internship"
    assert ATS_ADAPTERS["workday"] is workday.WorkdayAdapter
    assert "workday" in _ADAPTER_SOURCES


def test_later_pages_reporting_total_zero_still_page(monkeypatch, captures):
    """Real Workday answers total=0 after the first page (NVIDIA, 2026-11-08)."""
    captured_search, captured_detail = captures
    template = captured_search["jobPostings"][0]
    postings = [
        template | {"externalPath": f"/job/Pune/Intern_JR{index}", "title": "Data Intern"}
        for index in range(25)
    ]

    def respond(request):
        if request.url.path == "/robots.txt":
            return _robots()
        if request.method == "POST":
            body = json.loads(request.content)
            if body["searchText"] != "intern":
                return httpx.Response(200, json={"total": 0, "jobPostings": []})
            offset = body["offset"]
            total = 25 if offset == 0 else 0
            return httpx.Response(
                200, json={"total": total, "jobPostings": postings[offset : offset + 20]}
            )
        info = captured_detail["jobPostingInfo"] | {"title": "Data Intern"}
        return httpx.Response(200, json={"jobPostingInfo": info})

    adapter = _adapter(monkeypatch, respond)
    listings = adapter.fetch()
    assert len(listings) == 25
    assert adapter.health() == "ok"
    assert adapter.last_board_state == "ok"
    assert adapter.coverage()["details"]["totals_by_term"]["intern"] == 25


def test_recorded_detail_fallbacks_and_additional_locations(monkeypatch, captures):
    search, detail = captures
    posting = search["jobPostings"][0]
    info = copy.deepcopy(detail["jobPostingInfo"])
    info.pop("jobReqId")
    info.pop("externalUrl")
    info["additionalLocations"] = ["Remote, India"]
    info["startDate"] = "not a date"
    info["postedOn"] = "Posted 30+ Days Ago"

    def respond(request):
        if request.url.path == "/robots.txt":
            return _robots()
        if request.method == "POST":
            return httpx.Response(200, json={"total": 1, "jobPostings": [posting]})
        return httpx.Response(200, json={"jobPostingInfo": info})

    adapter = _adapter(monkeypatch, respond)
    listings = adapter.fetch()
    assert len(listings) == 1
    raw = listings[0]
    parsed = adapter.parse(raw)
    assert raw.external_id == posting["externalPath"]
    assert (
        parsed.apply_url == adapter.base_url + "/NVIDIAExternalCareerSite" + posting["externalPath"]
    )
    assert parsed.is_remote is True and "Remote, India" in parsed.location
    assert (
        datetime.now(UTC) - timedelta(days=31)
        < parsed.posted_at
        < datetime.now(UTC) - timedelta(days=29)
    )


@pytest.mark.parametrize(
    "posted,days",
    [
        ("Posted 30+ Days Ago", 30),
        ("Posted 1 Day Ago", 1),
        ("Posted Today", 0),
        ("Posted Yesterday", 1),
    ],
)
def test_relative_posted_dates(posted, days):
    now = datetime(2026, 11, 8, tzinfo=UTC)
    assert workday.parse_posted_at(None, posted, now=now) == now - timedelta(days=days)
    assert workday.parse_posted_at("2026-09-01", posted, now=now) == datetime(
        2026, 9, 1, tzinfo=UTC
    )
    assert workday.parse_posted_at(None, "Recently", now=now) is None


def test_capped_search_is_healthy_and_partial(monkeypatch, captures):
    search, detail = captures
    posting = search["jobPostings"][0]
    offsets = []

    def respond(request):
        if request.url.path == "/robots.txt":
            return _robots()
        if request.method == "POST":
            body = json.loads(request.content)
            if body["searchText"] == "intern":
                offsets.append(body["offset"])
                return httpx.Response(200, json={"total": 101, "jobPostings": [posting] * 20})
            return httpx.Response(200, json={"total": 0, "jobPostings": []})
        return httpx.Response(200, json=detail)

    adapter = _adapter(monkeypatch, respond)
    assert adapter.fetch()
    assert offsets == [0, 20, 40]
    assert adapter.health() == "ok"
    assert adapter.coverage()["details"]["capped_terms"] == ["intern"]
    coverage = _coverage_from_adapter(adapter, "workday", 1, health=adapter.health())
    assert coverage["status"] == "partial"
    assert adapter.last_board_state == "ok" and adapter.last_http_status == 200


@pytest.mark.parametrize("status", [404, 410])
def test_missing_tenant_returns_partial_without_exception(monkeypatch, status):
    adapter = _adapter(
        monkeypatch,
        lambda request: _robots() if request.url.path == "/robots.txt" else httpx.Response(status),
    )
    assert adapter.fetch() == []
    assert adapter.health() == "degraded"
    assert adapter.coverage()["status"] == "partial"
    assert adapter.last_board_state == "not_found" and adapter.last_http_status == status


def test_robots_disallowed_site_makes_no_search_request(monkeypatch):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, text="User-agent: *\nDisallow: /NVIDIAExternalCareerSite/\n")

    adapter = _adapter(monkeypatch, respond)
    assert adapter.fetch() == []
    assert len(requests) == 1
    assert adapter.health() == "degraded"


def test_budget_counts_retries_and_paces_requests(monkeypatch, captures):
    search, detail = captures
    posting = search["jobPostings"][0]
    requests = []
    waits = []

    def respond(request):
        requests.append(request)
        if request.url.path == "/robots.txt":
            return _robots()
        if request.method == "POST":
            body = json.loads(request.content)
            jobs = [
                posting
                | {
                    "externalPath": f"/job/Shanghai/{body['searchText'].replace(' ', '-')}-{index}",
                    "title": "Engineering Intern",
                }
                for index in range(20)
            ]
            return httpx.Response(200, json={"total": 20, "jobPostings": jobs})
        return httpx.Response(429, headers={"Retry-After": "2"})

    adapter = _adapter(monkeypatch, respond)
    monkeypatch.setattr(workday, "sleep", waits.append)
    adapter.fetch()
    assert len(requests) == workday.REQUEST_BUDGET
    assert adapter.coverage()["details"]["requests_made"] == 45
    assert waits.count(0.5) == len(requests) and 2.0 in waits
    assert adapter.health() == "degraded" and adapter.coverage()["status"] == "partial"


@pytest.mark.parametrize(
    "response",
    [httpx.Response(200, json={}), httpx.Response(200, text="bad json"), httpx.Response(503)],
)
def test_failed_search_is_partial(monkeypatch, response):
    def respond(request):
        return _robots() if request.url.path == "/robots.txt" else response

    adapter = _adapter(monkeypatch, respond)
    assert adapter.fetch() == []
    assert adapter.health() == "degraded" and adapter.coverage()["status"] == "partial"
    assert adapter.last_board_state == "error"


def test_empty_search_is_ok_board_evidence_without_zero_retry(monkeypatch):
    requests = []

    def respond(request):
        requests.append(request)
        if request.url.path == "/robots.txt":
            return _robots()
        return httpx.Response(200, json={"total": 0, "jobPostings": []})

    adapter = _adapter(monkeypatch, respond)
    assert adapter.fetch() == []
    assert adapter.health() == "ok"
    assert adapter.last_board_state == "ok" and adapter.last_http_status == 200
    requests.clear()
    monkeypatch.setitem(runner.ATS_ADAPTERS, "workday", lambda **kwargs: adapter)
    job = runner._AtsJob(
        1, 2, "nvidia", "workday", adapter.board_token, "NVIDIA", previously_had_listings=True
    )
    fetched = runner._fetch_company_board(job)
    assert len(requests) == len(workday.SEARCH_TERMS) + 1
    assert fetched.coverage["board_outcome"] == {"board_state": "ok", "http_status": 200}


def test_relevance_ranked_junk_stops_a_term_without_degrading_health(monkeypatch, captures):
    search, _detail = captures
    junk = search["jobPostings"][0] | {"title": "International Sales Manager"}
    offsets = []

    def respond(request):
        if request.url.path == "/robots.txt":
            return _robots()
        body = json.loads(request.content)
        if body["searchText"] == "intern":
            offsets.append(body["offset"])
            return httpx.Response(200, json={"total": 400, "jobPostings": [junk] * 20})
        return httpx.Response(200, json={"total": 0, "jobPostings": []})

    adapter = _adapter(monkeypatch, respond)
    assert adapter.fetch() == []
    assert offsets == [0]
    assert workday.SEARCH_TERMS == ("intern", "graduate", "co-op", "apprentice", "entry level")
    assert adapter.health() == "ok"
    assert adapter.coverage()["status"] == "partial"
    assert adapter.coverage()["details"]["early_stopped_terms"] == ["intern"]
    assert adapter.last_board_state == "ok"


def test_detail_budget_keeps_all_search_postings_with_stable_ids(monkeypatch, captures):
    search, detail = captures
    template = search["jobPostings"][0]
    requests = []

    def respond(request):
        requests.append(request)
        if request.url.path == "/robots.txt":
            return _robots()
        if request.method == "POST":
            term = json.loads(request.content)["searchText"].replace(" ", "-")
            jobs = [
                template
                | {
                    "title": "Engineering Intern",
                    "externalPath": f"/job/Shanghai/{term}-{index}",
                    "bulletFields": [f"{term}-{index}"],
                }
                for index in range(20)
            ]
            return httpx.Response(200, json={"total": 20, "jobPostings": jobs})
        job_id = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(
            200,
            json={
                "jobPostingInfo": detail["jobPostingInfo"]
                | {
                    "jobReqId": job_id,
                    "externalUrl": f"https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/job/Shanghai/{job_id}",
                }
            },
        )

    adapter = _adapter(monkeypatch, respond)
    listings = adapter.fetch()
    assert len(requests) == 45 and len(listings) == 100
    assert len({raw.external_id for raw in listings}) == 100
    fallback = [adapter.parse(raw) for raw in listings if raw.raw_payload.get("detail_fallback")]
    assert len(fallback) == 61
    assert all(
        item.description_raw == "" and item.location == template["locationsText"]
        for item in fallback
    )
    assert all(
        item.apply_url.endswith(item.external_id) and item.posted_at is not None
        for item in fallback
    )
    assert adapter.health() == "ok" and adapter.coverage()["status"] == "partial"
    assert adapter.last_board_state == "ok" and adapter.last_http_status == 200
    assert adapter.coverage()["details"]["limits"] == ["request_budget"]


def test_time_budget_preserves_kept_postings(monkeypatch, captures):
    search, detail = captures
    clock = [0.0]

    def respond(request):
        clock[0] += 0.5
        if request.url.path == "/robots.txt":
            return _robots()
        if request.method == "POST":
            body = json.loads(request.content)
            jobs = (
                [
                    search["jobPostings"][0]
                    | {
                        "title": "Engineering Intern",
                        "externalPath": f"/job/Shanghai/{index}",
                        "bulletFields": [f"R{index}"],
                    }
                    for index in range(body["offset"], body["offset"] + 20)
                ]
                if body["searchText"] == "intern"
                else []
            )
            return httpx.Response(200, json={"total": 60 if jobs else 0, "jobPostings": jobs})
        return httpx.Response(200, json=detail)

    adapter = _adapter(monkeypatch, respond)
    monkeypatch.setattr(workday, "monotonic", lambda: clock[0])
    monkeypatch.setattr(workday, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    listings = adapter.fetch()
    assert len(listings) == 60
    assert any(raw.raw_payload.get("detail_fallback") for raw in listings)
    assert "time_budget" in adapter.coverage()["details"]["limits"]
    assert clock[0] <= 25
    assert adapter.health() == "ok" and adapter.coverage()["status"] == "partial"


def test_detail_failure_does_not_claim_missing_board(monkeypatch, captures):
    search, _detail = captures

    def respond(request):
        if request.url.path == "/robots.txt":
            return _robots()
        if request.method == "POST":
            return httpx.Response(200, json={"total": 1, "jobPostings": search["jobPostings"][:1]})
        return httpx.Response(404)

    adapter = _adapter(monkeypatch, respond)
    assert adapter.fetch() == []
    assert adapter.health() == "degraded"
    assert adapter.last_board_state == "ok" and adapter.last_http_status == 200


def test_local_time_limit_during_detail_request_is_healthy_fallback(monkeypatch, captures):
    search, _detail = captures
    clock = [0.0]

    def respond(request):
        if request.url.path == "/robots.txt":
            return _robots()
        if request.method == "POST":
            return httpx.Response(200, json={"total": 1, "jobPostings": search["jobPostings"][:1]})
        clock[0] = workday.FETCH_MAX_SECONDS
        raise httpx.ReadTimeout("local detail time budget", request=request)

    adapter = _adapter(monkeypatch, respond)
    monkeypatch.setattr(workday, "monotonic", lambda: clock[0])
    listings = adapter.fetch()
    assert len(listings) == 1 and listings[0].raw_payload["detail_fallback"] is True
    assert adapter.health() == "ok"
    assert adapter.coverage()["details"]["limits"] == ["time_budget"]
    assert adapter.coverage()["status"] == "partial"


def test_search_timeout_is_an_error_board(monkeypatch):
    def respond(request):
        if request.url.path == "/robots.txt":
            return _robots()
        raise httpx.ReadTimeout("fixture timeout", request=request)

    adapter = _adapter(monkeypatch, respond)
    assert adapter.fetch() == []
    assert adapter.health() == "degraded"
    assert adapter.last_board_state == "error" and adapter.last_http_status is None
