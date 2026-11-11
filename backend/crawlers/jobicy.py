"""Jobicy aggregator adapter using its public jobs API.

Jobicy relaunched its API on 2026-10-19. ``/api/jobs`` pages the whole 7-day
publication window through an opaque cursor (pass ``nextCursor`` back as
``cursor`` until it is null), and ``jobCount`` is the size of one page, not a
total. One page holds only the newest 100 jobs, which by November 2026 was
about half a day of postings, so a daily crawl that read page one alone never
saw the other half and kept 0 student roles on most days.
"""

from datetime import UTC, datetime
from time import sleep
from typing import Any, Literal

import httpx

from core.adapters import NormalizedListing, RawListing
from core.domains import http_url
from crawlers.common import (
    USER_AGENT,
    build_http_timeout,
    build_listings,
    content_hash,
    extract_text,
    request_with_retries,
)
from crawlers.student_relevance import classify_student_role, is_student_relevant_role
from crawlers.watchdog import beat as watchdog_beat

_API_URL = "https://jobicy.com/api/jobs"
_PAGE_SIZE = 100
# The 7-day window held 15 pages (1,438 jobs) on 2026-11-11. The cap only stops
# a cursor that never ends; reaching it marks the crawl partial.
_MAX_PAGES = 40
# Jobicy asks integrations to poll at most once an hour. One daily traversal is
# one poll; this pause only spaces out its pages.
_PAGE_DELAY_SECONDS = 1.0
_MAX_RETRIES = 2

HealthStatus = Literal["ok", "degraded", "broken"]


