"""Jobicy aggregator adapter using its public remote-jobs API."""

from datetime import UTC, datetime
from time import sleep
from typing import Any, Literal

import httpx

from core.adapters import NormalizedListing, RawListing
from crawlers.common import (
    USER_AGENT,
    build_http_timeout,
    build_listings,
    content_hash,
    extract_text,
    request_with_retries,
)
from crawlers.student_relevance import classify_student_role, is_student_relevant_role

_API_URL = "https://jobicy.com/api/v2/remote-jobs"
_REQUEST_COUNT = 100
_MAX_RETRIES = 2

HealthStatus = Literal["ok", "degraded", "broken"]


class JobicyAdapter:
    """SourceAdapter for Jobicy's remote job feed."""

    source_slug = "jobicy"
    requires_browser = False

    def __init__(self, timeout: float = 15.0) -> None:
        self._client = httpx.Client(
            timeout=build_http_timeout(timeout),
            headers={"User-Agent": USER_AGENT},
        )
        self._last_health: HealthStatus = "ok"
        self._expected_total: int | None = None
        self._raw_count = 0
        self._kept_count = 0
        self._request_count = 0
        self._retry_count = 0
        self._retry_reasons: list[str] = []
        self._terminal_reason: str | None = None

    def fetch(self) -> list[RawListing]:
        self._expected_total = None
        self._raw_count = 0
        self._kept_count = 0
        self._request_count = 0
        self._retry_count = 0
        self._retry_reasons = []
        self._terminal_reason = None

        result = request_with_retries(
            lambda: self._client.get(_API_URL, params={"count": _REQUEST_COUNT}),
            max_retries=_MAX_RETRIES,
            sleeper=sleep,
        )
        self._request_count = result.attempts_made
        self._retry_count = max(result.attempts_made - 1, 0)
        self._retry_reasons = list(result.retry_reasons)
        response = result.response
        if response is None:
            self._terminal_reason = result.terminal_reason or "request_error"
            self._last_health = "degraded"
            return []

        if response.status_code == 404:
            self._terminal_reason = "http_404"
            self._last_health = "broken"
            return []
        if response.status_code != 200:
            self._terminal_reason = result.terminal_reason or f"http_{response.status_code}"
            self._last_health = "degraded"
            return []

        try:
            payload = response.json()
        except ValueError:
            self._terminal_reason = (
                "empty_response" if not response.text.strip() else "invalid_json"
            )
            self._last_health = "degraded"
            return []

        if not isinstance(payload, dict):
            self._terminal_reason = "non_object_payload"
            self._last_health = "degraded"
            return []

        self._expected_total = _declared_total(payload)
        jobs = payload.get("jobs")
        if not isinstance(jobs, list):
            self._terminal_reason = "missing_jobs"
            self._last_health = "degraded"
            return []

        self._raw_count = len(jobs)
        filtered_jobs = [
            job
            for job in jobs
            if isinstance(job, dict)
            and is_student_relevant_role(_job_title(job), job.get("jobLevel"))
        ]
        listings = build_listings(
            filtered_jobs, self._build_raw_listing, source_slug=self.source_slug
        )
        self._kept_count = len(listings)
        self._last_health = "ok" if len(listings) == len(filtered_jobs) else "degraded"
        return listings

    def parse(self, raw: RawListing) -> NormalizedListing:
        job = raw.raw_payload
        title = extract_text(_job_title(job))
        job_level = _as_text(job.get("jobLevel")) or None
        tags = _text_list(job.get("tags"))
        job_type = _text_list(job.get("jobType"))
        industry = _text_list(job.get("jobIndustry"))

        return NormalizedListing(
            source_slug=self.source_slug,
            external_id=raw.external_id,
            source_url=raw.source_url,
            title=title,
            company_name=extract_text(_as_text(job.get("companyName"))) or "Jobicy",
            company_domain=_as_text(job.get("companyWebsite")) or None,
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
        note = None if self._expected_total is not None else "source declares no total"
        if self._last_health in {"broken", "degraded"} and self._terminal_reason:
            terminal_note = f"fetch ended with {self._terminal_reason}"
            if self._retry_reasons:
                terminal_note = f"{terminal_note} after {self._retry_reasons[-1]}"
            note = f"{note}; {terminal_note}" if note else terminal_note

        details: dict[str, Any] = self.filter_counts() | {
            "requested_count": _REQUEST_COUNT,
            "requests_made": self._request_count,
            "terminal_reason": self._terminal_reason,
        }
        if self._retry_count:
            details["retry_attempts"] = self._retry_count
            details["retry_reasons"] = self._retry_reasons

        coverage: dict[str, Any] = {
            "mode": "declared_total" if self._expected_total is not None else "unknown",
            "expected_total": self._expected_total,
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
            external_id=str(job.get("id") or job.get("jobId") or job.get("jobSlug") or source_url),
            source_url=source_url,
            content_hash=content_hash(job),
            raw_payload=job,
        )


def _source_url(job: dict[str, Any]) -> str:
    return _as_text(job.get("url") or job.get("jobUrl") or job.get("applyUrl"))


def _job_title(job: dict[str, Any]) -> str:
    return _as_text(job.get("jobTitle") or job.get("title"))


def _declared_total(payload: dict[str, Any]) -> int | None:
    value = payload.get("jobCount")
    try:
        return max(int(value), 0) if value is not None else None
    except (TypeError, ValueError):
        return None


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
