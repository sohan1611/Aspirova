"""Student roles from the public Workday CXS career-site API.

Search limits are normal partial coverage. Transport and parse failures degrade
health. Individual postings are retired through the Workday liveness checker.
"""

import logging
import re
import threading
from datetime import UTC, datetime, timedelta
from time import monotonic, sleep
from typing import Any, Literal
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from core.adapters import NormalizedListing, RawListing
from crawlers.common import (
    USER_AGENT,
    build_http_timeout,
    content_hash,
    extract_text,
    request_with_retries,
)
from crawlers.student_relevance import classify_student_role, is_student_relevant_role
from pipeline.location_country import derive_country

SEARCH_TERMS = ("intern", "graduate", "co-op", "apprentice", "entry level")
PAGE_SIZE = 20
MAX_PAGES_PER_TERM = 3
REQUEST_BUDGET = 45
FETCH_MAX_SECONDS = 25.0
REQUEST_DELAY_SECONDS = 0.5
_HOST_LOCKS: dict[str, Any] = {}
_HOST_LOCKS_GUARD = threading.Lock()
logger = logging.getLogger(__name__)
HealthStatus = Literal["ok", "degraded", "broken"]


def tenant_lock(base_url: str) -> Any:
    with _HOST_LOCKS_GUARD:
        return _HOST_LOCKS.setdefault(base_url, threading.Lock())


def cxs_endpoints(apply_url: str) -> tuple[str, str] | None:
    """Return search/detail URLs for a Workday employer link, ignoring locale."""
    try:
        parts = urlsplit(apply_url)
        host = parts.hostname or ""
        tenant = re.fullmatch(r"([a-z0-9-]+)\.wd\d+\.myworkdayjobs\.com", host)
        path = re.fullmatch(
            r"/(?:[a-zA-Z]{2}[-_][a-zA-Z]{2}/)?([a-zA-Z0-9_-]+)(/job/.+)", parts.path
        )
        if (
            parts.scheme not in {"http", "https"}
            or parts.username
            or parts.password
            or not tenant
            or not path
        ):
            return None
        api = f"https://{host}/wday/cxs/{tenant[1]}/{path[1]}"
        return f"{api}/jobs", f"{api}{path[2]}"
    except ValueError:
        return None


class _RequestLimit(Exception):
    """Stop HTTP work at a normal crawl limit without degrading source health."""


def parse_board_token(token: str) -> tuple[str, str, str]:
    parts = token.split("|")
    if (
        len(parts) != 3
        or not re.fullmatch(r"[a-zA-Z0-9-]+", parts[0])
        or not re.fullmatch(r"wd\d+", parts[1], re.IGNORECASE)
        or not re.fullmatch(r"[a-zA-Z0-9_-]+", parts[2])
    ):
        raise ValueError("Workday board token must be <tenant>|wd<N>|<site>")
    return parts[0].lower(), parts[1].lower(), parts[2]


def parse_posted_at(
    start_date: Any, posted_on: Any, *, now: datetime | None = None
) -> datetime | None:
    if isinstance(start_date, str):
        try:
            parsed = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
            return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed
        except ValueError:
            pass
    current = now or datetime.now(UTC)
    text = str(posted_on or "")
    match = re.search(r"Posted\s+(\d+)\+?\s+Days?\s+Ago", text, re.IGNORECASE)
    if match:
        return current - timedelta(days=int(match[1]))
    if re.fullmatch(r"Posted\s+(Today|Yesterday)", text, re.IGNORECASE):
        return current - timedelta(days=1 if "yesterday" in text.lower() else 0)
    return None