class JobicyAdapter:
    """SourceAdapter for Jobicy's 7-day remote job window."""

    source_slug = "jobicy"
    requires_browser = False

    def __init__(self, timeout: float = 15.0) -> None:
        self._client = httpx.Client(
            timeout=build_http_timeout(timeout),
            headers={"User-Agent": USER_AGENT},
        )
        self._last_health: HealthStatus = "ok"
        self._raw_count = 0
        self._kept_count = 0
        self._malformed_count = 0
        self._request_count = 0
        self._page_count = 0
        self._retry_count = 0
        self._retry_reasons: list[str] = []
        self._hit_page_cap = False
        self._window_complete = False
        self._terminal_reason: str | None = None

    def fetch(self) -> list[RawListing]:
        self._last_health = "ok"
        self._raw_count = 0
        self._kept_count = 0
        self._malformed_count = 0
        self._request_count = 0
        self._page_count = 0
        self._retry_count = 0
        self._retry_reasons = []
        self._hit_page_cap = False
        self._window_complete = False
        self._terminal_reason = None

        window_jobs: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        cursor: str | None = None
        while True:
            if self._page_count >= _MAX_PAGES:
                self._hit_page_cap = True
                self._terminal_reason = "page_cap"
                self._last_health = "degraded"
                break
            if self._page_count:
                sleep(_PAGE_DELAY_SECONDS)

            params: dict[str, Any] = {"count": _PAGE_SIZE}
            if cursor:
                params["cursor"] = cursor
            self._page_count += 1
            payload = self._fetch_page(params)
            if payload is None:
                # Pages already read stay valid: this is a rolling window, so a
                # short read only lowers coverage and never retires anything.
                break

            for job in payload["jobs"]:
                if not isinstance(job, dict):
                    continue
                # Jobicy's docs ask integrations to dedupe by id across pages.
                job_id = _external_id(job)
                if job_id and job_id in seen_ids:
                    continue
                if job_id:
                    seen_ids.add(job_id)
                window_jobs.append(job)

            next_cursor = payload.get("nextCursor")
            if isinstance(next_cursor, str) and next_cursor:
                cursor = next_cursor
                continue
            if payload.get("hasMore") is True:
                self._terminal_reason = "missing_cursor"
                self._last_health = "degraded"
                break
            self._window_complete = True
            break

        self._raw_count = len(window_jobs)
        filtered_jobs = [job for job in window_jobs if _is_student_role(job)]
        listings = build_listings(
            filtered_jobs, self._build_raw_listing, source_slug=self.source_slug
        )
        self._kept_count = len(listings)
        self._malformed_count = len(filtered_jobs) - len(listings)
        if self._malformed_count and self._last_health == "ok":
            self._last_health = "degraded"
        return listings

    def parse(self, raw: RawListing) -> NormalizedListing:
        job = raw.raw_payload
        title = extract_text(_job_title(job))
        company_name = extract_text(_as_text(job.get("companyName")))
        job_level = _as_text(job.get("jobLevel")) or None
        tags = _text_list(job.get("tags"))
        job_type = _text_list(job.get("jobType"))
        industry = _text_list(job.get("jobIndustry"))

        return NormalizedListing(
            source_slug=self.source_slug,
            external_id=raw.external_id,
            source_url=raw.source_url,
            title=title,
            company_name=company_name or "Jobicy",
            company_domain=_as_text(job.get("companyWebsite")) or None,
            company_logo_url=http_url(job.get("companyLogo")) if company_name else None,
            location=_as_text(job.get("jobGeo")) or None,
            is_remote=True,
            category=classify_student_role(title, job_level),
            description_raw=extract_text(
                _as_text(job.get("jobDescription") or job.get("jobExcerpt"))
            ),
            apply_url=raw.source_url,
            posted_at=_parse_datetime(job.get("pubDate")),
            deadline=None,
            meta={
                "platform": "jobicy",
                "job_level": job_level,
                "job_type": job_type,
                "industry": industry,
                "tags": tags,
                "geo": job.get("jobGeo"),
            },
            deadline_confidence="unknown",
        )

    def health(self) -> HealthStatus:
        return self._last_health

    def coverage(self) -> dict[str, Any]:
        complete = self._window_complete and self._last_health == "ok"
        note = "bounded by design to Jobicy's 7-day jobs window"
        if not complete:
            if self._terminal_reason:
                terminal_note = f"fetch ended with {self._terminal_reason}"
                if self._retry_reasons:
                    terminal_note = f"{terminal_note} after {self._retry_reasons[-1]}"
                note = f"{note}; {terminal_note}"
            if self._malformed_count:
                note = f"{note}; skipped {self._malformed_count} malformed listings"

        details: dict[str, Any] = self.filter_counts() | {
            "page_size_requested": _PAGE_SIZE,
            "page_cap": _MAX_PAGES,
            "pages_requested": self._page_count,
            "requests_made": self._request_count,
            "bounded_by_design": True,
            "hit_page_cap": self._hit_page_cap,
            "terminal_reason": self._terminal_reason,
            "window_raw_fetched": self._raw_count,
            "window_raw_expected": self._raw_count if self._window_complete else None,
        }
        if self._retry_count:
            details["retry_attempts"] = self._retry_count
            details["retry_reasons"] = self._retry_reasons

        return {
            "mode": "bounded_window",
            "expected_total": None,
            "status": "complete" if complete else "partial",
            "note": note,
            "details": details,
        }

    def filter_counts(self) -> dict[str, int]:
        return {
            "raw_count": self._raw_count,
            "student_relevant_count": self._kept_count,
            "filtered_out": max(self._raw_count - self._kept_count, 0),
        }

    def _fetch_page(self, params: dict[str, Any]) -> dict[str, Any] | None:
        """Fetch one page; on failure record why and return None."""
        result = request_with_retries(
            lambda: self._client.get(_API_URL, params=params),
            max_retries=_MAX_RETRIES,
            sleeper=sleep,
        )
        self._request_count += result.attempts_made
        self._retry_count += max(result.attempts_made - 1, 0)
        self._retry_reasons.extend(result.retry_reasons)
        response = result.response
        if response is None:
            return self._stop(result.terminal_reason or "request_error")
        if response.status_code == 404:
            return self._stop("http_404", health="broken")
        if response.status_code != 200:
            return self._stop(result.terminal_reason or f"http_{response.status_code}")

        # The runner beats only around the whole fetch() call. Beat on each
        # page that came back so a long traversal never looks hung, while
        # pacing sleeps and failed requests still do not count as progress.
        watchdog_beat(f"jobicy:page-{self._page_count}")

        try:
            payload = response.json()
        except ValueError:
            return self._stop("empty_response" if not response.text.strip() else "invalid_json")
        if not isinstance(payload, dict):
            return self._stop("non_object_payload")
        if not isinstance(payload.get("jobs"), list):
            return self._stop("missing_jobs")
        return payload

    def _stop(self, reason: str, *, health: HealthStatus = "degraded") -> None:
        self._terminal_reason = reason
        self._last_health = health
        return None

    def _build_raw_listing(self, job: dict[str, Any]) -> RawListing:
        source_url = _source_url(job)
        if not source_url:
            raise KeyError("url")
        return RawListing(
            source_slug=self.source_slug,
            external_id=_external_id(job),
            source_url=source_url,
            content_hash=content_hash(job),
            raw_payload=job,
        )


def _is_student_role(job: dict[str, Any]) -> bool:
    """Admit on a student title before consulting Jobicy's level tag.

    Jobicy's level tag is unreliable. On 2026-11-11 "Growth Marketing Intern"
    and "Security Intern, Threat Operations - Winter 2027" were tagged Senior,
    and "Customer Success Junior" was tagged Director. A student word in a title
    that has no senior word wins over the tag. Without a student word the tag
    still decides: "Entry-Level, Junior" admits the role and a senior tag
    rejects it.
    """
    title = _job_title(job)
    return is_student_relevant_role(title) or is_student_relevant_role(title, job.get("jobLevel"))


def _external_id(job: dict[str, Any]) -> str:
    return _as_text(job.get("id") or job.get("jobId") or job.get("jobSlug") or _source_url(job))


def _source_url(job: dict[str, Any]) -> str:
    return _as_text(job.get("url") or job.get("jobUrl") or job.get("applyUrl"))


def _job_title(job: dict[str, Any]) -> str:
    return _as_text(job.get("jobTitle") or job.get("title"))


def _text_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [text for text in (_as_text(item) for item in value) if text]
    text = _as_text(value)
    return [text] if text else []


def _parse_datetime(value: Any) -> datetime | None:
    text = _as_text(value)
    if not text:
        return None
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
