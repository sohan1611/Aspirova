"""Per-crawl robots cache. RFC 9309 unavailable/unreachable rules fail safely."""

from collections.abc import Callable
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from crawlers.common import USER_AGENT


class RobotsCache:
    def __init__(self, request: Callable[[str], httpx.Response]) -> None:
        self.request = request
        self._hosts: dict[str, RobotFileParser | bool] = {}

    def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._hosts:
            self._hosts[origin] = self._load(origin)
        policy = self._hosts[origin]
        return policy if isinstance(policy, bool) else policy.can_fetch(USER_AGENT, url)

    def delay(self, url: str) -> float:
        parts = urlsplit(url)
        policy = self._hosts.get(f"{parts.scheme}://{parts.netloc}")
        if isinstance(policy, RobotFileParser):
            return max(float(policy.crawl_delay(USER_AGENT) or 1), 1.0)
        return 1.0

    def _load(self, origin: str) -> RobotFileParser | bool:
        url = origin + "/robots.txt"
        try:
            # RFC 9309 permits robots redirects, including across authorities.
            for _ in range(6):
                response = self.request(url)
                if response.status_code in {301, 302, 303, 307, 308}:
                    target = urljoin(url, response.headers.get("Location", ""))
                    if target == url or urlsplit(target).scheme not in {"http", "https"}:
                        return False
                    url = target
                    continue
                if 400 <= response.status_code < 500:
                    return True
                if response.status_code != 200:
                    return False
                # A 200 challenge/error document is not an empty robots policy.
                if "<html" in response.text.lower() or "<!doctype" in response.text.lower():
                    return False
                policy = RobotFileParser()
                policy.parse(response.text.splitlines())
                return policy
        except (httpx.RequestError, ValueError):
            return False
        return False
