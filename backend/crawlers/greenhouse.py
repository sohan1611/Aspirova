"""Greenhouse ATS adapter - the first and primary source per the ATS-first
crawling strategy (Doc 04 sec 1). One adapter class, parameterized by board
token, covers every Greenhouse company (Doc 04 sec 11) - board tokens are
DATA (companies.ats_board_id), never hardcoded here.
"""

import hashlib
import html
import json
from datetime import datetime
from typing import Literal

import httpx
from bs4 import BeautifulSoup

from core.adapters import NormalizedListing, RawListing
from pipeline.normalize import classify_category

USER_AGENT = (
    "AspirovaBot/0.1 (+https://github.com/sohan1611/Aspirova; student project, contact via repo)"
)


def _extract_text(raw_html: str | None) -> str:
    """Greenhouse's `content` field is HTML where the tags themselves are
    HTML-entity-encoded (e.g. literal text "&lt;div&gt;", not a real "<div>").
    html.unescape() recovers the real markup first; it is a no-op for any
    board that does NOT double-encode, so this is safe unconditionally
    (verified against a real cloudflare.io job payload)."""
    if not raw_html:
        return ""
    unescaped = html.unescape(raw_html)
    return BeautifulSoup(unescaped, "html.parser").get_text(separator=" ", strip=True)


def _content_hash(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class GreenhouseAdapter:
    """SourceAdapter for one company's Greenhouse job board.
    Instantiate per company (Doc 04 sec 11): GreenhouseAdapter(board_token=..., company_name=...).
    """

    source_slug = "greenhouse"
    requires_browser = False

    def __init__(self, board_token: str, company_name: str, timeout: float = 15.0) -> None:
        self.board_token = board_token
        self.company_name = company_name
        self._client = httpx.Client(timeout=timeout, headers={"User-Agent": USER_AGENT})
        self._last_health: Literal["ok", "degraded", "broken"] = "ok"

    def fetch(self) -> list[RawListing]:
        url = f"https://boards-api.greenhouse.io/v1/boards/{self.board_token}/jobs?content=true"
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

        jobs = response.json().get("jobs", [])
        self._last_health = "ok"

        return [
            RawListing(
                source_slug=self.source_slug,
                external_id=str(job["id"]),
                source_url=job["absolute_url"],
                content_hash=_content_hash(job),
                raw_payload=job,
            )
            for job in jobs
        ]

    def parse(self, raw: RawListing) -> NormalizedListing:
        job = raw.raw_payload
        location_name = (job.get("location") or {}).get("name")
        description_raw = _extract_text(job.get("content"))
        title = job["title"]

        posted_at: datetime | None = None
        if job.get("updated_at"):
            posted_at = datetime.fromisoformat(job["updated_at"])

        return NormalizedListing(
            source_slug=self.source_slug,
            external_id=raw.external_id,
            source_url=raw.source_url,
            title=title,
            company_name=self.company_name,
            location=location_name,
            is_remote=bool(location_name and "remote" in location_name.lower()),
            category=classify_category(title),
            description_raw=description_raw,
            apply_url=job["absolute_url"],
            posted_at=posted_at,
            deadline=None,
            deadline_confidence="unknown",
        )

    def health(self) -> Literal["ok", "degraded", "broken"]:
        return self._last_health
