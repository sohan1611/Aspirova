"""Ashby ATS adapter (Doc handoffs/PHASE-2-HANDOFF.md sec 5, Part 2.5) -
the third ATS source per the ATS-first crawling strategy (Doc 04 sec 1).
Same shape as GreenhouseAdapter/LeverAdapter (Doc 04 sec 11): the
ingestion pipeline never changes, only the adapter.

Ashby's public JSON endpoint
(`api.ashbyhq.com/posting-api/job-board/{token}`) is the cleanest of the
three sources so far: plain-text description AND a direct `isRemote`
boolean, no location-string heuristics needed to infer it (contrast
crawlers/greenhouse.py's substring-matching fallback).
"""

from datetime import datetime
from typing import Literal

import httpx

from core.adapters import NormalizedListing, RawListing
from crawlers.common import USER_AGENT, content_hash
from pipeline.normalize import classify_category


class AshbyAdapter:
    """SourceAdapter for one company's Ashby job board.
    Instantiate per company: AshbyAdapter(board_token=..., company_name=...).
    """

    source_slug = "ashby"
    requires_browser = False

    def __init__(self, board_token: str, company_name: str, timeout: float = 15.0) -> None:
        self.board_token = board_token
        self.company_name = company_name
        self._client = httpx.Client(timeout=timeout, headers={"User-Agent": USER_AGENT})
        self._last_health: Literal["ok", "degraded", "broken"] = "ok"

    def fetch(self) -> list[RawListing]:
        url = f"https://api.ashbyhq.com/posting-api/job-board/{self.board_token}"
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
                external_id=job["id"],
                source_url=job["jobUrl"],
                content_hash=content_hash(job),
                raw_payload=job,
            )
            for job in jobs
        ]

    def parse(self, raw: RawListing) -> NormalizedListing:
        job = raw.raw_payload
        title = job["title"]

        posted_at: datetime | None = None
        if job.get("publishedAt"):
            posted_at = datetime.fromisoformat(job["publishedAt"])

        return NormalizedListing(
            source_slug=self.source_slug,
            external_id=raw.external_id,
            source_url=raw.source_url,
            title=title,
            company_name=self.company_name,
            location=job.get("location"),
            is_remote=job.get("isRemote"),
            category=classify_category(title),
            description_raw=job.get("descriptionPlain") or "",
            apply_url=job["jobUrl"],
            posted_at=posted_at,
            deadline=None,
            deadline_confidence="unknown",
        )

    def health(self) -> Literal["ok", "degraded", "broken"]:
        return self._last_health