class WorkdayAdapter:
    source_slug = "workday"
    requires_browser = False

    def __init__(self, board_token: str, company_name: str, timeout: float = 15.0) -> None:
        self.board_token = board_token
        self.company_name = company_name
        self.tenant, cluster, self.site = parse_board_token(board_token)
        self.base_url = f"https://{self.tenant}.{cluster}.myworkdayjobs.com"
        self.api_url = f"{self.base_url}/wday/cxs/{self.tenant}/{self.site}"
        self._client = httpx.Client(
            timeout=build_http_timeout(timeout), headers={"User-Agent": USER_AGENT}
        )
        self._host_lock = tenant_lock(self.base_url)
        self._timeout = timeout
        self._last_health: HealthStatus = "ok"
        self._requests = 0
        self._failures: list[str] = []
        self._capped_terms: list[str] = []
        self._totals: dict[str, int] = {}
        self._finished = False
        self._early_terms: list[str] = []
        self._limits: set[str] = set()
        self._deadline: float | None = None
        self._last_request_status: int | None = None
        self.last_board_state = "error"
        self.last_http_status: int | None = None

    def _reset(self) -> None:
        self._last_health = "ok"
        self._requests = 0
        self._failures = []
        self._capped_terms = []
        self._totals = {}
        self._finished = False
        self._early_terms = []
        self._limits = set()
        self._deadline = None
        self._last_request_status = None
        self.last_board_state = "error"
        self.last_http_status = None

    def _fail(self, reason: str) -> None:
        self._last_health = "degraded"
        self._failures.append(reason)
        logger.warning("Workday %s: %s", self.board_token, reason)

    def _budget_available(self) -> bool:
        if self._requests >= REQUEST_BUDGET:
            self._limits.add("request_budget")
        if self._deadline is not None and monotonic() + REQUEST_DELAY_SECONDS >= self._deadline:
            self._limits.add("time_budget")
        return not self._limits

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response | None:
        self._last_request_status = None
        if not self._budget_available():
            return None

        def once() -> httpx.Response:
            if not self._budget_available():
                raise _RequestLimit
            sleep(REQUEST_DELAY_SECONDS)
            self._requests += 1
            timeout = self._timeout
            if self._deadline is not None:
                timeout = min(timeout, max(self._deadline - monotonic(), 0.001))
            try:
                response = self._client.request(method, url, timeout=timeout, **kwargs)
            except httpx.TimeoutException:
                if self._deadline is not None and monotonic() >= self._deadline:
                    self._limits.add("time_budget")
                    raise _RequestLimit from None
                self._fail("request_error")
                raise
            except httpx.RequestError:
                self._fail("request_error")
                raise
            self._last_request_status = response.status_code
            return response

        # Serialize sites on the same tenant, including Retry-After backoff.
        try:
            with self._host_lock:
                result = request_with_retries(
                    once, max_retries=min(2, REQUEST_BUDGET - self._requests - 1), sleeper=sleep
                )
        except _RequestLimit:
            if self._last_request_status is not None and self._last_request_status != 200:
                self._fail(f"http_{self._last_request_status}")
            return None
        response = result.response
        if response is None or response.status_code != 200:
            self._fail(
                result.terminal_reason
                or (f"http_{response.status_code}" if response is not None else "request_error")
            )
        return response

    def _json(self, method: str, url: str, **kwargs: Any) -> dict[str, Any] | None:
        response = self._request(method, url, **kwargs)
        if response is None or response.status_code != 200:
            return None
        try:
            value = response.json()
        except ValueError:
            self._fail("invalid_json")
            return None
        if not isinstance(value, dict):
            self._fail("non_object_payload")
            return None
        return value

    def _robots_allowed(self) -> bool:
        response = self._request("GET", f"{self.base_url}/robots.txt")
        if response is not None and response.status_code == 404:
            # No robots file is a valid policy; unlike a missing career site.
            self._failures.pop()
            self._last_health = "ok" if not self._failures else "degraded"
            return True
        if response is None or response.status_code != 200:
            return False
        robots = RobotFileParser()
        robots.parse(response.text.splitlines())
        if not robots.can_fetch(USER_AGENT, f"{self.base_url}/{self.site}/"):
            self._fail("robots_disallowed")
            return False
        return True

    def _search(self, term: str, offset: int = 0) -> tuple[int, list[dict[str, Any]]] | None:
        payload = self._json(
            "POST",
            f"{self.api_url}/jobs",
            json={
                "appliedFacets": {},
                "limit": PAGE_SIZE,
                "offset": offset,
                "searchText": term,
            },
        )
        self.last_http_status = self._last_request_status
        self.last_board_state = "not_found" if self.last_http_status in {404, 410} else "error"
        if payload is None:
            return None
        jobs = payload.get("jobPostings")
        total = payload.get("total")
        # Workday reports the real total only on the first page; later pages
        # answer total=0 (verified live on NVIDIA 2026-11-08), so only the
        # first page's total is checked against its postings.
        if (
            not isinstance(total, int)
            or isinstance(total, bool)
            or total < 0
            or not isinstance(jobs, list)
            or any(not isinstance(job, dict) for job in jobs)
            or (offset == 0 and total < len(jobs))
        ):
            self._fail("invalid_search_shape")
            return None
        self.last_board_state = "ok"
        return total, jobs

    def student_count(self) -> int | None:
        """Verify the public board with one intern search, without detail work."""
        self._reset()
        page = self._search("intern")
        return page[0] if page is not None and self._last_health == "ok" else None

    def fetch(self) -> list[RawListing]:
        self._reset()
        self._deadline = monotonic() + FETCH_MAX_SECONDS
        if not self._robots_allowed():
            return []
        postings: dict[str, dict[str, Any]] = {}
        for term in SEARCH_TERMS:
            for page_number in range(MAX_PAGES_PER_TERM):
                if not self._budget_available():
                    break
                offset = page_number * PAGE_SIZE
                page = self._search(term, offset)
                if page is None:
                    # Stop a vanished tenant or rate-limited board immediately.
                    return self._details(postings)
                page_total, jobs = page
                if offset == 0:
                    self._totals[term] = page_total
                total = self._totals.get(term, page_total)
                relevant = 0
                for job in jobs:
                    path = job.get("externalPath")
                    if (
                        not isinstance(path, str)
                        or not path.startswith("/job/")
                        or urlsplit(path).query
                        or urlsplit(path).fragment
                    ):
                        self._fail("invalid_external_path")
                        continue
                    if not isinstance(job.get("title"), str) or not job["title"].strip():
                        self._fail("invalid_search_title")
                        continue
                    if is_student_relevant_role(job["title"]):
                        relevant += 1
                        postings.setdefault(path, job)
                if jobs and not relevant:
                    self._early_terms.append(term)
                    break
                if offset + len(jobs) >= total:
                    break
                if len(jobs) < PAGE_SIZE:
                    self._early_terms.append(term)
                    break
                if page_number == MAX_PAGES_PER_TERM - 1:
                    self._capped_terms.append(term)
            if not self._budget_available():
                break
        self._finished = len(self._totals) == len(SEARCH_TERMS)
        return self._details(postings)

    def _details(self, postings: dict[str, dict[str, Any]]) -> list[RawListing]:
        listings: list[RawListing] = []
        for path, posting in postings.items():
            payload = (
                self._json("GET", f"{self.api_url}{path}") if self._budget_available() else None
            )
            info = payload.get("jobPostingInfo") if payload is not None else None
            if payload is None and self._limits:
                bullet_fields = posting.get("bulletFields") or []
                info = {
                    "title": posting["title"],
                    "location": posting.get("locationsText"),
                    "postedOn": posting.get("postedOn"),
                    "jobDescription": "",
                    "jobReqId": (
                        bullet_fields[0]
                        if isinstance(bullet_fields, list) and bullet_fields
                        else None
                    ),
                    "detail_fallback": True,
                }
            elif payload is None:
                continue
            if (
                not isinstance(info, dict)
                or not isinstance(info.get("title"), str)
                or not info["title"].strip()
                or not isinstance(info.get("jobDescription"), str)
            ):
                self._fail("invalid_job_detail")
                continue
            if not is_student_relevant_role(info["title"]):
                continue
            url = info.get("externalUrl") or f"{self.base_url}/{self.site}{path}"
            # Store relative date text, not a moving timestamp, in the content hash.
            data = info | {
                "externalPath": path,
                "postedOn": info.get("postedOn") or posting.get("postedOn"),
            }
            listings.append(
                RawListing(
                    source_slug=self.source_slug,
                    external_id=str(info.get("jobReqId") or path),
                    source_url=url,
                    content_hash=content_hash(data),
                    raw_payload=data,
                )
            )
        return listings

    def parse(self, raw: RawListing) -> NormalizedListing:
        info = raw.raw_payload
        locations = [info.get("location"), *(info.get("additionalLocations") or [])]
        location = (
            "; ".join(
                dict.fromkeys(
                    value.strip() for value in locations if isinstance(value, str) and value.strip()
                )
            )
            or None
        )
        country_value = info.get("country")
        country_name = (
            country_value.get("descriptor") if isinstance(country_value, dict) else country_value
        )
        country = derive_country(country_name) if isinstance(country_name, str) else None
        title = info["title"]
        return NormalizedListing(
            source_slug=self.source_slug,
            external_id=raw.external_id,
            source_url=raw.source_url,
            title=title,
            company_name=self.company_name,
            location=location,
            country=country or derive_country(location),
            is_remote=bool(re.search(r"\bremote\b", location or "", re.IGNORECASE)),
            category=classify_student_role(title),
            description_raw=extract_text(info.get("jobDescription")),
            apply_url=info.get("externalUrl") or raw.source_url,
            posted_at=parse_posted_at(info.get("startDate"), info.get("postedOn")),
            deadline_confidence="unknown",
            meta={
                "time_type": info.get("timeType"),
                "job_req_id": info.get("jobReqId"),
                "posted_on": info.get("postedOn"),
                "detail_fallback": info.get("detail_fallback", False),
            },
        )

    def health(self) -> HealthStatus:
        return self._last_health

    def coverage(self) -> dict[str, Any]:
        return {
            "mode": "search",
            "expected_total": None,
            "status": (
                "complete"
                if self._finished
                and self._last_health == "ok"
                and not self._capped_terms
                and not self._early_terms
                and not self._limits
                else "partial"
            ),
            "note": "term totals overlap; complete means all bounded student searches finished",
            "details": {
                "requests_made": self._requests,
                "request_budget": REQUEST_BUDGET,
                "totals_by_term": self._totals,
                "capped_terms": self._capped_terms,
                "early_stopped_terms": self._early_terms,
                "limits": sorted(self._limits),
                "max_seconds": FETCH_MAX_SECONDS,
                "failures": self._failures,
            },
        }
