"""Unstop aggregator adapter using its public opportunity search API."""

from datetime import UTC, datetime, timedelta
from time import monotonic, sleep
from typing import Any, Callable, Literal

import httpx

from core.adapters import NormalizedListing, RawListing
from core.eligibility import ELIGIBLE_EXPERIENCED_ONLY_META_KEY, is_eligible_experienced_only
from crawlers.common import (
    RetriedResponse,
    USER_AGENT,
    build_http_timeout,
    build_listings,
    content_hash,
    extract_text,
    is_plausible_deadline,
    request_with_retries,
)

_API_URL = "https://unstop.com/api/public/opportunity/search-result"
_OPPORTUNITY_TYPES = ("internships", "competitions", "hackathons", "jobs")
_PAGE_SIZE = 300
_MAX_PAGES = 8
_MAX_RETRIES = 2

HealthStatus = Literal["ok", "degraded", "broken"]


class UnstopAdapter:
    """SourceAdapter for Unstop's multi-organizer opportunity feed."""

    source_slug = "unstop"
    requires_browser = False

    def __init__(self, timeout: float = 15.0) -> None:
        self._client = httpx.Client(
            timeout=build_http_timeout(timeout),
            headers={"User-Agent": USER_AGENT},
        )
        self._last_health: HealthStatus = "ok"
        self._stopped_early = False
        self._declared_totals: dict[str, int] = {}
        self._fully_paged_types: set[str] = set()
        self._incomplete_type_reasons: dict[str, str] = {}
        self._request_count = 0
        self._retry_count = 0
        self._retry_reasons: list[str] = []

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
        self._declared_totals = {}
        self._fully_paged_types = set()
        self._incomplete_type_reasons = {}
        self._request_count = 0
        self._retry_count = 0
        self._retry_reasons = []

        for opportunity_type in _OPPORTUNITY_TYPES:
            for page in range(1, _MAX_PAGES + 1):
                if _should_stop(deadline_monotonic, should_stop):
                    self._stopped_early = True
                    self._mark_type_incomplete(opportunity_type, "stopped_early")
                    # Health is normally applied after the type loop, which this
                    # early return skips. A type that already failed must not be
                    # reported healthy just because a LATER type then ran out of
                    # budget - unstop hits stopped_early on most runs, so that
                    # would quietly hide real degradation.
                    self._last_health = "degraded" if degraded else "ok"
                    return listings

                result = self._get_page(opportunity_type, page)
                self._request_count += result.attempts_made
                self._retry_count += max(result.attempts_made - 1, 0)
                self._retry_reasons.extend(result.retry_reasons)
                response = result.response
                if response is None:
                    self._mark_type_incomplete(
                        opportunity_type,
                        result.terminal_reason or "request_error",
                    )
                    degraded = True
                    break

                if _should_stop(deadline_monotonic, should_stop):
                    self._stopped_early = True
                    self._mark_type_incomplete(opportunity_type, "stopped_early")
                    # Health is normally applied after the type loop, which this
                    # early return skips. A type that already failed must not be
                    # reported healthy just because a LATER type then ran out of
                    # budget - unstop hits stopped_early on most runs, so that
                    # would quietly hide real degradation.
                    self._last_health = "degraded" if degraded else "ok"
                    return listings

                if response.status_code == 404:
                    self._mark_type_incomplete(opportunity_type, "http_404")
                    self._last_health = "broken"
                    return listings
                if response.status_code != 200:
                    self._mark_type_incomplete(
                        opportunity_type,
                        result.terminal_reason or f"http_{response.status_code}",
                    )
                    degraded = True
                    break

                try:
                    payload = response.json()
                except ValueError:
                    self._mark_type_incomplete(opportunity_type, "invalid_json")
                    degraded = True
                    break

                items = _opportunity_items(payload)
                if items is None:
                    self._mark_type_incomplete(opportunity_type, "missing_items")
                    degraded = True
                    break
                declared_total = _declared_total(payload)
                if declared_total is not None:
                    self._declared_totals[opportunity_type] = declared_total
                if not items:
                    self._fully_paged_types.add(opportunity_type)
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

                if len(items) < _PAGE_SIZE or (
                    declared_total is not None and page * _PAGE_SIZE >= declared_total
                ):
                    self._fully_paged_types.add(opportunity_type)
                    break
            else:
                self._mark_type_incomplete(opportunity_type, "page_cap")

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
        elif search_opportunity == "jobs":
            category = "job"
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

        meta: dict[str, Any] = {
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
        }
        filters_meta = _filters_meta(opportunity.get("filters"))
        if filters_meta:
            meta.update(filters_meta)

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
            meta=meta,
            deadline_confidence="explicit" if deadline is not None else "unknown",
        )

    def health(self) -> HealthStatus:
        return self._last_health

    def coverage(self) -> dict[str, Any]:
        declared_totals = getattr(self, "_declared_totals", {})
        fully_paged_type_set = getattr(self, "_fully_paged_types", set())
        incomplete_reasons = getattr(self, "_incomplete_type_reasons", {})
        fully_paged_types = [
            opportunity_type
            for opportunity_type in _OPPORTUNITY_TYPES
            if opportunity_type in fully_paged_type_set
        ]
        incomplete_type_reasons = {
            opportunity_type: incomplete_reasons.get(opportunity_type, "not_reached")
            for opportunity_type in _OPPORTUNITY_TYPES
            if opportunity_type not in fully_paged_type_set
        }
        missing_declared_totals = [
            opportunity_type
            for opportunity_type in _OPPORTUNITY_TYPES
            if opportunity_type not in declared_totals
        ]
        details: dict[str, Any] = {
            "declared_totals_by_type": dict(declared_totals),
            "fully_paged_types": fully_paged_types,
        }
        if incomplete_type_reasons:
            details["incomplete_type_reasons"] = incomplete_type_reasons
        if missing_declared_totals:
            details["missing_declared_totals"] = missing_declared_totals
        details["requests_made"] = getattr(self, "_request_count", 0)
        if getattr(self, "_retry_count", 0):
            details["retry_attempts"] = self._retry_count
            details["retry_reasons"] = self._retry_reasons

        return {
            "mode": "declared_type_totals",
            "expected_total": None,
            "status": (
                "complete" if len(fully_paged_types) == len(_OPPORTUNITY_TYPES) else "partial"
            ),
            "note": (
                "Unstop opportunity types overlap, so summed per-type totals "
                "are not a valid distinct-listing denominator."
            ),
            "details": details,
        }

    def _mark_type_incomplete(self, opportunity_type: str, reason: str) -> None:
        self._incomplete_type_reasons.setdefault(opportunity_type, reason)

    def _get_page(self, opportunity_type: str, page: int) -> RetriedResponse:
        return request_with_retries(
            lambda: self._client.get(
                _API_URL,
                params={
                    "opportunity": opportunity_type,
                    "oppstatus": "open",
                    "per_page": _PAGE_SIZE,
                    "page": page,
                },
            ),
            max_retries=_MAX_RETRIES,
            sleeper=sleep,
        )


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


