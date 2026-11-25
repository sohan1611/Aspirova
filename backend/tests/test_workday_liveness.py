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


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    from pipeline import liveness

    original = liveness.inspect_destination
    monkeypatch.setattr(
        liveness,
        "inspect_destination",
        lambda *args, **kwargs: original(*args, resolve=lambda *_: True, **kwargs),
    )


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
        (403, 200, "inconclusive"),
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
    assert not any(request.method == "POST" for request in requests)
    assert all(request.headers["User-Agent"] == liveness.USER_AGENT for request in requests)


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
