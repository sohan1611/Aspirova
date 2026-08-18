"""Amazon jobs adapter using the public search JSON endpoint.

Unlike the parameterized ATS adapters, Amazon has one employer-wide API.
The ``board_token`` argument is retained only for runner compatibility. The
crawl is deliberately focused on student roles and capped per search term so
it never expands into Amazon's full global job catalogue.
"""

import re
import time
from datetime import datetime, timezone
from typing import Any, Literal

import httpx

from core.adapters import NormalizedListing, RawListing
from crawlers.common import (
    USER_AGENT,
    build_http_timeout,
    build_listings,
    content_hash,
    extract_text,
)
from pipeline.normalize import classify_category

_BASE_URL = "https://www.amazon.jobs"
_SEARCH_URL = f"{_BASE_URL}/en/search.json"
_SEARCH_TERMS = ("intern", "new grad", "graduate")
_PAGE_SIZE = 100
_PER_QUERY_CAP = 300
_REQUEST_DELAY_SECONDS = 0.5
_REMOTE_PATTERN = re.compile(r"\b(remote|virtual)\b(?!\s+(?:sensing|sensors?)\b)", re.IGNORECASE)

HealthStatus = Literal["ok", "degraded", "broken"]


class AmazonAdapter:
    """SourceAdapter for Amazon's employer-wide jobs search."""

    source_slug = "amazon"
    requires_browser = False

    def __init__(self, board_token: str, company_name: str, timeout: float = 15.0) -> None:
        self.board_token = board_token
        self.company_name = company_name
        self._client = httpx.Client(
            timeout=build_http_timeout(timeout),
            headers={"User-Agent": USER_AGENT},
        )
        self._last_health: HealthStatus = "ok"
        self._declared_hits_by_query: dict[str, int] = {}

    def fetch(self) -> list[RawListing]:
        listings: list[RawListing] = []
        seen_ids: set[str] = set()
        request_count = 0
        degraded = False
        self._declared_hits_by_query = {}

        for query in _SEARCH_TERMS:
            offset = 0

            while offset < _PER_QUERY_CAP:
                if request_count:
                    time.sleep(_REQUEST_DELAY_SECONDS)
                request_count += 1

                try:
                    response = self._client.get(
                        _SEARCH_URL,
                        params={
                            "base_query": query,
                            "result_limit": _PAGE_SIZE,
                            "offset": offset,
                            "sort": "recent",
                        },
                    )
                except httpx.RequestError:
                    self._last_health = "degraded"
                    return listings

                if response.status_code == 404:
                    self._last_health = "broken"
                    return listings
                if response.status_code != 200:
                    self._last_health = "degraded"
                    return listings

                try:
                    payload = response.json()
                except ValueError:
                    self._last_health = "degraded"
                    return listings

                if not isinstance(payload, dict):
                    self._last_health = "degraded"
                    return listings

                jobs = payload.get("jobs") or []
                if not isinstance(jobs, list):
                    self._last_health = "degraded"
                    return listings

                try:
                    hits = max(0, int(payload.get("hits", 0)))
                except (TypeError, ValueError):
                    self._last_health = "degraded"
                    return listings
                self._declared_hits_by_query.setdefault(query, hits)

                remaining = _PER_QUERY_CAP - offset

                def build_job(job: Any) -> RawListing:
                    if not isinstance(job, dict):
                        raise TypeError("job is not an object")

                    job_id = job.get("id")
                    job_path = job.get("job_path")
                    if job_id is None or not job_path:
                        raise KeyError("id/job_path")

                    return RawListing(
                        source_slug=self.source_slug,
                        external_id=str(job_id),
                        source_url=f"{_BASE_URL}{job_path}",
                        content_hash=content_hash(job),
                        raw_payload=job,
                    )

                for job in jobs[: min(_PAGE_SIZE, remaining)]:
                    job_listings = build_listings(
                        [job],
                        build_job,
                        source_slug=self.source_slug,
                    )
                    if not job_listings:
                        degraded = True
                        continue

                    listing = job_listings[0]
                    external_id = listing.external_id
                    if external_id in seen_ids:
                        continue

                    seen_ids.add(external_id)
                    listings.append(listing)

                offset += _PAGE_SIZE
                if not jobs or offset >= min(hits, _PER_QUERY_CAP):
                    break

        self._last_health = "degraded" if degraded else "ok"
        return listings

    def parse(self, raw: RawListing) -> NormalizedListing:
        job = raw.raw_payload if isinstance(raw.raw_payload, dict) else {}
        title = _as_text(job.get("title"))

        normalized_location = _as_text(job.get("normalized_location"))
        if normalized_location:
            location: str | None = normalized_location
        else:
            location_parts = [
                _as_text(job.get(field)) for field in ("city", "state", "country_code")
            ]
            location = ", ".join(part for part in location_parts if part) or None

        posted_at: datetime | None = None
        posted_date = job.get("posted_date")
        if posted_date:
            try:
                posted_at = datetime.strptime(str(posted_date), "%B %d, %Y")
                if posted_at.tzinfo is None:
                    posted_at = posted_at.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                posted_at = None

        try:
            description_raw = extract_text(_as_text(job.get("description_short")))
        except (TypeError, ValueError):
            description_raw = ""

        remote_text = f"{title} {location or ''}"

        return NormalizedListing(
            source_slug=self.source_slug,
            external_id=raw.external_id,
            source_url=raw.source_url,
            title=title,
            company_name=self.company_name,
            location=location,
            is_remote=bool(_REMOTE_PATTERN.search(remote_text)),
            category=classify_category(title),
            description_raw=description_raw,
            apply_url=raw.source_url,
            posted_at=posted_at,
            deadline=None,
            deadline_confidence="unknown",
        )

    def health(self) -> HealthStatus:
        return self._last_health

    def coverage(self) -> dict[str, Any]:
        declared_hits_by_query = dict(self._declared_hits_by_query)
        capped_queries = [
            query for query, hits in declared_hits_by_query.items() if hits > _PER_QUERY_CAP
        ]
        missing_queries = [query for query in _SEARCH_TERMS if query not in declared_hits_by_query]
        details: dict[str, Any] = {"declared_hits_by_query": declared_hits_by_query}
        if capped_queries:
            details["capped_queries"] = capped_queries
        if missing_queries:
            details["missing_queries"] = missing_queries

        status = "partial" if capped_queries else "complete"
        if missing_queries:
            status = "unknown"

        return {
            "mode": "declared_query_totals",
            "expected_total": None,
            "status": status,
            "note": (
                "Amazon search terms overlap, so summed per-query hits are not "
                "a valid distinct-listing denominator."
            ),
            "details": details,
        }


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        return str(value).strip()
    except (TypeError, ValueError):
        return ""
