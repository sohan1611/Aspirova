"""HackerEarth aggregator adapter using its public events endpoint."""

from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import urljoin

import httpx

from core.adapters import NormalizedListing, RawListing
from crawlers.common import (
    USER_AGENT,
    build_http_timeout,
    build_listings,
    content_hash,
    extract_text,
    is_plausible_deadline,
)

_BASE_URL = "https://www.hackerearth.com"
_API_URL = f"{_BASE_URL}/chrome-extension/events/"

HealthStatus = Literal["ok", "degraded", "broken"]


class HackerEarthAdapter:
    """SourceAdapter for HackerEarth challenge events."""

    source_slug = "hackerearth"
    requires_browser = False

    def __init__(self, timeout: float = 15.0) -> None:
        self._client = httpx.Client(
            timeout=build_http_timeout(timeout),
            headers={"User-Agent": USER_AGENT},
        )
        self._last_health: HealthStatus = "ok"
        self._raw_count = 0

    def fetch(self) -> list[RawListing]:
        self._raw_count = 0
        try:
            response = self._client.get(_API_URL)
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
            self._last_health = "degraded"
            return []

        if not isinstance(payload, dict):
            self._last_health = "degraded"
            return []
        events = payload.get("response")
        if not isinstance(events, list):
            self._last_health = "degraded"
            return []

        self._raw_count = len(events)
        listings = build_listings(events, self._build_raw_listing, source_slug=self.source_slug)
        self._last_health = "ok" if len(listings) == len(events) else "degraded"
        return listings

    def parse(self, raw: RawListing) -> NormalizedListing:
        event = raw.raw_payload
        title = extract_text(_as_text(event.get("title")))
        challenge_type = _as_text(event.get("challenge_type"))
        deadline = _event_deadline(event)

        return NormalizedListing(
            source_slug=self.source_slug,
            external_id=raw.external_id,
            source_url=raw.source_url,
            title=title,
            company_name="HackerEarth",
            company_domain="hackerearth.com",
            location="Online",
            is_remote=True,
            category=_category(challenge_type),
            description_raw=extract_text(_as_text(event.get("description"))),
            apply_url=raw.source_url,
            posted_at=_parse_datetime(event.get("start_timestamp") or event.get("start_time")),
            deadline=deadline,
            meta={
                "platform": "hackerearth",
                "challenge_type": challenge_type,
                "event_status": event.get("status"),
                "starts_at": _iso_or_none(
                    _parse_datetime(event.get("start_timestamp") or event.get("start_time"))
                ),
                "ends_at": _iso_or_none(deadline),
            },
            deadline_confidence="explicit" if deadline is not None else "unknown",
        )

    def health(self) -> HealthStatus:
        return self._last_health

    def coverage(self) -> dict[str, Any]:
        return {
            "mode": "unknown",
            "expected_total": None,
            "note": "source declares no total",
            "details": {"raw_count": self._raw_count},
        }

    def _build_raw_listing(self, event: dict[str, Any]) -> RawListing:
        source_url = urljoin(_BASE_URL, _as_text(event.get("url")))
        if not source_url:
            raise KeyError("url")
        return RawListing(
            source_slug=self.source_slug,
            external_id=str(event.get("id") or event.get("slug") or source_url),
            source_url=source_url,
            content_hash=content_hash(event),
            raw_payload=event,
        )


def _category(challenge_type: str) -> str:
    return "hackathon" if "hackathon" in challenge_type.lower() else "competition"


def _event_deadline(event: dict[str, Any]) -> datetime | None:
    deadline = _parse_datetime(
        event.get("end_timestamp") or event.get("end_time") or event.get("end")
    )
    return deadline if is_plausible_deadline(deadline) else None


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, (int, float)):
        timestamp = float(value) / 1000 if value > 10_000_000_000 else float(value)
        return datetime.fromtimestamp(timestamp, tz=UTC)

    text = _as_text(value)
    if not text:
        return None
    if text.isdigit():
        return _parse_datetime(int(text))
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _iso_or_none(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        return str(value).strip()
    except (TypeError, ValueError):
        return ""
