from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from core.adapters import NormalizedListing, RawListing, SourceAdapter
from crawlers.common import (
    USER_AGENT,
    build_http_timeout,
    build_listings,
    content_hash,
    extract_text,
)
from pipeline.normalize import classify_category


class WorkableAdapter(SourceAdapter):
    source_slug = "workable"
    requires_browser = False

    def __init__(
        self,
        board_token: str,
        company_name: str,
        timeout: float = 15.0,
    ) -> None:
        self.board_token = board_token
        self.company_name = company_name
        self.client = httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=build_http_timeout(timeout),
        )
        self._last_health = "ok"

    def fetch(self) -> list[RawListing]:
        url = (
            "https://apply.workable.com/api/v1/widget/accounts/" f"{self.board_token}?details=true"
        )

        try:
            response = self.client.get(url, follow_redirects=True)
        except httpx.RequestError:
            self._last_health = "degraded"
            return []

        if response.status_code == 404:
            self._last_health = "broken"
            return []

        if response.status_code != 200:
            self._last_health = "degraded"
            return []

        try:
            payload = response.json()
        except ValueError:
            self._last_health = "broken"
            return []

        # Unknown board tokens can return 200 error objects, so check shape, not length.
        if not isinstance(payload, dict) or "jobs" not in payload:
            self._last_health = "broken"
            return []

        jobs = payload["jobs"]
        if not isinstance(jobs, list):
            self._last_health = "broken"
            return []

        self._last_health = "ok"

        def build_job(job: Any) -> RawListing:
            if not isinstance(job, dict):
                raise TypeError("job is not an object")

            shortcode = job.get("shortcode")
            if not shortcode:
                raise KeyError("shortcode")

            return RawListing(
                source_slug=self.source_slug,
                external_id=str(shortcode),
                source_url=job.get("url") or job.get("application_url"),
                content_hash=content_hash(job),
                raw_payload=job,
            )

        return build_listings(jobs, build_job, source_slug=self.source_slug)

    def parse(self, raw: RawListing) -> NormalizedListing:
        job = raw.raw_payload
        location = _location_from_job(job)
        location_text = location or ""
        published_at = _parse_date(job.get("published_on") or job.get("created_at"))

        return NormalizedListing(
            source_slug=self.source_slug,
            external_id=raw.external_id,
            title=job["title"],
            company_name=self.company_name,
            location=location,
            is_remote=bool(job.get("telecommuting")) or ("remote" in location_text.lower()),
            category=classify_category(job["title"]),
            apply_url=job.get("application_url") or job.get("url") or job.get("shortlink"),
            source_url=raw.source_url,
            description_raw=extract_text(job.get("description") or ""),
            posted_at=published_at,
            deadline=None,
            deadline_confidence="unknown",
        )

    def health(self) -> str:
        return self._last_health


def _location_from_job(job: dict[str, Any]) -> str | None:
    flat_location = _join_location_parts([job.get("city"), job.get("state"), job.get("country")])
    if flat_location:
        return flat_location

    locations = job.get("locations") or []
    if not locations:
        return None

    first_location = locations[0] or {}
    return _join_location_parts(
        [
            first_location.get("city"),
            first_location.get("region"),
            first_location.get("country"),
        ]
    )


def _join_location_parts(parts: list[Any]) -> str | None:
    location = ", ".join(str(part).strip() for part in parts if str(part or "").strip())
    return location or None


def _parse_date(value: Any) -> datetime | None:
    if not value:
        return None

    try:
        return datetime.strptime(str(value), "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        return None
