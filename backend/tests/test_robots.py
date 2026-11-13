import httpx
import pytest

from crawlers.robots import RobotsCache


@pytest.mark.parametrize(
    "status,body,allowed",
    [
        (200, "User-agent: *\nAllow: /", True),
        (200, "User-agent: AspirovaBot\nDisallow: /notices", False),
        (200, "User-agent: *\nDisallow: /", False),
        (200, "", True),
        (403, "Forbidden", True),
        (404, "Not Found", True),
        (503, "Unavailable", False),
        (500, "Error", False),
        (200, "<html>CAPTCHA</html>", False),
        (203, "User-agent: *\nAllow: /", False),
    ],
)
def test_runtime_policy_and_per_origin_cache(status, body, allowed):
    urls = []

    def request(url):
        urls.append(url)
        return httpx.Response(status, text=body)

    cache = RobotsCache(request)
    assert cache.allowed("https://example.gov.in/notices") is allowed
    assert cache.allowed("https://example.gov.in/notices?page=2") is allowed
    assert urls == ["https://example.gov.in/robots.txt"]


def test_network_unreachable_is_disallowed():
    def request(url):
        raise httpx.ConnectError("fixture offline")

    assert not RobotsCache(request).allowed("https://example.gov.in/notices")


def test_specific_agent_and_redirected_policy():
    def request(url):
        if url.endswith("robots.txt"):
            return httpx.Response(302, headers={"Location": "/policy.txt"})
        return httpx.Response(
            200,
            text="User-agent: *\nDisallow: /\n\nUser-agent: AspirovaBot\nAllow: /notices\nDisallow: /private",
        )

    cache = RobotsCache(request)
    assert cache.allowed("https://example.gov.in/notices")
    assert not cache.allowed("https://example.gov.in/private")
