"""Lever ATS adapter (Doc handoffs/PHASE-2-HANDOFF.md sec 5, Part 2.5) -
the second ATS source per the ATS-first crawling strategy (Doc 04 sec 1).
One adapter class, parameterized by board token (companies.ats_board_id),
same shape as GreenhouseAdapter (Doc 04 sec 11): the ingestion pipeline
never changes, only the adapter.

Lever's public JSON endpoint (`api.lever.co/v0/postings/{token}?mode=json`)
conveniently provides plain-text description and remote/workplace fields
directly - no HTML-entity double-encoding to unwind, unlike Greenhouse's
`content` field (crawlers/greenhouse.py's _extract_text).
"""

from datetime import datetime, timezone
from typing import Literal

import httpx

from core.adapters import NormalizedListing, RawListing
from crawlers.common import USER_AGENT, build_listings, content_hash
from pipeline.normalize import classify_category


class LeverAdapter:
    """SourceAdapter for one company's Lever job board.
    Instantiate per company: LeverAdapter(board_token=..., company_name=...).
    """

    source_slug = "lever"
    requires_browser = False

    def __init__(self, board_token: str, company_name: str, timeout: float = 15.0) -> None:
        self.board_token = board_token
        self.company_name = company_name
        self._client = httpx.Client(timeout=timeout, headers={"User-Agent": USER_AGENT})
        self._last_health: Literal["ok", "degraded", "broken"] = "ok"

    def fetch(self) -> list[RawListing]:
        url = f"https://api.lever.co/v0/postings/{self.board_token}?mode=json"
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
            postings = response.json()
        except ValueError:
            self._last_health = "broken"
            return []

        # Unknown board tokens can return 200 error objects, so check shape, not length.
        if not isinstance(postings, list):
            self._last_health = "broken"
            return []

        self._last_health = "ok"

        return build_listings(
            postings,
            lambda posting: RawListing(
                source_slug=self.source_slug,
                external_id=posting["id"],
                source_url=posting["hostedUrl"],
                content_hash=content_hash(posting),
                raw_payload=posting,
            ),
            source_slug=self.source_slug,
        )

    def parse(self, raw: RawListing) -> NormalizedListing:
        posting = raw.raw_payload
        title = posting["text"]
        categories = posting.get("categories") or {}
        location = categories.get("location")
        workplace_type = posting.get("workplaceType")

        posted_at: datetime | None = None
        created_at_ms = posting.get("createdAt")
        if created_at_ms:
            posted_at = datetime.fromtimestamp(created_at_ms / 1000, tz=timezone.utc)

        return NormalizedListing(
            source_slug=self.source_slug,
            external_id=raw.external_id,
            source_url=raw.source_url,
            title=title,
            company_name=self.company_name,
            location=location,
            is_remote=workplace_type == "remote" if workplace_type else None,
            category=classify_category(title),
            description_raw=posting.get("descriptionPlain") or "",
            apply_url=posting["hostedUrl"],
            posted_at=posted_at,
            deadline=None,
            deadline_confidence="unknown",
        )

    def health(self) -> Literal["ok", "degraded", "broken"]:
        return self._last_health
