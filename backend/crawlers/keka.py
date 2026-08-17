"""Adapter for public Keka careers boards."""

import re
from datetime import datetime
from typing import Any, Literal

import httpx

from core.adapters import NormalizedListing, RawListing
from crawlers.common import USER_AGENT
from crawlers.common import build_http_timeout
from crawlers.common import build_listings
from crawlers.common import content_hash as _content_hash
from crawlers.common import extract_text as _extract_text
from pipeline.normalize import classify_category

HealthStatus = Literal["ok", "degraded", "broken"]

_UUID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)
_REMOTE_PATTERN = re.compile(r"\bremote\b(?!\s+(?:sensing|sensors?)\b)", re.IGNORECASE)


class KekaAdapter:
    """Fetch active listings from a Keka tenant's public careers board."""

    source_slug = "keka"
    requires_browser = False

    def __init__(self, board_token: str, company_name: str, timeout: float = 15.0) -> None:
        self.board_token = board_token
        self.company_name = company_name
        self._careers_url = f"https://{board_token}.keka.com/careers/"
        self._client = httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=build_http_timeout(timeout),
        )
        self._last_health: HealthStatus = "ok"

    def health(self) -> HealthStatus:
        return self._last_health

    def _active_jobs_url(self, tenant_uuid: str) -> str:
        return (
            f"https://{self.board_token}.keka.com/careers/"
            f"api/embedjobs/default/active/{tenant_uuid}"
        )

    def _job_url(self, job_id: str) -> str:
        return f"https://{self.board_token}.keka.com/careers/jobdetails/{job_id}"

    def fetch(self) -> list[RawListing]:
        try:
            careers_response = self._client.get(self._careers_url)
        except httpx.RequestError:
            self._last_health = "degraded"
            return []

        if careers_response.status_code == 404:
            self._last_health = "broken"
            return []
        if careers_response.status_code != 200:
            self._last_health = "degraded"
            return []

        careers_html = careers_response.text
        if not isinstance(careers_html, str):
            self._last_health = "degraded"
            return []

        uuid_match = _UUID_PATTERN.search(careers_html)
        if uuid_match is None:
            self._last_health = "broken"
            return []

        try:
            jobs_response = self._client.get(self._active_jobs_url(uuid_match.group(0)))
        except httpx.RequestError:
            self._last_health = "degraded"
            return []

        if jobs_response.status_code == 404:
            self._last_health = "broken"
            return []
        if jobs_response.status_code != 200:
            self._last_health = "degraded"
            return []

        try:
            payload: Any = jobs_response.json()
        except (TypeError, ValueError):
            self._last_health = "broken"
            return []

        # Unknown board tokens can return 200 error objects, so check shape, not length.
        if not isinstance(payload, list):
            self._last_health = "broken"
            return []

        def build_job(job: Any) -> RawListing:
            if not isinstance(job, dict):
                raise TypeError("job is not an object")

            job_id = job.get("id")
            if isinstance(job_id, bool) or not isinstance(job_id, (int, str)):
                raise KeyError("id")

            external_id = str(job_id)
            return RawListing(
                source_slug=self.source_slug,
                external_id=external_id,
                source_url=self._job_url(external_id),
                raw_payload=job,
                content_hash=_content_hash(job),
            )

        listings = build_listings(payload, build_job, source_slug=self.source_slug)
        self._last_health = "ok"
        return listings

    def parse(self, raw: RawListing) -> NormalizedListing:
        raw_payload = getattr(raw, "raw_payload", {})
        job = raw_payload if isinstance(raw_payload, dict) else {}

        title_value = job.get("title")
        title = title_value.strip() if isinstance(title_value, str) else ""

        description_value = job.get("description")
        description = _extract_text(
            description_value if isinstance(description_value, str) else None
        ).strip()
        if not description:
            excerpt_value = job.get("excerpt")
            description = excerpt_value.strip() if isinstance(excerpt_value, str) else ""

        location = ""
        job_locations = job.get("jobLocations")
        if isinstance(job_locations, list) and job_locations:
            first_location = job_locations[0]
            if isinstance(first_location, dict):
                location_parts = []
                for key in ("city", "state", "countryName"):
                    value = first_location.get(key)
                    if isinstance(value, str) and value.strip():
                        location_parts.append(value.strip())
                location = ", ".join(location_parts)

        posted_at = None
        published_on = job.get("publishedOn")
        if isinstance(published_on, str) and published_on:
            try:
                posted_at = datetime.fromisoformat(published_on.replace("Z", "+00:00"))
            except ValueError:
                pass

        job_id = job.get("id")
        if isinstance(job_id, bool) or not isinstance(job_id, (int, str)):
            job_id = getattr(raw, "external_id", "")
        external_id = str(job_id) if isinstance(job_id, (int, str)) else ""

        return NormalizedListing(
            source_slug=self.source_slug,
            external_id=external_id,
            source_url=raw.source_url,
            title=title,
            company_name=self.company_name,
            location=location,
            description_raw=description,
            apply_url=self._job_url(external_id),
            posted_at=posted_at,
            deadline=None,
            deadline_confidence="unknown",
            is_remote=bool(_REMOTE_PATTERN.search(f"{title} {location}")),
            category=classify_category(title),
        )
