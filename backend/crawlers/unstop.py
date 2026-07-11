"""Unstop aggregator adapter using its public opportunity search API."""

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import httpx

from core.adapters import NormalizedListing, RawListing
from crawlers.common import USER_AGENT, content_hash, extract_text

_API_URL = "https://unstop.com/api/public/opportunity/search-result"
_OPPORTUNITY_TYPES = ("competitions", "hackathons")
_PAGE_SIZE = 100
_MAX_PAGES = 10

HealthStatus = Literal["ok", "degraded", "broken"]


class UnstopAdapter:
    """SourceAdapter for Unstop's multi-organizer opportunity feed."""

    source_slug = "unstop"
    requires_browser = False

    def __init__(self, timeout: float = 15.0) -> None:
        self._client = httpx.Client(timeout=timeout, headers={"User-Agent": USER_AGENT})
        self._last_health: HealthStatus = "ok"

    def fetch(self) -> list[RawListing]:
        listings: list[RawListing] = []
        seen_ids: set[str] = set()
        degraded = False
        expiry_cutoff = datetime.now(UTC) - timedelta(days=14)

        for opportunity_type in _OPPORTUNITY_TYPES:
            for page in range(1, _MAX_PAGES + 1):
                try:
                    response = self._client.get(
                        _API_URL,
                        params={
                            "opportunity": opportunity_type,
                            "per_page": _PAGE_SIZE,
                            "page": page,
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

                items = _opportunity_items(payload)
                if items is None:
                    self._last_health = "degraded"
                    return listings
                if not items:
                    break

                for item in items:
                    if not isinstance(item, dict):
                        degraded = True
                        continue

                    deadline = _parse_iso_datetime(item.get("end_date"))
                    if deadline is not None and deadline < expiry_cutoff:
                        continue

                    opportunity_id = item.get("id")
                    source_url = _as_text(item.get("seo_url"))
                    if opportunity_id is None or not source_url:
                        degraded = True
                        continue

                    external_id = str(opportunity_id)
                    if external_id in seen_ids:
                        continue

                    seen_ids.add(external_id)
                    listings.append(
                        RawListing(
                            source_slug=self.source_slug,
                            external_id=external_id,
                            source_url=source_url,
                            content_hash=content_hash(item),
                            raw_payload=item,
                        )
                    )

        self._last_health = "degraded" if degraded else "ok"
        return listings

    def parse(self, raw: RawListing) -> NormalizedListing:
        opportunity = raw.raw_payload
        organization = opportunity.get("organisation") or {}
        if not isinstance(organization, dict):
            organization = {}

        organizer = extract_text(_as_text(organization.get("name"))) or None
        opportunity_type = _as_text(opportunity.get("type")) or None
        region = _as_text(opportunity.get("region")) or None
        deadline = _parse_iso_datetime(opportunity.get("end_date"))
        apply_url = _as_text(opportunity.get("seo_url")) or raw.source_url

        prizes = opportunity.get("prizes")
        if not isinstance(prizes, list):
            prizes = []
        offers_ppi = any(bool(prize.get("pre_placement_internship")) for prize in prizes)
        offers_ppo = any(bool(prize.get("pre_placement_opportunity")) for prize in prizes)
        skills = opportunity.get("required_skills")
        if not isinstance(skills, list):
            skills = []

        return NormalizedListing(
            source_slug=self.source_slug,
            external_id=raw.external_id,
            source_url=raw.source_url,
            title=extract_text(_as_text(opportunity.get("title"))),
            company_name=organizer or "Unstop",
            company_domain=None,
            location=region,
            is_remote=(region or "").lower() == "online",
            category=(
                "hackathon" if (opportunity_type or "").lower() == "hackathons" else "competition"
            ),
            description_raw=extract_text(_as_text(opportunity.get("details"))),
            apply_url=apply_url,
            deadline=deadline,
            meta={
                "platform": "unstop",
                "organizer": organizer,
                "type": opportunity_type,
                "subtype": opportunity.get("subtype"),
                "mode": region,
                "prizes": prizes,
                "offers_ppi": offers_ppi,
                "offers_ppo": offers_ppo,
                "register_count": opportunity.get("registerCount"),
                "skills": skills,
                "is_paid": opportunity.get("isPaid"),
            },
            deadline_confidence="explicit" if deadline is not None else "unknown",
        )

    def health(self) -> HealthStatus:
        return self._last_health


def _opportunity_items(payload: Any) -> list[Any] | None:
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    items = data.get("data")
    if not isinstance(items, list):
        return None
    return items


def _parse_iso_datetime(value: Any) -> datetime | None:
    text = _as_text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
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