def _declared_total(payload: Any) -> int | None:
    containers: list[Any] = [payload]
    if isinstance(payload, dict):
        for key in ("data", "meta", "pagination"):
            nested = payload.get(key)
            if isinstance(nested, dict):
                containers.append(nested)

    for container in containers:
        if not isinstance(container, dict):
            continue
        for key in ("total", "total_count", "totalCount", "recordsTotal"):
            value = container.get(key)
            if value is None:
                continue
            try:
                return max(int(value), 0)
            except (TypeError, ValueError):
                return None
    return None


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


def _filters_meta(filters: Any) -> dict[str, Any]:
    if not isinstance(filters, list) or not filters:
        return {}

    eligibility = _filter_names(filters, "eligible")
    categories = _filter_names(filters, "category")
    return {
        "eligibility": eligibility,
        ELIGIBLE_EXPERIENCED_ONLY_META_KEY: is_eligible_experienced_only(eligibility),
        "categories": categories,
    }


def _filter_names(filters: list[Any], filter_type: str) -> list[str]:
    names: list[str] = []
    for filter_item in filters:
        if not isinstance(filter_item, dict) or filter_item.get("type") != filter_type:
            continue
        name = filter_item.get("name")
        if isinstance(name, str) and name:
            names.append(name)
    return names


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        return str(value).strip()
    except (TypeError, ValueError):
        return ""
