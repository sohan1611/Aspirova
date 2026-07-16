"""SmartRecruiters adapter with lazy per-posting detail retrieval.

``fetch()`` retrieves only the inexpensive paginated LIST endpoint. Its stable
list-field hashes drive the board change detection described in Doc 04 §6.
``parse()`` deliberately makes one DETAIL request per listing, so that cost is
paid only when a board changed. ``raw_payload`` therefore contains the cheap
LIST item rather than ``jobAd``; the description is captured into
``opportunities.description_raw`` during parsing and is not read downstream
from the raw payload. A failed detail request raises so an empty description is
never ingested and stranded behind the list-based content hash.
"""

from datetime import datetime
from typing import Any, Literal

import httpx

from core.adapters import NormalizedListing, RawListing
from crawlers.common import USER_AGENT
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
        postings = self._fetch_postings()
        if postings is None:
            return []

        listings: list[RawListing] = []
        for posting in postings:
            listings.append(
                RawListing(
                    source_slug=self.source_slug,
                    external_id=str(posting["id"]),
                    source_url=(posting.get("postingUrl") or posting.get("applyUrl") or ""),
                    raw_payload=posting,
                    content_hash=_content_hash(
                        {
                            "id": posting.get("id"),
                            "name": posting.get("name"),
                            "releasedDate": posting.get("releasedDate"),
                            "location": posting.get("location"),
                        }
                    ),
                )
            )

        return listings

    def parse(self, raw: RawListing) -> NormalizedListing:
        detail = self._fetch_detail(raw.external_id)
        if detail is None:
            raise RuntimeError(f"SmartRecruiters detail fetch failed for posting {raw.external_id}")

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

    def _fetch_postings(self) -> list[dict[str, Any]] | None:
        postings: list[dict[str, Any]] = []
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
                return postings

            for posting in content:
                if not isinstance(posting, dict):
                    continue
                posting_id = posting.get("id")
                if posting_id:
                    postings.append(posting)

            offset += limit
            total_found = payload.get("totalFound")
            if total_found is not None:
                try:
                    if offset >= int(total_found):
                        self._last_health = "ok"
                        return postings
                except (TypeError, ValueError):
                    self._last_health = "degraded"
                    return postings

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
