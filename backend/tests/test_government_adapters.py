"""Trimmed public captures, with every HTTP request intercepted."""

import copy
import json
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pytest

from core.organisers import classify_organiser
from crawlers import government as gov
from crawlers.drdo import DrdoAdapter
from crawlers.isro import IsroAdapter
from crawlers.meity import MeityCareersAdapter
from crawlers.nec import NecInternshipsAdapter
from crawlers.nic_dii import NicDiiAdapter

FIXTURES = Path(__file__).parent / "fixtures" / "gov"
ADAPTERS = (MeityCareersAdapter, NicDiiAdapter, DrdoAdapter, NecInternshipsAdapter, IsroAdapter)
NOW = datetime(2026, 11, 12, 12, tzinfo=gov.IST)
PATHS = {
    "/cms/wp-json/post-page/careers_post": "meity.json",
    "/": "nic-home.html",
    "/timelines": "nic-schedule.html",
    "/drdo/en/offerings/vacancies": "drdo.html",
    "/nec-internship-applications": "nec.html",
    "/nec-internship-applications-winter-session-last-date-apply-30th-november-2026": "nec-detail.html",
    "/CurrentOpportunities.html": "isro.html",
    "/URSCRecruitment13.html": "isro-open.html",
}


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def adapter(
    monkeypatch,
    cls,
    *,
    overrides=None,
    robot_status=200,
    robot_text="User-agent: *\nAllow: /",
    handler=None,
):
    instance = cls(now=lambda: NOW)
    instance._client.close()
    requests = []

    def respond(request):
        requests.append(request)
        assert request.headers["User-Agent"] == gov.USER_AGENT
        if request.url.path == "/robots.txt":
            return httpx.Response(robot_status, text=robot_text)
        if handler:
            response = handler(request)
            if response is not None:
                return response
        name = PATHS[request.url.path]
        data = (overrides or {}).get(name, fixture(name))
        if isinstance(data, tuple):
            return httpx.Response(data[0], text=data[1])
        return httpx.Response(200, text=data)

    instance._client = httpx.Client(
        transport=httpx.MockTransport(respond), headers={"User-Agent": gov.USER_AGENT}
    )
    monkeypatch.setattr(gov, "sleep", lambda _seconds: None)
    return instance, requests


@pytest.mark.parametrize("cls,expected", list(zip(ADAPTERS, [3, 1, 7, 1, 1])))
def test_captured_mapping_and_counts(monkeypatch, cls, expected):
    source, requests = adapter(monkeypatch, cls)
    raw = source.fetch()
    assert source.health() == "ok", source.coverage()
    assert source.coverage()["status"] == "complete"
    assert len(raw) == source.filter_counts()["student_relevant_count"] == expected
    parsed = [source.parse(row) for row in raw]
    for row, result in zip(raw, parsed):
        assert row.content_hash == gov.content_hash(row.raw_payload)
        assert result.title == row.raw_payload["title"]
        assert result.company_name == row.raw_payload["company"]
        assert classify_organiser(result.company_name) == "government"
        assert result.country == "IN"
        assert result.source_url == result.apply_url == row.source_url
        assert result.source_url.startswith(("http://", "https://"))
        assert result.deadline.utcoffset() == timedelta(hours=5, minutes=30)
        assert result.meta["original_dates"]
        assert result.meta["summary_source"] == "extracted"
    assert sum(r.url.path == "/robots.txt" for r in requests) == 1
    if cls is MeityCareersAdapter:
        assert {p.external_id for p in parsed} == {"30040", "30032", "30029"}
        assert parsed[0].company_name == "National e-Governance Division"
        assert parsed[0].title == "NeGD's Technical Internship Programme - 2026"
        assert parsed[0].category == "internship"
        assert parsed[0].deadline == datetime(2026, 11, 20, 23, 59, 59, tzinfo=gov.IST)
        assert parsed[-1].category == "job"
        assert parsed[-1].company_name == "Digital India Corporation"
        assert parsed[0].posted_at == datetime(2026, 11, 11, tzinfo=gov.IST)
        assert parsed[0].source_url.endswith("032b92c51d45d44365455c98ea37b0eb.pdf")
    elif cls is NicDiiAdapter:
        assert parsed[0].title == "Digital India Internship – Winter 2026"
        assert parsed[0].external_id == "winter-2026"
        assert parsed[0].company_name == "National Informatics Centre"
        assert parsed[0].category == "internship"
        assert parsed[0].deadline == datetime(2026, 11, 13, 16, 59, 59, tzinfo=gov.IST)
        assert parsed[0].source_url == "https://dii.nic.in/timelines"
        assert parsed[0].posted_at == datetime(2026, 11, 2, tzinfo=gov.IST)
        assert "30th January 2027" in parsed[0].meta["original_dates"]["Completion of Internship"]
        assert "31st January, 2027" in parsed[0].meta["homepage_programme_duration"][0]
    elif cls is DrdoAdapter:
        internship = next(p for p in parsed if p.external_id.startswith("dgre/"))
        assert internship.company_name == "DRDO – DGRE"
        assert internship.location == "Chandigarh"
        assert internship.category == "internship"
        assert internship.deadline == datetime(2026, 12, 6, 23, 59, 59, tzinfo=gov.IST)
        assert all(p.deadline_confidence == "inferred" for p in parsed)
        assert next(p for p in parsed if "/jrf/" in p.external_id).category == "job"
    elif cls is NecInternshipsAdapter:
        assert parsed[0].external_id == "winter-2026"
        assert parsed[0].company_name == "North Eastern Council"
        assert parsed[0].category == "internship"
        assert parsed[0].deadline == datetime(2026, 11, 30, 23, 59, 59, tzinfo=gov.IST)
        assert parsed[0].posted_at is None
        assert parsed[0].location is None
    else:
        assert parsed[0].external_id == "URSCRecruitment13.html"
        assert parsed[0].company_name == "ISRO – U. R. Rao Satellite Centre (URSC)"
        assert parsed[0].location == "Bengaluru"
        assert parsed[0].category == "job"
        assert parsed[0].deadline == datetime(2026, 11, 13, 23, 59, 59, tzinfo=gov.IST)
        assert parsed[0].posted_at == datetime(2026, 10, 24, tzinfo=gov.IST)
        # Multiple logical notices inside the same .row.list are retained.
        assert source.coverage()["expected_total"] == 13
        assert source.filter_counts()["skipped_closed"] == 12
    assert (
        all(p.deadline_confidence == "explicit" for p in parsed) if cls is not DrdoAdapter else True
    )


