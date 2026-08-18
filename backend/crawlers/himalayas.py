"""Himalayas aggregator adapter using its public jobs API."""

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
from crawlers.watchdog import beat as watchdog_beat

_API_URL = "https://himalayas.app/jobs/api"
_PAGE_SIZE = 20
# Himalayas advertises about 102k jobs but returns only 20 per request, and its
# seniority filter did not narrow totals when probed. Crawl only the most-recent
# window so this source cannot consume an entire aggregator run.
_MAX_REQUESTS = 250
_REQUEST_DELAY_SECONDS = 3.0
_MAX_RETRIES = 3

HealthStatus = Literal["ok", "degraded", "broken"]


class HimalayasAdapter:
    """SourceAdapter for a bounded Himalayas jobs window."""

    source_slug = "himalayas"
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
        self._page_count = 0
        self._retry_count = 0
        self._retry_reasons: list[str] = []
        self._hit_request_cap = False
        self._terminal_reason: str | None = None
        self._terminal_offset: int | None = None

    def fetch(self) -> list[RawListing]:
        listings: list[RawListing] = []
        degraded = False
        offset = 0
        self._expected_total = None
        self._raw_count = 0
        self._kept_count = 0
        self._request_count = 0
        self._page_count = 0
        self._retry_count = 0
        self._retry_reasons = []
        self._hit_request_cap = False
        self._terminal_reason = None
        self._terminal_offset = None

        while self._page_count < _MAX_REQUESTS:
            if self._page_count:
                sleep(_REQUEST_DELAY_SECONDS)

            request_offset = offset
            self._page_count += 1
            result = request_with_retries(
                lambda: self._client.get(
                    _API_URL,
                    params={"limit": _PAGE_SIZE, "offset": request_offset},
                ),
                max_retries=_MAX_RETRIES,
                sleeper=sleep,
            )
            self._request_count += result.attempts_made
            self._retry_count += max(result.attempts_made - 1, 0)
            self._retry_reasons.extend(result.retry_reasons)
            response = result.response
            if response is None:
                self._terminal_reason = result.terminal_reason or "request_error"
                self._terminal_offset = request_offset
                self._last_health = "degraded"
                return listings

            if response.status_code == 404:
                self._terminal_reason = "http_404"
                self._terminal_offset = request_offset
                self._last_health = "broken"
                return listings
            if response.status_code != 200:
                self._terminal_reason = result.terminal_reason or f"http_{response.status_code}"
                self._terminal_offset = request_offset
                self._last_health = "degraded"
                return listings

            # The runner beats only around the whole fetch() call, so a
            # deliberately paced source looks frozen from outside: this window
            # is up to ~250 requests 3s apart (~13 min) and keeps only a few
            # dozen rows, so it runs far past the watchdog's 600s no-progress
            # threshold without ever reaching an ingest batch. That is what
            # killed crawl 32170763256 - "HUNG: hard exit after 722s without
            # progress; last activity was himalayas:fetch-start" - taking
            # devpost, remoteok, arbeitnow and jobicy with it, none of which
            # ever got to run.
            #
            # Beat only on a page that actually came back 200. Pacing sleeps,
            # backoff waits and failed requests deliberately do NOT beat, so a
            # source that stops fetching is still caught by the watchdog.
            watchdog_beat(f"himalayas:page-{self._page_count}")

            try:
                payload = response.json()
            except ValueError:
                self._terminal_reason = "invalid_json"
                self._terminal_offset = request_offset
                self._last_health = "degraded"
                return listings

            if not isinstance(payload, dict):
                self._terminal_reason = "non_object_payload"
                self._terminal_offset = request_offset
                self._last_health = "degraded"
                return listings

            declared_total = _declared_total(payload)
            if declared_total is not None:
                self._expected_total = declared_total

            jobs = _job_items(payload)
            if jobs is None:
                self._terminal_reason = "missing_jobs"
                self._terminal_offset = request_offset
                self._last_health = "degraded"
                return listings
            if not jobs:
                self._terminal_reason = "empty_page"
                self._terminal_offset = request_offset
                break

            self._raw_count += len(jobs)
            filtered_jobs = [
                job
                for job in jobs
                if isinstance(job, dict)
                # Himalayas labels ordinary assistant/customer-service roles
                # Entry-level, and its seniority filter parameter is inert.
                # For this source, title text is the only trusted admission signal.
                and is_student_relevant_role(_job_title(job))
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

            if len(jobs) < _PAGE_SIZE:
                self._terminal_reason = "short_page"
                self._terminal_offset = request_offset
                break
            offset += len(jobs)

        if self._page_count >= _MAX_REQUESTS and (
            self._expected_total is None or self._raw_count < self._expected_total
        ):
            self._hit_request_cap = True
            self._terminal_reason = self._terminal_reason or "request_cap"
            self._terminal_offset = self._terminal_offset or offset
        self._last_health = "degraded" if degraded else "ok"
        return listings

    def parse(self, raw: RawListing) -> NormalizedListing:
        job = raw.raw_payload
        title = extract_text(_job_title(job))
        seniority = _job_seniority(job) or None
        categories = _text_values(job.get("categories"))
        locations = _location_values(job)
        job_type = (
            _as_text(job.get("jobType") or job.get("employmentType") or job.get("type")) or None
        )
        source_url = _source_url(job) or raw.source_url
        apply_url = _apply_url(job) or source_url

        return NormalizedListing(
            source_slug=self.source_slug,
            external_id=raw.external_id,
            source_url=source_url,
            title=title,
            company_name=_company_name(job) or "Himalayas",
            company_domain=_company_domain(job),
            location=", ".join(locations) if locations else None,
            is_remote=_remote_value(job),
            category=classify_student_role(title, seniority),
            description_raw=extract_text(
                _as_text(job.get("description") or job.get("jobDescription"))
            ),
            apply_url=apply_url,
            posted_at=_parse_datetime(
                job.get("publishedDate")
                or job.get("pubDate")
                or job.get("postedAt")
                or job.get("createdAt")
                or job.get("created_at")
            ),
            deadline=None,
            meta={
                "platform": "himalayas",
                "seniority": seniority,
                "job_type": job_type,
                "categories": categories,
                "locations": locations,
            },
            deadline_confidence="unknown",
        )

    def health(self) -> HealthStatus:
        return self._last_health

    def coverage(self) -> dict[str, Any]:
        status = "complete" if self._last_health == "ok" else "partial"
        window_raw_expected = (
            self._raw_count
            if self._terminal_reason in {"empty_page", "short_page"}
            else _MAX_REQUESTS * _PAGE_SIZE
        )
        note = "bounded by design to the most recent Himalayas jobs window"
        if status == "partial" and self._terminal_reason:
            note = f"{note}; fetch ended with {self._terminal_reason}"

        details: dict[str, Any] = self.filter_counts() | {
            "catalogue_total": self._expected_total,
            "request_cap": _MAX_REQUESTS,
            "page_size_requested": _PAGE_SIZE,
            "requests_made": self._request_count,
            "pages_requested": self._page_count,
            "bounded_by_design": True,
            "hit_request_cap": self._hit_request_cap,
            "terminal_reason": self._terminal_reason,
            "terminal_offset": self._terminal_offset,
            "window_raw_fetched": self._raw_count,
            "window_raw_expected": window_raw_expected,
        }
        if self._retry_count:
            details["retry_attempts"] = self._retry_count
            details["retry_reasons"] = self._retry_reasons

        return {
            "mode": "bounded_window",
            "expected_total": None,
            "status": status,
            "note": note,
            "details": details,
        }

    def filter_counts(self) -> dict[str, int]:
        return {
            "raw_count": self._raw_count,
            "student_relevant_count": self._kept_count,
            "filtered_out": max(self._raw_count - self._kept_count, 0),
        }

    def _build_raw_listing(self, job: dict[str, Any]) -> RawListing:
        source_url = _source_url(job) or _apply_url(job)
        if not source_url:
            raise KeyError("url")
        return RawListing(
            source_slug=self.source_slug,
            external_id=str(job.get("id") or job.get("slug") or job.get("guid") or source_url),
            source_url=source_url,
            content_hash=content_hash(job),
            raw_payload=job,
        )


def _job_items(payload: dict[str, Any]) -> list[Any] | None:
    for key in ("jobs", "data", "results"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return None


def _declared_total(payload: dict[str, Any]) -> int | None:
    for key in ("totalCount", "total_count", "total"):
        value = payload.get(key)
        if value is None:
            continue
        try:
            return max(int(value), 0)
        except (TypeError, ValueError):
            return None
    return None


def _source_url(job: dict[str, Any]) -> str:
    return _as_text(job.get("url") or job.get("jobUrl") or job.get("job_url"))


def _apply_url(job: dict[str, Any]) -> str:
    return _as_text(
        job.get("applicationLink")
        or job.get("applicationUrl")
        or job.get("applyUrl")
        or job.get("apply_url")
    )


def _job_title(job: dict[str, Any]) -> str:
    return _as_text(job.get("title") or job.get("jobTitle") or job.get("name"))


def _job_seniority(job: dict[str, Any]) -> str:
    return ", ".join(
        _text_values(job.get("seniority") or job.get("experience") or job.get("jobLevel"))
    )


def _company_name(job: dict[str, Any]) -> str:
    company = job.get("company")
    if isinstance(company, dict):
        company_name = _as_text(company.get("name") or company.get("companyName"))
        if _valid_company_name(company_name):
            return company_name

    company_name = _as_text(job.get("companyName") or job.get("company_name") or company)
    if _valid_company_name(company_name):
        return company_name

    company_slug = _as_text(job.get("companySlug") or job.get("company_slug"))
    return _company_name_from_slug(company_slug)


def _valid_company_name(value: str) -> bool:
    return bool(value and value.strip().lower() not in {"name", "company"})


def _company_name_from_slug(value: str) -> str:
    return " ".join(part.capitalize() for part in value.replace("_", "-").split("-") if part)


def _company_domain(job: dict[str, Any]) -> str | None:
    company = job.get("company")
    if isinstance(company, dict):
        for key in ("website", "websiteUrl", "domain"):
            value = _as_text(company.get(key))
            if value:
                return value
    return _as_text(job.get("companyDomain") or job.get("company_domain")) or None


def _location_values(job: dict[str, Any]) -> list[str]:
    for key in ("locations", "locationRestrictions", "countries"):
        values = _text_values(job.get(key))
        if values:
            return values

    location = job.get("location")
    if isinstance(location, dict):
        values = _text_values(location)
        if values:
            return values

    text = _as_text(location)
    return [text] if text else []


def _text_values(value: Any) -> list[str]:
    if isinstance(value, list):
        values: list[str] = []
        for item in value:
            values.extend(_text_values(item))
        return _dedupe(values)
    if isinstance(value, dict):
        for key in ("name", "label", "title", "value"):
            text = _as_text(value.get(key))
            if text:
                return [text]
        return _dedupe(_as_text(item) for item in value.values())
    text = _as_text(value)
    return [text] if text else []


def _dedupe(values: Any) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        text = _as_text(value)
        lowered = text.lower()
        if text and lowered not in seen:
            seen.add(lowered)
            deduped.append(text)
    return deduped


def _remote_value(job: dict[str, Any]) -> bool | None:
    value = job.get("remote") if "remote" in job else job.get("isRemote")
    if isinstance(value, bool):
        return value
    if value is None:
        return True
    text = _as_text(value).lower()
    if text in {"true", "1", "yes", "remote"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    return True


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
