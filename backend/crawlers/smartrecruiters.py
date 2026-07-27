from datetime import datetime
from typing import Any, Literal

import httpx

from core.adapters import NormalizedListing, RawListing
from crawlers.common import USER_AGENT
from crawlers.common import build_listings
from crawlers.common import content_hash as _content_hash
from crawlers.common import extract_text as _extract_text
from pipeline.normalize import classify_category

HealthStatus = Literal["ok", "degraded", "broken"]


class SmartRecruitersAdapter:
    source_slug = "smartrecruiters"
    requires_browser = False

    def __init__(
        self,
        board_token: str,
        company_name: str,
        timeout: float = 15.0,
    ) -> None:
        self.board_token = board_token
        self.company_name = company_name
        self._client = httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
        )
        self._last_health: HealthStatus = "ok"

    def health(self) -> HealthStatus:
        return self._last_health

    def fetch(self) -> list[RawListing]:
        posting_ids = self._fetch_posting_ids()
        if posting_ids is None:
            return []

        listings: list[RawListing] = []
        degraded = self._last_health == "degraded"

        for posting_id in posting_ids:
            detail = self._fetch_detail(posting_id)
            if detail is None:
                degraded = True
                continue

            detail_listings = build_listings(
                [detail],
                lambda detail: RawListing(
                    source_slug=self.source_slug,
                    external_id=str(detail.get("id", posting_id)),
                    source_url=detail.get("postingUrl") or detail["applyUrl"],
                    raw_payload=detail,
                    content_hash=_content_hash(detail),
                ),
                source_slug=self.source_slug,
            )
            if not detail_listings:
                degraded = True
                continue
            listings.extend(detail_listings)

        self._last_health = "degraded" if degraded else "ok"
        return listings

    def parse(self, raw: RawListing) -> NormalizedListing:
        detail = raw.raw_payload
        location = detail.get("location") or {}
        if not isinstance(location, dict):
            location = {}
        apply_url = detail.get("postingUrl") or detail.get("applyUrl") or raw.source_url

        return NormalizedListing(
            source_slug=self.source_slug,
            external_id=raw.external_id,
            source_url=raw.source_url,
            title=str(detail.get("name") or ""),
            company_name=self.company_name,
            location=_clean_location(location),
            description_raw=_extract_description(detail),
            apply_url=apply_url,
            posted_at=_parse_released_date(detail.get("releasedDate")),
            deadline=None,
            deadline_confidence="unknown",
            is_remote=location.get("remote") is True,
            category=classify_category(str(detail.get("name") or "")),
        )

    def _fetch_posting_ids(self) -> list[str] | None:
        posting_ids: list[str] = []
        offset = 0
        limit = 100

        while True:
            try:
                response = self._client.get(
                    f"https://api.smartrecruiters.com/v1/companies/" f"{self.board_token}/postings",
                    params={"limit": limit, "offset": offset},
                )
            except httpx.RequestError:
                self._last_health = "degraded"
                return None

            if response.status_code == 404:
                self._last_health = "broken"
                return None
            if response.status_code != 200:
                self._last_health = "degraded"
                return None

            try:
                payload = response.json()
            except ValueError:
                self._last_health = "degraded"
                return None

            if not isinstance(payload, dict):
                self._last_health = "degraded"
                return None

            content = payload.get("content") or []
            if not isinstance(content, list):
                self._last_health = "degraded"
                return None
            if not content:
                self._last_health = "ok"
                return posting_ids

            for posting in content:
                if not isinstance(posting, dict):
                    continue
                posting_id = posting.get("id")
                if posting_id:
                    posting_ids.append(str(posting_id))

            offset += limit
            total_found = payload.get("totalFound")
            if total_found is not None:
                try:
                    if offset >= int(total_found):
                        self._last_health = "ok"
                        return posting_ids
                except (TypeError, ValueError):
                    self._last_health = "degraded"
                    return posting_ids

    def _fetch_detail(self, posting_id: str) -> dict[str, Any] | None:
        try:
            response = self._client.get(
                f"https://api.smartrecruiters.com/v1/companies/"
                f"{self.board_token}/postings/{posting_id}",
            )
        except httpx.RequestError:
            return None

        if response.status_code != 200:
            return None

        try:
            detail = response.json()
        except ValueError:
            return None

        if not isinstance(detail, dict):
            return None
        return detail


def _extract_description(detail: dict[str, Any]) -> str:
    job_ad = detail.get("jobAd") or {}
    if not isinstance(job_ad, dict):
        return ""

    sections = job_ad.get("sections") or {}
    if not isinstance(sections, dict):
        return ""

    section_names = [
        "companyDescription",
        "jobDescription",
        "qualifications",
        "additionalInformation",
    ]
    texts: list[str] = []

    for section_name in section_names:
        section = sections.get(section_name) or {}
        if not isinstance(section, dict):
            continue
        text = _extract_text(section.get("text") or "").strip()
        if text:
            texts.append(text)

    return "\n\n".join(texts)


def _clean_location(location: dict[str, Any]) -> str:
    full_location = location.get("fullLocation")
    if full_location:
        parts = [part.strip() for part in str(full_location).split(",")]
    else:
        parts = [str(location.get(key) or "").strip() for key in ("city", "region", "country")]

    return ", ".join(part for part in parts if part)


def _parse_released_date(value: Any) -> datetime | None:
    if not value:
        return None

    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