@pytest.mark.parametrize("cls", ADAPTERS)
def test_robots_disallowed_fetches_no_listing(monkeypatch, cls):
    source, requests = adapter(monkeypatch, cls, robot_text="User-agent: AspirovaBot\nDisallow: /")
    assert source.fetch() == []
    assert source.health() == "broken"
    assert [r.url.path for r in requests] == ["/robots.txt"]
    assert source.coverage()["status"] == "partial"


@pytest.mark.parametrize("cls", ADAPTERS)
@pytest.mark.parametrize("failure", ["captcha", "203", "truncated", "missing"])
def test_invalid_inventory_is_never_empty_success(monkeypatch, cls, failure):
    name = {
        MeityCareersAdapter: "meity.json",
        NicDiiAdapter: "nic-schedule.html",
        DrdoAdapter: "drdo.html",
        NecInternshipsAdapter: "nec.html",
        IsroAdapter: "isro.html",
    }[cls]
    challenge = "<html><head><title>CAPTCHA access denied</title></head></html>"
    bad = {
        "captcha": challenge,
        "203": (203, fixture(name)),
        "truncated": fixture(name)[: len(fixture(name)) // 2],
        "missing": "{}" if cls is MeityCareersAdapter else "<html><body>Error</body></html>",
    }[failure]
    source, _ = adapter(monkeypatch, cls, overrides={name: bad})
    assert source.fetch() == []
    assert source.health() == "degraded"
    assert source.coverage()["status"] == "partial"


@pytest.mark.parametrize("cls", ADAPTERS)
def test_runtime_robots_cache_resets_on_next_crawl(monkeypatch, cls):
    source, requests = adapter(monkeypatch, cls)
    source.fetch()
    source.fetch()
    assert sum(r.url.path == "/robots.txt" for r in requests) == 2


@pytest.mark.parametrize("cls", ADAPTERS)
def test_extension_preserves_notice_identity(monkeypatch, cls):
    source, _ = adapter(monkeypatch, cls)
    before = {r.external_id: r for r in source.fetch()}
    overrides = {}
    if cls is MeityCareersAdapter:
        overrides["meity.json"] = (
            fixture("meity.json")
            .replace("20/11/2026", "25/11/2026")
            .replace("20th November", "25th November")
        )
    elif cls is NicDiiAdapter:
        overrides["nic-home.html"] = fixture("nic-home.html").replace("2026-11-13T", "2026-11-15T")
        overrides["nic-schedule.html"] = fixture("nic-schedule.html").replace(
            "13<sup>th</sup>", "15<sup>th</sup>"
        )
    elif cls is DrdoAdapter:
        overrides["drdo.html"] = fixture("drdo.html").replace("01/12/2026", "05/12/2026")
    elif cls is NecInternshipsAdapter:
        for name in ("nec.html", "nec-detail.html"):
            overrides[name] = fixture(name).replace("30th November 2026", "5th January 2027")
    else:
        overrides["isro.html"] = fixture("isro.html").replace(
            "November 13, 2026", "November 20, 2026"
        )
        overrides["isro-open.html"] = fixture("isro-open.html").replace(
            "November 13, 2026", "November 20, 2026"
        )
    changed, _ = adapter(monkeypatch, cls, overrides=overrides)
    after = {r.external_id: r for r in changed.fetch()}
    assert changed.health() == "ok", changed.coverage()
    assert before.keys() == after.keys()
    updated = [key for key in before if before[key].content_hash != after[key].content_hash]
    assert updated
    for key in updated:
        assert changed.parse(after[key]).deadline > source.parse(before[key]).deadline


def test_meity_deadline_conflict_and_missing_acf(monkeypatch):
    source, _ = adapter(monkeypatch, MeityCareersAdapter)
    posts = json.loads(fixture("meity.json"))["posts"]
    senior = source.notice(next(p for p in posts if p["ID"] == 29863))
    assert senior["deadline"] is None
    assert senior["meta"]["deadline_conflict"] is True
    assert senior["meta"]["application_dates_in_content"] == ["15.12.2026"]
    missing = source.notice(next(p for p in posts if p["ID"] == 29259))
    assert missing["meta"]["missing_acf"] is True
    assert missing["confidence"] == "unknown"


def test_meity_pagination_count_and_duplicate_guards(monkeypatch):
    posts = json.loads(fixture("meity.json"))["posts"]
    generated = [copy.deepcopy(posts[2]) | {"ID": index} for index in range(1, 52)]

    def handler(request):
        page = int(request.url.params["page"])
        return httpx.Response(
            200,
            json={
                "posts": generated[(page - 1) * 50 : page * 50],
                "total_items": 51,
                "total_pages": 2,
                "current_page": page,
            },
        )

    source, requests = adapter(monkeypatch, MeityCareersAdapter, handler=handler)
    assert len(source.fetch()) == 51
    assert source.health() == "ok"
    assert [r.url.params.get("page") for r in requests[1:]] == ["1", "2"]
    generated[-1]["ID"] = generated[0]["ID"]
    assert source.fetch() == []
    assert source.health() == "degraded"
    generated.pop()
    assert source.fetch() == []
    assert source.health() == "degraded"


def test_meity_page_cap_is_not_partial_success(monkeypatch):
    def handler(request):
        return httpx.Response(
            200, json={"posts": [], "total_items": 300, "total_pages": 6, "current_page": 1}
        )

    source, _ = adapter(monkeypatch, MeityCareersAdapter, handler=handler)
    assert source.fetch() == []
    assert source.health() == "degraded"


def test_nic_schedule_fallback_and_conflict(monkeypatch):
    home = fixture("nic-home.html")
    source, _ = adapter(
        monkeypatch,
        NicDiiAdapter,
        overrides={"nic-home.html": home.replace("registrationEnd", "removedEnd")},
    )
    result = source.parse(source.fetch()[0])
    assert result.deadline == datetime(2026, 11, 13, 23, 59, 59, tzinfo=gov.IST)
    assert result.meta["deadline_precision"] == "day"
    broken, _ = adapter(
        monkeypatch,
        NicDiiAdapter,
        overrides={"nic-home.html": home.replace("2026-11-13T", "2026-11-14T")},
    )
    assert broken.fetch() == []
    assert broken.health() == "degraded"


def test_drdo_original_and_extension_are_one_notice(monkeypatch):
    tree = gov.html_tree(fixture("drdo.html"))
    # Duplicate the real CASDIC extension as an earlier original in the same board.
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(fixture("drdo.html"), "html.parser")
    extension = next(c for c in soup.select(".vacanciess-box-content") if "CASDIC" in c.get_text())
    original = str(extension).replace("01/12/2026", "20/11/2026").replace("Date Extension in ", "")
    assert len(list(tree.nodes(cls="vacanciess-box-content"))) == 11
    source, _ = adapter(
        monkeypatch,
        DrdoAdapter,
        overrides={"drdo.html": fixture("drdo.html").replace("</body>", original + "</body>")},
    )
    rows = source.fetch()
    casdic = [r for r in rows if r.external_id.startswith("casdic/")]
    assert len(casdic) == 1
    assert source.parse(casdic[0]).deadline.day == 1
    assert source.parse(casdic[0]).deadline.month == 12
    assert source.filter_counts()["duplicates"] == 1


def test_drdo_and_nec_pagination_is_not_ignored(monkeypatch):
    for cls, name in ((DrdoAdapter, "drdo.html"), (NecInternshipsAdapter, "nec.html")):
        data = fixture(name).replace("</body>", '<a rel="next" href="?page=1">Next</a></body>')
        source, _ = adapter(monkeypatch, cls, overrides={name: data})
        assert source.fetch() == []
        assert source.health() == "degraded"


def test_isro_detail_overrides_cutoff_and_closed_status(monkeypatch):
    extended, _ = adapter(
        monkeypatch,
        IsroAdapter,
        overrides={
            "isro-open.html": fixture("isro-open.html").replace(
                "November 13, 2026", "November 22, 2026"
            )
        },
    )
    assert extended.parse(extended.fetch()[0]).deadline.day == 22
    closed, _ = adapter(
        monkeypatch,
        IsroAdapter,
        overrides={"isro-open.html": fixture("isro-open.html").replace("Open /", "Closed /")},
    )
    assert closed.fetch() == []
    assert closed.health() == "ok"
    expired, requests = adapter(monkeypatch, IsroAdapter)
    expired._now = lambda: datetime(2027, 1, 1, tzinfo=gov.IST)
    assert expired.fetch() == []
    assert expired.health() == "ok"
    assert len(requests) == 2  # robots + catalogue; no historical details


@pytest.mark.parametrize(
    "title,keep",
    [
        (
            "STQC Directorate is inviting applications for various positions on deputation basis.",
            False,
        ),
        (
            "Digital India BHASHINI Division-DIC is currently inviting applications for the Manager-Admin position purely on Contract/Consolidated basis",
            False,
        ),
        ("Filling up the post of Director General, NIELIT on regular basis", False),
        (
            "DMRL, Hyderabad invites application for engagement of Retired Government Employees as 'Consultant' on contract basis",
            False,
        ),
        ("Provisionally Selected List of JRF in DYSL-CT, Chennai", False),
        ("NeGD's Technical Internship Programme - 2026", True),
        ("Digital India Internship – Winter 2026", True),
        (
            "DMRL, Hyderabad invites application for the post of Junior Research Fellowship (JRF)",
            True,
        ),
        ("DMRL, Hyderabad invites application for the post of Research Associate (RA)", True),
        (
            "Date Extension in CASDIC, Bengaluru advertisement for paid internship for BE/B.Tech And M.Sc Students",
            True,
        ),
        (
            "NEC Internship Applications for winter session (Last date to apply is 30th November 2026)",
            True,
        ),
        (
            "Recruitment to the posts of Technician - B/ Heavy Vehicle Driver - A/ Light Vehicle Driver - A/ Staff Car Driver- A",
            True,
        ),
        ("Senior Research Fellow (SRF)", True),
        ("Project Fellow", True),
        ("Young Professionals", True),
        ("Graduate Apprentices", True),
        ("Graduate Trainees", True),
        ("Internship results", False),
        ("JRF admit-card notice", False),
        ("Internship answer key", False),
        ("Internship corrigendum", False),
        ("Internship cancellation", False),
        ("Internship testimonials", False),
        ("Head of internship programme", False),
        ("Senior Technical Assistant", False),
    ],
)
def test_government_student_boundary_on_real_and_regression_titles(title, keep):
    assert gov.student_notice(title) is keep


def test_politeness_includes_retries_and_redirect_robots(monkeypatch):
    clock = [0.0]

    def tick(seconds):
        clock[0] += seconds

    monkeypatch.setattr(gov, "monotonic", lambda: clock[0])
    source, _ = adapter(monkeypatch, NicDiiAdapter)
    monkeypatch.setattr(gov, "sleep", tick)
    starts = []

    def respond(request):
        starts.append(clock[0])
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private\nCrawl-delay: 2")
        if len(starts) == 2:
            return httpx.Response(503, headers={"Retry-After": "0"})
        return httpx.Response(302, headers={"Location": "/private"})

    source._client = httpx.Client(transport=httpx.MockTransport(respond))
    assert source.fetch() == []
    assert source.health() == "broken"
    assert len(starts) == 3
    assert all(b - a >= 2 for a, b in zip(starts, starts[1:]))
