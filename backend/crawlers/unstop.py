"""Unstop aggregator adapter using its public opportunity search API."""

from datetime import UTC, datetime, timedelta
from time import monotonic
from typing import Any, Callable, Literal

import httpx

from core.adapters import NormalizedListing, RawListing
from crawlers.common import (
    USER_AGENT,
    build_listings,
    content_hash,
    extract_text,
    is_plausible_deadline,
)

_API_URL = "https://unstop.com/api/public/opportunity/search-result"
_OPPORTUNITY_TYPES = ("internships", "competitions", "hackathons")
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
        self._stopped_early = False

    @property
    def stopped_early(self) -> bool:
        """Whether the most recent fetch returned a deliberately incomplete
        page set because its crawler deadline or stop signal was reached."""
        return self._stopped_early

    def fetch(
        self,
        *,
        deadline_monotonic: float | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> list[RawListing]:
        listings: list[RawListing] = []
        seen_ids: set[str] = set()
        degraded = False
        expiry_cutoff = datetime.now(UTC) - timedelta(days=14)
        self._stopped_early = False

        for opportunity_type in _OPPORTUNITY_TYPES:
            for page in range(1, _MAX_PAGES + 1):
                if _should_stop(deadline_monotonic, should_stop):
                    self._stopped_early = True
                    return listings

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

                if _should_stop(deadline_monotonic, should_stop):
                    self._stopped_early = True
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

                    deadline = _registration_deadline(item)
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
                    # Record WHICH search returned this item — Unstop's per-item
                    # "type" is unreliable (internships come back with type="jobs"),
                    # so category must be derived from the search opportunity type.
                    item["_aspirova_opportunity"] = opportunity_type
                    item_listings = build_listings(
                        [item],
                        lambda item: RawListing(
                            source_slug=self.source_slug,
                            external_id=external_id,
                            source_url=source_url,
                            content_hash=content_hash(item),
                            raw_payload=item,
                        ),
                        source_slug=self.source_slug,
                    )
                    if not item_listings:
                        degraded = True
                        continue
                    listings.extend(item_listings)

        self._last_health = "degraded" if degraded else "ok"
        return listings

    def parse(self, raw: RawListing) -> NormalizedListing:
        opportunity = raw.raw_payload
        organization = opportunity.get("organisation") or {}
        if not isinstance(organization, dict):
            organization = {}

        organizer = extract_text(_as_text(organization.get("name"))) or None
        # Category comes from the SEARCH that returned this item (authoritative),
        # not the item's own "type" (Unstop returns internships with type="jobs").
        search_opportunity = _as_text(opportunity.get("_aspirova_opportunity")).lower()
        item_type = (_as_text(opportunity.get("type")) or "").lower()
        if search_opportunity == "internships":
            category = "internship"
        elif search_opportunity == "hackathons" or item_type == "hackathons":
            category = "hackathon"
        else:
            category = "competition"
        region = _as_text(opportunity.get("region")) or None
        deadline = _registration_deadline(opportunity)
        apply_url = _as_text(opportunity.get("seo_url")) or raw.source_url
        location = _location_from_payload(opportunity, region)

        prizes = opportunity.get("prizes")
        if not isinstance(prizes, list):
            prizes = []
        offers_ppi = any(bool(prize.get("pre_placement_internship")) for prize in prizes)
        offers_ppo = any(bool(prize.get("pre_placement_opportunity")) for prize in prizes)
        # Trim prizes to display essentials — Unstop's raw objects carry pivot/
        # entity internals that bloat every /feed response with no user value.
        trimmed_prizes = [
            {
                "rank": prize.get("rank"),
                "cash": prize.get("cash"),
                "currency": prize.get("currency"),
            }
            for prize in prizes
            if isinstance(prize, dict)
        ]
        # Skills -> a deduped list of plain name strings (raw skills are nested
        # objects with pivot/ai_generated flags — huge payload, no value here).
        skills: list[str] = []
        raw_skills = opportunity.get("required_skills")
        if isinstance(raw_skills, list):
            _seen_skills: set[str] = set()
            for skill in raw_skills:
                name = (
                    _as_text(skill.get("skill_name") or skill.get("skill"))
                    if isinstance(skill, dict)
                    else _as_text(skill)
                ).strip()
                if name and name.lower() not in _seen_skills:
                    _seen_skills.add(name.lower())
                    skills.append(name)

        return NormalizedListing(
            source_slug=self.source_slug,
            external_id=raw.external_id,
            source_url=raw.source_url,
            title=extract_text(_as_text(opportunity.get("title"))),
            company_name=organizer or "Unstop",
            company_domain=None,
            location=location,
            is_remote=(region or "").lower() == "online",
            category=category,
            description_raw=extract_text(_as_text(opportunity.get("details"))),
            apply_url=apply_url,
            deadline=deadline,
            meta={
                "platform": "unstop",
                "organizer": organizer,
                "type": item_type or search_opportunity,
                "subtype": opportunity.get("subtype"),
                "mode": region,
                "prizes": trimmed_prizes,
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


def _should_stop(deadline_monotonic: float | None, should_stop: Callable[[], bool] | None) -> bool:
    if deadline_monotonic is not None and monotonic() >= deadline_monotonic:
        return True
    return should_stop() if should_stop is not None else False


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


def _location_from_payload(opportunity: dict[str, Any], region: str | None) -> str | None:
    if (region or "").lower() == "online":
        return "Online"

    address = opportunity.get("address_with_country_logo")
    if not isinstance(address, dict):
        return None

    parts = [
        _as_text(address.get("city")),
        _as_text(address.get("state")),
        _country_name(address.get("country")),
    ]
    location = ", ".join(part for part in parts if part)
    return location or None


def _country_name(country: Any) -> str:
    if isinstance(country, dict):
        return _as_text(country.get("name"))

    text = _as_text(country)
    if len(text) in {2, 3} and text.isalpha():
        return ""
    return text


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


def _registration_deadline(item: Any) -> datetime | None:
    """The real deadline is when REGISTRATION closes (regnRequirements.end_regn_dt),
    NOT end_date — which is the event's final-round date and can be months later.
    Using end_date made closed-registration contests look open. Fall back to
    end_date only when the registration window is missing."""
    if not isinstance(item, dict):
        return None
    reqs = item.get("regnRequirements")
    candidate = None
    if isinstance(reqs, dict):
        regn = _parse_iso_datetime(reqs.get("end_regn_dt"))
        if regn is not None:
            candidate = regn
    if candidate is None:
        candidate = _parse_iso_datetime(item.get("end_date"))
    return candidate if is_plausible_deadline(candidate) else None


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        return str(value).strip()
    except (TypeError, ValueError):
        return ""
