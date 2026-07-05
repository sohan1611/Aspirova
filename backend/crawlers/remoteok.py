"""RemoteOK aggregator adapter - the first best-effort aggregator (Doc 04
sec 1: aggregators are a secondary, best-effort tier, never the
foundation; Doc handoffs/PHASE-2-HANDOFF.md sec 2/5, Part 2.5).

Chosen deliberately over the aggregators Doc 04 already named as
off-limits (Internshala, Unstop, Wellfound, LinkedIn all forbid scraping
in their ToS and actively block bots): RemoteOK publishes a genuinely
public JSON API intended for third-party reuse, confirmed by inspecting
its own robots.txt (`User-agent: *` / `Allow: /` with a `Crawl-delay: 1` -
the only named disallows are AI-training/SEO-scraping bots, not general
search-style crawling) and the API response's own embedded legal notice,
which explicitly REQUESTS attribution + a followed link back, not a ban on
reuse. This crawler honors both: an honest, identifiable User-Agent
(crawlers/common.py), and every listing links out to RemoteOK's own hosted
page (`url`/`apply_url` in the payload) - never mirrored - which is both
Doc 01 R1's standing rule and literally what RemoteOK's API terms ask for.

Unlike the ATS adapters (Greenhouse/Lever/Ashby - one board, one company,
resolved at seed time), one RemoteOK fetch spans many different companies
whose only identity signal is a free-text name - see
pipeline/company_resolution.py and crawlers/runner.py's crawl_aggregator,
which resolves/creates the Company row per listing rather than assuming
one fixed company_id for the whole batch.
"""

from datetime import datetime
from typing import Literal

import httpx

from core.adapters import NormalizedListing, RawListing
from crawlers.common import USER_AGENT, content_hash, extract_text
from pipeline.normalize import classify_category


class RemoteOkAdapter:
    """SourceAdapter for the RemoteOK aggregator. Not company-scoped - no
    board_token, unlike the ATS adapters."""

    source_slug = "remoteok"
    requires_browser = False

    def __init__(self, timeout: float = 15.0) -> None:
        self._client = httpx.Client(timeout=timeout, headers={"User-Agent": USER_AGENT})
        self._last_health: Literal["ok", "degraded", "broken"] = "ok"

    def fetch(self) -> list[RawListing]:
        try:
            response = self._client.get("https://remoteok.com/api")
        except httpx.RequestError:
            self._last_health = "degraded"
            return []

        if response.status_code == 404:
            self._last_health = "broken"
            return []
        if response.status_code != 200:
            self._last_health = "degraded"
            return []

        payload = response.json()
        self._last_health = "ok"

        # payload[0] is RemoteOK's own legal/API-terms notice, not a job -
        # every real posting has an "id"; the notice does not.
        jobs = [job for job in payload if isinstance(job, dict) and "id" in job]

        return [
            RawListing(
                source_slug=self.source_slug,
                external_id=str(job["id"]),
                source_url=job.get("url") or job["apply_url"],
                content_hash=content_hash(job),
                raw_payload=job,
            )
            for job in jobs
        ]

    def parse(self, raw: RawListing) -> NormalizedListing:
        job = raw.raw_payload
        title = extract_text(job["position"])
        company_name = extract_text(job["company"])
        description_raw = extract_text(job.get("description"))

        posted_at: datetime | None = None
        if job.get("date"):
            posted_at = datetime.fromisoformat(job["date"])

        return NormalizedListing(
            source_slug=self.source_slug,
            external_id=raw.external_id,
            source_url=raw.source_url,
            title=title,
            company_name=company_name,
            location=job.get("location") or None,
            # RemoteOK lists only remote roles by definition - there is no
            # separate remote/onsite field to read, unlike Ashby's isRemote
            # or Greenhouse/Lever's location-string heuristics.
            is_remote=True,
            category=classify_category(title),
            description_raw=description_raw,
            apply_url=raw.source_url,
            posted_at=posted_at,
            deadline=None,
            deadline_confidence="unknown",
        )

    def health(self) -> Literal["ok", "degraded", "broken"]:
        return self._last_health
