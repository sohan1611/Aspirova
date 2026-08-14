"""Greenhouse ATS adapter - the first and primary source per the ATS-first
crawling strategy (Doc 04 sec 1). One adapter class, parameterized by board
token, covers every Greenhouse company (Doc 04 sec 11) - board tokens are
DATA (companies.ats_board_id), never hardcoded here.
"""

from datetime import datetime
from typing import Literal

import httpx

from core.adapters import NormalizedListing, RawListing
from crawlers.common import USER_AGENT, build_listings
from crawlers.common import content_hash as _content_hash
from crawlers.common import extract_text as _extract_text
from pipeline.normalize import classify_category


class GreenhouseAdapter:
    """SourceAdapter for one company's Greenhouse job board.
    Instantiate per company (Doc 04 sec 11): GreenhouseAdapter(board_token=..., company_name=...).
    """

    source_slug = "greenhouse"
    requires_browser = False

    def __init__(self, board_token: str, company_name: str, timeout: float = 15.0) -> None:
        self.board_token = board_token
        self.company_name = company_name
        self._client = httpx.Client(timeout=timeout, headers={"User-Agent": USER_AGENT})
        self._last_health: Literal["ok", "degraded", "broken"] = "ok"

    def fetch(self) -> list[RawListing]:
        url = f"https://boards-api.greenhouse.io/v1/boards/{self.board_token}/jobs?content=true"
        try:
            response = self._client.get(url)
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
        if (
            not isinstance(payload, dict)
            or "jobs" not in payload
            or not isinstance(payload["jobs"], list)
        ):
            self._last_health = "broken"
            return []

        jobs = payload["jobs"]
        self._last_health = "ok"

        return build_listings(
            jobs,
            lambda job: RawListing(
                source_slug=self.source_slug,
                external_id=str(job["id"]),
                source_url=job["absolute_url"],
                content_hash=_content_hash(job),
                raw_payload=job,
            ),
            source_slug=self.source_slug,
        )

    def parse(self, raw: RawListing) -> NormalizedListing:
        job = raw.raw_payload
        location_name = (job.get("location") or {}).get("name")
        description_raw = _extract_text(job.get("content"))
        title = job["title"]

        posted_at: datetime | None = None
        if job.get("updated_at"):
            posted_at = datetime.fromisoformat(job["updated_at"])

        return NormalizedListing(
            source_slug=self.source_slug,
            external_id=raw.external_id,
            source_url=raw.source_url,
            title=title,
            company_name=self.company_name,
            location=location_name,
            is_remote=bool(location_name and "remote" in location_name.lower()),
            category=classify_category(title),
            description_raw=description_raw,
            apply_url=job["absolute_url"],
            posted_at=posted_at,
            deadline=None,
            deadline_confidence="unknown",
        )

    def health(self) -> Literal["ok", "degraded", "broken"]:
        return self._last_health
