"""Devfolio aggregator adapter using its public hackathon API."""

from datetime import UTC, datetime
from time import sleep
from typing import Any, Literal

import httpx

from core.adapters import NormalizedListing, RawListing
from crawlers.common import (
    USER_AGENT,
    build_http_timeout,
    content_hash,
    extract_text,
    is_plausible_deadline,
    request_with_retries,
)
from crawlers.watchdog import beat as watchdog_beat

_API_URL = "https://api.devfolio.co/api/hackathons"
_BASE_APPLY_HOST = "devfolio.co"
_FILTERS = ("application_open", "upcoming")
_PAGE_SIZE = 30
_MAX_PAGES = 10
_MAX_RETRIES = 2
_REQUEST_DELAY_SECONDS = 1.0

HealthStatus = Literal["ok", "degraded", "broken"]


class DevfolioAdapter:
    """SourceAdapter for Devfolio's open and upcoming hackathon feed."""

    source_slug = "devfolio"
    requires_browser = False

    def __init__(self, timeout: float = 15.0) -> None:
        self._client = httpx.Client(
            timeout=build_http_timeout(timeout),
            headers={"User-Agent": USER_AGENT},
        )
        self._last_health: HealthStatus = "ok"
        self._declared_totals: dict[str, int] = {}
        self._fetched_by_filter: dict[str, int] = {}
        self._fully_paged_filters: set[str] = set()
        self._incomplete_filter_reasons: dict[str, str] = {}
        self._request_count = 0
        self._page_count = 0
        self._retry_count = 0
        self._retry_reasons: list[str] = []

    def fetch(self) -> list[RawListing]:
        listings: list[RawListing] = []
        seen_uuids: set[str] = set()
        degraded = False
        self._declared_totals = {}
        self._fetched_by_filter = {}
        self._fully_paged_filters = set()
        self._incomplete_filter_reasons = {}
        self._request_count = 0
        self._page_count = 0
        self._retry_count = 0
        self._retry_reasons = []

        for filter_name in _FILTERS:
            for page in range(1, _MAX_PAGES + 1):
                if self._page_count:
                    sleep(_REQUEST_DELAY_SECONDS)

                result = self._get_page(filter_name, page)
                self._request_count += result.attempts_made
                self._retry_count += max(result.attempts_made - 1, 0)
                self._retry_reasons.extend(result.retry_reasons)
                response = result.response
                if response is None:
                    self._mark_filter_incomplete(
                        filter_name,
                        result.terminal_reason or "request_error",
                    )
                    degraded = True
                    break

                if response.status_code in {404, 422}:
                    self._mark_filter_incomplete(filter_name, f"http_{response.status_code}")
                    self._last_health = "broken"
                    return listings
                if response.status_code != 200:
                    self._mark_filter_incomplete(
                        filter_name,
                        result.terminal_reason or f"http_{response.status_code}",
                    )
                    degraded = True
                    break

                self._page_count += 1
                watchdog_beat(f"devfolio:{filter_name}:page-{page}")

                try:
                    payload = response.json()
                except ValueError:
                    self._mark_filter_incomplete(filter_name, "invalid_json")
                    self._last_health = "broken"
                    return listings

                if not isinstance(payload, dict):
                    self._mark_filter_incomplete(filter_name, "non_object_payload")
                    self._last_health = "broken"
                    return listings

                records = payload.get("result")
                if not isinstance(records, list):
                    self._mark_filter_incomplete(filter_name, "missing_result")
                    self._last_health = "broken"
                    return listings

                declared_total = _declared_count(payload)
                if declared_total is not None:
                    self._declared_totals[filter_name] = declared_total
                self._fetched_by_filter[filter_name] = self._fetched_by_filter.get(
                    filter_name, 0
                ) + len(records)

                if not records:
                    self._fully_paged_filters.add(filter_name)
                    break

                for record in records:
                    try:
                        listing = self._build_raw_listing(record, seen_uuids)
                    except (KeyError, TypeError, ValueError, AttributeError):
                        degraded = True
                        continue
                    if listing is not None:
                        listings.append(listing)

                declared_pages = _declared_pages(payload)
                if (
                    (declared_pages is not None and page >= declared_pages)
                    or (declared_total is not None and page * _PAGE_SIZE >= declared_total)
                    or len(records) < _PAGE_SIZE
                ):
                    self._fully_paged_filters.add(filter_name)
                    break
            else:
                self._mark_filter_incomplete(filter_name, "page_cap")
                degraded = True

        self._last_health = "degraded" if degraded else "ok"
        return listings

    def parse(self, raw: RawListing) -> NormalizedListing:
        hackathon = raw.raw_payload
        title = extract_text(_as_text(hackathon.get("name")))
        tagline = extract_text(_as_text(hackathon.get("tagline")))
        description = extract_text(_as_text(hackathon.get("desc")))
        themes = _theme_names(hackathon.get("themes"))
        description_raw = " ".join(part for part in [tagline, description, *themes] if part)
        starts_at = _parse_datetime(hackathon.get("starts_at"))
        ends_at = _parse_datetime(hackathon.get("ends_at"))
        deadline = ends_at if is_plausible_deadline(ends_at) else None
        apply_url = _apply_url(hackathon) or raw.source_url
        source_country = _as_optional_text(hackathon.get("country"))
        source_city = _as_optional_text(hackathon.get("city"))
        source_state = _as_optional_text(hackathon.get("state"))
        source_location = _as_optional_text(hackathon.get("location"))

        return NormalizedListing(
            source_slug=self.source_slug,
            external_id=raw.external_id,
            source_url=raw.source_url,
            title=title,
            company_name="Devfolio",
            company_domain=None,
            location=_display_location(hackathon),
            is_remote=(
                hackathon.get("is_online") if isinstance(hackathon.get("is_online"), bool) else None
            ),
            category="hackathon",
            description_raw=description_raw,
            apply_url=apply_url,
            posted_at=None,
            deadline=deadline,
            meta={
                "platform": "devfolio",
                "attribution": "via Devfolio",
                "tagline": tagline or None,
                "status": hackathon.get("status"),
                "geo_state": source_state,
                "apply_mode": hackathon.get("apply_mode"),
                "team_min": hackathon.get("team_min"),
                "team_size": hackathon.get("team_size"),
                "participants_count": hackathon.get("participants_count"),
                "prizes": hackathon.get("prizes"),
                "themes": themes,
                "is_online": hackathon.get("is_online"),
                "is_university_hackathon": hackathon.get("is_university_hackathon"),
                "city": source_city,
                "country": source_country,
                "location": source_location,
                "timezone": hackathon.get("timezone"),
                "starts_at": _iso_or_none(starts_at),
                "ends_at": _iso_or_none(ends_at),
            },
            deadline_confidence="explicit" if deadline is not None else "unknown",
        )

    def health(self) -> HealthStatus:
        return self._last_health

    def coverage(self) -> dict[str, Any]:
        fully_paged_filters = [
            filter_name for filter_name in _FILTERS if filter_name in self._fully_paged_filters
        ]
        incomplete_filter_reasons = {
            filter_name: self._incomplete_filter_reasons.get(filter_name, "not_reached")
            for filter_name in _FILTERS
            if filter_name not in self._fully_paged_filters
        }
        filters = {
            filter_name: {
                "fetched": self._fetched_by_filter.get(filter_name, 0),
                "declared": self._declared_totals.get(filter_name),
            }
            for filter_name in _FILTERS
        }
        details: dict[str, Any] = {
            "filters": filters,
            "declared_totals_by_filter": dict(self._declared_totals),
            "fetched_by_filter": dict(self._fetched_by_filter),
            "fully_paged_filters": fully_paged_filters,
            "requests_made": self._request_count,
            "pages_completed": self._page_count,
        }
        if incomplete_filter_reasons:
            details["incomplete_filter_reasons"] = incomplete_filter_reasons
        if self._retry_count:
            details["retry_attempts"] = self._retry_count
            details["retry_reasons"] = self._retry_reasons

        return {
            "mode": "declared_filter_totals",
            "expected_total": None,
            "status": "complete" if len(fully_paged_filters) == len(_FILTERS) else "partial",
            "note": (
                "Devfolio filters overlap, so summed per-filter totals are not "
                "a valid distinct-listing denominator."
            ),
            "details": details,
        }

    def _build_raw_listing(
        self,
        record: Any,
        seen_uuids: set[str],
    ) -> RawListing | None:
        if not isinstance(record, dict):
            raise TypeError("hackathon is not an object")

        external_id = _as_text(record.get("uuid"))
        source_url = _apply_url(record)
        if not external_id or not source_url:
            raise KeyError("uuid/slug")
        if external_id in seen_uuids:
            return None

        seen_uuids.add(external_id)
        return RawListing(
            source_slug=self.source_slug,
            external_id=external_id,
            source_url=source_url,
            content_hash=content_hash(record),
            raw_payload=record,
        )

    def _get_page(self, filter_name: str, page: int):
        return request_with_retries(
            lambda: self._client.get(
                _API_URL,
                params={"filter": filter_name, "page": page, "limit": _PAGE_SIZE},
            ),
            max_retries=_MAX_RETRIES,
            sleeper=sleep,
        )

    def _mark_filter_incomplete(self, filter_name: str, reason: str) -> None:
        self._incomplete_filter_reasons.setdefault(filter_name, reason)


