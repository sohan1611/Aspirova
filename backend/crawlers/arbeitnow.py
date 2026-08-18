"""Arbeitnow aggregator adapter using its public job-board API."""

from datetime import UTC, datetime
from time import sleep
from typing import Any, Literal

import httpx

from core.adapters import NormalizedListing, RawListing
from crawlers.common import (
    RetriedResponse,
    USER_AGENT,
    build_http_timeout,
    build_listings,
    content_hash,
    extract_text,
    request_with_retries,
)
from crawlers.student_relevance import classify_student_role, is_student_relevant_role

_API_URL = "https://www.arbeitnow.com/api/job-board-api"
_PAGE_SIZE = 175
_MAX_PAGES = 12
_REQUEST_DELAY_SECONDS = 0.5
_MAX_RETRIES = 2

HealthStatus = Literal["ok", "degraded", "broken"]


class ArbeitnowAdapter:
    """SourceAdapter for Arbeitnow's broad jobs feed."""

    source_slug = "arbeitnow"
    requires_browser = False

    def __init__(self, timeout: float = 15.0) -> None:
        self._client = httpx.Client(
            timeout=build_http_timeout(timeout),
            headers={"User-Agent": USER_AGENT},
        )
        self._last_health: HealthStatus = "ok"
        self._raw_count = 0
        self._kept_count = 0
        self._page_count = 0
        self._request_count = 0
        self._retry_count = 0
        self._retry_reasons: list[str] = []
        self._hit_page_cap = False
        self._terminal_reason: str | None = None
        self._terminal_page: int | None = None

    def fetch(self) -> list[RawListing]:
        listings: list[RawListing] = []
        degraded = False
        self._raw_count = 0
        self._kept_count = 0
        self._page_count = 0
        self._request_count = 0
        self._retry_count = 0
        self._retry_reasons = []
        self._hit_page_cap = False
        self._terminal_reason = None
        self._terminal_page = None

        page = 1
        while page <= _MAX_PAGES:
            if self._page_count:
                sleep(_REQUEST_DELAY_SECONDS)

            result = self._get_page(page)
            self._request_count += result.attempts_made
            self._retry_count += max(result.attempts_made - 1, 0)
            self._retry_reasons.extend(result.retry_reasons)
            response = result.response
            if response is None:
                self._terminal_reason = result.terminal_reason or "request_error"
                self._terminal_page = page
                self._last_health = "degraded"
                return listings

            if response.status_code == 404:
                self._terminal_reason = "http_404"
                self._terminal_page = page
                self._last_health = "broken"
                return listings
            if response.status_code != 200:
                self._terminal_reason = result.terminal_reason or f"http_{response.status_code}"
                self._terminal_page = page
                self._last_health = "degraded"
                return listings

            try:
                payload = response.json()
            except ValueError:
                self._terminal_reason = (
                    "empty_response" if not response.text.strip() else "invalid_json"
                )
                self._terminal_page = page
                self._last_health = "degraded"
                return listings

            if not isinstance(payload, dict):
                self._terminal_reason = "non_object_payload"
                self._terminal_page = page
                self._last_health = "degraded"
                return listings

            jobs = payload.get("data")
            if not isinstance(jobs, list):
                self._terminal_reason = "missing_jobs"
                self._terminal_page = page
                self._last_health = "degraded"
                return listings
            if not jobs:
                self._terminal_reason = "empty_page"
                self._terminal_page = page
                break

            self._raw_count += len(jobs)
            filtered_jobs = [
                job
                for job in jobs
                if isinstance(job, dict) and is_student_relevant_role(job.get("title"))
            ]

            page_listings = build_listings(
                filtered_jobs,
                self._build_raw_listing,
                source_slug=self.source_slug,
            )
            if len(page_listings) != len(filtered_jobs):
                degraded = True
            listings.extend(page_listings)
            self._kept_count += len(page_listings)
            self._page_count += 1

            links = payload.get("links")
            next_link = links.get("next") if isinstance(links, dict) else None
            if not next_link:
                break
            page += 1

        if page > _MAX_PAGES:
            self._hit_page_cap = True
        self._last_health = "degraded" if degraded else "ok"
        return listings

    def parse(self, raw: RawListing) -> NormalizedListing:
        job = raw.raw_payload
        title = extract_text(_as_text(job.get("title")))
        location = extract_text(_as_text(job.get("location"))) or None
        tags = _text_list(job.get("tags"))
        job_types = _text_list(job.get("job_types"))

        return NormalizedListing(
            source_slug=self.source_slug,
            external_id=raw.external_id,
            source_url=raw.source_url,
            title=title,
            company_name=extract_text(_as_text(job.get("company_name"))) or "Arbeitnow",
            company_domain=None,
            location=location,
            is_remote=_as_bool(job.get("remote")),
            category=classify_student_role(title, job_types),
            description_raw=extract_text(_as_text(job.get("description"))),
            apply_url=raw.source_url,
            posted_at=_parse_datetime(job.get("created_at")),
            deadline=None,
            meta={
                "platform": "arbeitnow",
                "tags": tags,
                "job_types": job_types,
            },
            deadline_confidence="unknown",
        )

    def health(self) -> HealthStatus:
        return self._last_health

    def coverage(self) -> dict[str, Any]:
        note = "source declares no total"
        if self._hit_page_cap:
            note = f"{note}; fetch capped at {_MAX_PAGES} pages"
        if self._last_health in {"broken", "degraded"} and self._terminal_reason:
            note = f"{note}; fetch ended with {self._terminal_reason}"

        details: dict[str, Any] = self.filter_counts() | {
            "page_size": _PAGE_SIZE,
            "page_cap": _MAX_PAGES,
            "pages_fetched": self._page_count,
            "requests_made": self._request_count,
            "terminal_reason": self._terminal_reason,
            "terminal_page": self._terminal_page,
        }
        if self._retry_count:
            details["retry_attempts"] = self._retry_count
            details["retry_reasons"] = self._retry_reasons

        coverage: dict[str, Any] = {
            "mode": "unknown",
            "expected_total": None,
            "note": note,
            "details": details,
        }
        if self._last_health in {"broken", "degraded"} and self._terminal_reason:
            coverage["status"] = "partial"

        return coverage

    def filter_counts(self) -> dict[str, int]:
        return {
            "raw_count": self._raw_count,
            "student_relevant_count": self._kept_count,
            "filtered_out": max(self._raw_count - self._kept_count, 0),
        }

    def _build_raw_listing(self, job: dict[str, Any]) -> RawListing:
        source_url = _source_url(job)
        if not source_url:
            raise KeyError("url")
        return RawListing(
            source_slug=self.source_slug,
            external_id=str(job.get("slug") or job.get("id") or source_url),
            source_url=source_url,
            content_hash=content_hash(job),
            raw_payload=job,
        )

    def _get_page(self, page: int) -> RetriedResponse:
        return request_with_retries(
            lambda: self._client.get(
                _API_URL,
                params={"page": page, "per_page": _PAGE_SIZE},
            ),
            max_retries=_MAX_RETRIES,
            sleeper=sleep,
        )


def _source_url(job: dict[str, Any]) -> str:
    return _as_text(job.get("url") or job.get("apply_url") or job.get("job_url"))


def _text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [text for text in (_as_text(item) for item in value) if text]


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "remote"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
    return None


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, (int, float)):
        timestamp = float(value) / 1000 if value > 10_000_000_000 else float(value)
        return datetime.fromtimestamp(timestamp, tz=UTC)

    text = _as_text(value)
    if not text:
        return None
    if text.isdigit():
        return _parse_datetime(int(text))
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        return str(value).strip()
    except (TypeError, ValueError):
        return ""
