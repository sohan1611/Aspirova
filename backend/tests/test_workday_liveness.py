"""CXS liveness branches using recorded public JSON and HTTP status mutations."""

import json
from pathlib import Path

import httpx
import pytest

from crawlers.workday import cxs_endpoints
from pipeline import liveness

FIXTURES = Path(__file__).parent / "fixtures"
BASE = "https://nvidia.wd5.myworkdayjobs.com"
SITE = "NVIDIAExternalCareerSite"


@pytest.fixture
def detail():
    return json.loads((FIXTURES / "workday_detail_sample.json").read_text(encoding="utf-8-sig"))


@pytest.mark.parametrize("locale", ["", "en-US/", "fr_FR/"])
def test_derive_cxs_urls_from_apply_url(detail, locale):
    path = detail["jobPostingInfo"]["externalUrl"].split(f"/{SITE}", 1)[1]
    apply_url = f"{BASE}/{locale}{SITE}{path}?source=github#apply"
    assert cxs_endpoints(apply_url) == (
        f"{BASE}/wday/cxs/nvidia/{SITE}/jobs",
        f"{BASE}/wday/cxs/nvidia/{SITE}{path}",
    )


@pytest.mark.parametrize(
    "detail_status,control_status,expected",
    [
        (200, None, "alive"),
        (404, None, "closed"),
        (410, None, "closed"),
        (403, 200, "closed"),
        (403, 403, "inconclusive"),
        (403, 404, "inconclusive"),
        (403, 503, "inconclusive"),
        (403, "timeout", "inconclusive"),
        ("timeout", None, "inconclusive"),
        (302, None, "inconclusive"),
        (429, None, "inconclusive"),
        (500, None, "inconclusive"),
    ],
)
def test_workday_liveness_uses_detail_status_and_control(
    detail, monkeypatch, detail_status, control_status, expected
):
    requests = []
    monkeypatch.setattr(liveness, "sleep", lambda _delay: None)

    def respond(request):
        requests.append(request)
        # A generic page GET would return an alive SPA and fail the closed cases.
        assert "/wday/cxs/" in request.url.path
        status = control_status if request.method == "POST" else detail_status
        if status == "timeout":
            raise httpx.ReadTimeout("fixture timeout", request=request)
        return httpx.Response(status, json=detail, headers={"Retry-After": "0"})

    with httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=True) as client:
        status = liveness.fetch_url_liveness_status(detail["jobPostingInfo"]["externalUrl"], client)
    assert status == expected
    assert any(request.method == "POST" for request in requests) is (detail_status == 403)
    assert all(request.headers["User-Agent"] == liveness.USER_AGENT for request in requests)


@pytest.mark.parametrize("control_status,expected", [(200, "closed"), (403, "inconclusive")])
def test_control_cache_is_shared_between_workers_and_batches_but_resets_per_run(
    detail, monkeypatch, control_status, expected
):
    requests = []
    real_client = httpx.Client
    original_url = detail["jobPostingInfo"]["externalUrl"]
    candidates = [
        liveness.LivenessCandidate(index, original_url + f"?job={index}") for index in range(4)
    ]

    def respond(request):
        requests.append(request)
        return httpx.Response(control_status if request.method == "POST" else 403, json=detail)

    monkeypatch.setattr(liveness, "sleep", lambda _delay: None)
    monkeypatch.setattr(liveness, "_select_candidates", lambda _session, *, limit: candidates)
    monkeypatch.setattr(
        liveness.httpx,
        "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    for run in range(2):
        result = liveness.check_listing_liveness(
            object(), batch_size=2, concurrency=2, max_seconds=120
        )
        assert result.scanned == 4
        assert result.closed == (4 if expected == "closed" else 0)
        assert result.inconclusive == (4 if expected == "inconclusive" else 0)
        assert sum(request.method == "POST" for request in requests) == run + 1


def test_control_cache_is_scoped_to_site_and_tenant(detail, monkeypatch):
    posts = []
    checker = liveness.WorkdayLivenessChecker()
    monkeypatch.setattr(liveness, "sleep", lambda _delay: None)

    def respond(request):
        if request.method == "POST":
            posts.append(str(request.url))
            return httpx.Response(200, json={"total": 0, "jobPostings": []})
        return httpx.Response(403, json=detail)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        for url in [
            f"{BASE}/{SITE}/job/China/One",
            f"{BASE}/en-US/{SITE}/job/China/Two",
            f"{BASE}/OtherSite/job/China/Three",
            "https://acme.wd1.myworkdayjobs.com/Careers/job/India/Four",
        ]:
            assert (
                liveness.fetch_url_liveness_status(url, client, workday_checker=checker) == "closed"
            )
    assert len(posts) == 3


@pytest.mark.parametrize(
    "url",
    [
        f"{BASE}/",
        f"{BASE}/en-US/",
        f"{BASE}/{SITE}/careers",
        "https://[broken",
    ],
)
def test_invalid_workday_paths_are_inconclusive_without_html_fetch(url, monkeypatch):
    def respond(_request):
        raise AssertionError("invalid Workday URL must not fall back to the SPA")

    monkeypatch.setattr(liveness, "sleep", lambda _delay: None)
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        assert liveness.fetch_url_liveness_status(url, client) == "inconclusive"