def _display_location(hackathon: dict[str, Any]) -> str | None:
    if hackathon.get("is_online") is True:
        return "Online"

    country = _as_optional_text(hackathon.get("country"))
    if country is None:
        return None

    return _join_location_parts(
        [
            _as_optional_text(hackathon.get("location")),
            _as_optional_text(hackathon.get("city")),
            _as_optional_text(hackathon.get("state")),
            country,
        ]
    )


def _join_location_parts(parts: list[str | None]) -> str | None:
    seen: set[str] = set()
    deduped: list[str] = []
    for part in parts:
        if part is None:
            continue
        lowered = part.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(part)
    return ", ".join(deduped) or None


def _theme_names(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []

    names: list[str] = []
    seen: set[str] = set()
    for theme in value:
        if not isinstance(theme, dict):
            continue
        name = extract_text(_as_text(theme.get("name")))
        lowered = name.lower()
        if name and lowered not in seen:
            seen.add(lowered)
            names.append(name)
    return names


def _apply_url(record: dict[str, Any]) -> str:
    slug = _as_text(record.get("slug"))
    if not slug:
        return ""
    return f"https://{slug}.{_BASE_APPLY_HOST}"


def _declared_count(payload: dict[str, Any]) -> int | None:
    return _non_negative_int(payload.get("count"))


def _declared_pages(payload: dict[str, Any]) -> int | None:
    return _non_negative_int(payload.get("pages"))


def _non_negative_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return None


def _parse_datetime(value: Any) -> datetime | None:
    text = _as_text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _iso_or_none(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _as_optional_text(value: Any) -> str | None:
    text = _as_text(value)
    return text or None


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        return str(value).strip()
    except (TypeError, ValueError):
        return ""
