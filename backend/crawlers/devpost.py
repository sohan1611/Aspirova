"""Devpost aggregator adapter using its public hackathon JSON API."""

import html
import re
from datetime import UTC, datetime
from typing import Any, Literal

import httpx
from bs4 import BeautifulSoup

from core.adapters import NormalizedListing, RawListing
from crawlers.common import (
    USER_AGENT,
    build_listings,
    content_hash,
    extract_text,
    is_plausible_deadline,
)

_API_URL = "https://devpost.com/api/hackathons"
_MAX_PAGES = 10

HealthStatus = Literal["ok", "degraded", "broken"]


class DevpostAdapter:
    """SourceAdapter for Devpost's multi-organizer hackathon feed."""

    source_slug = "devpost"
    requires_browser = False

    def __init__(self, timeout: float = 15.0) -> None:
        self._client = httpx.Client(timeout=timeout, headers={"User-Agent": USER_AGENT})
        self._last_health: HealthStatus = "ok"

    def fetch(self) -> list[RawListing]:
        listings: list[RawListing] = []
        degraded = False

        for page in range(1, _MAX_PAGES + 1):
            try:
                response = self._client.get(
                    _API_URL,
                    params={"status[]": "open", "page": page},
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

            hackathons = payload.get("hackathons")
            if not isinstance(hackathons, list):
                self._last_health = "degraded"
                return listings
            if not hackathons:
                self._last_health = "degraded" if degraded else "ok"
                return listings

            def build_hackathon(hackathon: Any) -> RawListing:
                if not isinstance(hackathon, dict):
                    raise TypeError("hackathon is not an object")

                hackathon_id = hackathon.get("id")
                source_url = _as_text(hackathon.get("url"))
                if hackathon_id is None or not source_url:
                    raise KeyError("id/url")

                return RawListing(
                    source_slug=self.source_slug,
                    external_id=str(hackathon_id),
                    source_url=source_url,
                    content_hash=content_hash(hackathon),
                    raw_payload=hackathon,
                )

            page_listings = build_listings(
                hackathons,
                build_hackathon,
                source_slug=self.source_slug,
            )
            if len(page_listings) != len(hackathons):
                degraded = True
            listings.extend(page_listings)

        self._last_health = "degraded" if degraded else "ok"
        return listings

    def parse(self, raw: RawListing) -> NormalizedListing:
        hackathon = raw.raw_payload
        organizer = extract_text(_as_text(hackathon.get("organization_name"))) or None

        displayed_location = hackathon.get("displayed_location") or {}
        if not isinstance(displayed_location, dict):
            displayed_location = {}
        location = extract_text(_as_text(displayed_location.get("location"))) or None

        themes: list[str] = []
        raw_themes = hackathon.get("themes") or []
        if isinstance(raw_themes, list):
            for theme in raw_themes:
                if not isinstance(theme, dict):
                    continue
                name = extract_text(_as_text(theme.get("name")))
                if name:
                    themes.append(name)

        description_parts = [extract_text(_as_text(hackathon.get("description")))]
        description_parts.extend(themes)
        description_raw = " ".join(part for part in description_parts if part)

        dates = _as_text(hackathon.get("submission_period_dates")) or None
        deadline = _parse_submission_deadline(dates)
        apply_url = _as_text(hackathon.get("url")) or raw.source_url

        return NormalizedListing(
            source_slug=self.source_slug,
            external_id=raw.external_id,
            source_url=raw.source_url,
            title=extract_text(_as_text(hackathon.get("title"))),
            company_name=organizer or "Devpost",
            company_domain=None,
            location=location,
            is_remote="online" in (location or "").lower(),
            category="hackathon",
            description_raw=description_raw,
            apply_url=apply_url,
            deadline=deadline,
            meta={
                "platform": "devpost",
                "organizer": organizer,
                "prize": _strip_html(hackathon.get("prize_amount")),
                "themes": themes,
                "registrations_count": hackathon.get("registrations_count"),
                "mode": location,
                "dates": dates,
            },
            deadline_confidence="explicit" if deadline is not None else "unknown",
        )

    def health(self) -> HealthStatus:
        return self._last_health


def _parse_submission_deadline(value: Any) -> datetime | None:
    text = _as_text(value)
    if not text:
        return None

    # Ranges omit the year from the start date; the final segment is the
    # submission deadline and always carries the year.
    deadline_text = re.split(r"\s+[-\u2013\u2014]\s+", text)[-1].strip()
    try:
        parsed = datetime.strptime(deadline_text, "%b %d, %Y")
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed if is_plausible_deadline(parsed) else None


def _strip_html(value: Any) -> str:
    text = _as_text(value)
    if not text:
        return ""
    return BeautifulSoup(html.unescape(text), "html.parser").get_text(strip=True)


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        return str(value).strip()
    except (TypeError, ValueError):
        return ""
