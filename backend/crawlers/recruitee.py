from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from core.adapters import NormalizedListing, RawListing, SourceAdapter
from crawlers.common import USER_AGENT, build_listings, content_hash, extract_text
from pipeline.normalize import classify_category


class RecruiteeAdapter(SourceAdapter):
    source_slug = "recruitee"
    requires_browser = False

    def __init__(self, board_token: str, company_name: str, timeout: float = 15.0) -> None:
        self.board_token = board_token
        self.company_name = company_name
        self._last_health = "unknown"
        self.client = httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
            follow_redirects=True,
        )

    @property
    def offers_url(self) -> str:
        return f"https://{self.board_token}.recruitee.com/api/offers/"

    def fetch(self) -> list[RawListing]:
        try:
            response = self.client.get(self.offers_url)
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
        if not isinstance(payload, dict) or "offers" not in payload:
            self._last_health = "broken"
            return []

        offers = payload["offers"]
        if not isinstance(offers, list):
            self._last_health = "broken"
            return []

        listings = build_listings(
            (offer for offer in offers if self._is_published(offer)),
            lambda offer: RawListing(
                source_slug=self.source_slug,
                external_id=str(offer["id"]),
                source_url=self._source_url(offer),
                content_hash=content_hash(offer),
                raw_payload=offer,
            ),
            source_slug=self.source_slug,
        )

        self._last_health = "ok"
        return listings

    def parse(self, raw: RawListing) -> NormalizedListing:
        offer = raw.raw_payload
        title = offer.get("title") or offer.get("position") or ""
        apply_url = offer.get("careers_apply_url") or offer.get("careers_url")
        source_url = raw.source_url or self._source_url(offer)

        return NormalizedListing(
            source_slug=self.source_slug,
            external_id=raw.external_id,
            title=title,
            company_name=self.company_name,
            location=self._location(offer),
            is_remote=bool(offer.get("remote")),
            category=classify_category(title),
            description_raw=extract_text(offer.get("description")),
            apply_url=apply_url or source_url,
            source_url=source_url,
            posted_at=self._parse_datetime(offer.get("published_at") or offer.get("created_at")),
            deadline=None,
            deadline_confidence="unknown",
        )

    def health(self) -> str:
        return self._last_health

    def _source_url(self, offer: dict[str, Any]) -> str:
        if offer.get("careers_url"):
            return str(offer["careers_url"])
        if offer.get("careers_apply_url"):
            return str(offer["careers_apply_url"])
        if offer.get("slug"):
            return f"https://{self.board_token}.recruitee.com/o/{offer['slug']}"
        return self.offers_url

    @staticmethod
    def _is_published(offer: Any) -> bool:
        if not isinstance(offer, dict):
            return False
        status = offer.get("status")
        return status is None or status == "published"

    @staticmethod
    def _location(offer: dict[str, Any]) -> str | None:
        parts = [
            str(part).strip()
            for part in (
                offer.get("city"),
                offer.get("state_name"),
                offer.get("country"),
            )
            if part
        ]
        if parts:
            return ", ".join(parts)

        location = offer.get("location")
        if location:
            return str(location).strip() or None
        return None

    @staticmethod
    def _parse_datetime(value: Any) -> datetime | None:
        if not value or not isinstance(value, str):
            return None

        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
