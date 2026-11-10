"""SourceAdapter contract — every crawl source plugs into this, and only this
(Doc 02 sec 3.3, Doc 04 sec 3). Adding a source = adding an adapter; the
ingestion pipeline never changes.
"""

from datetime import datetime
from typing import Iterable, Literal, Protocol

from pydantic import BaseModel, model_validator

from core.domains import http_url


class RawListing(BaseModel):
    """Exactly what we fetched from a source, before any interpretation."""

    source_slug: str
    external_id: str | None
    source_url: str
    content_hash: str
    raw_payload: dict


class NormalizedListing(BaseModel):
    """What an adapter extracts from a RawListing. Becomes a canonical
    Opportunity only after dedup (Doc 04 sec 9) - this is pre-dedup."""

    source_slug: str
    external_id: str | None
    source_url: str
    title: str
    company_name: str
    company_domain: str | None = None
    company_logo_url: str | None = None
    location: str | None = None
    country: str | None = None
    is_remote: bool | None = None
    category: str | None = None
    description_raw: str
    apply_url: str
    posted_at: datetime | None = None
    deadline: datetime | None = None
    meta: dict | None = None
    deadline_confidence: Literal["explicit", "inferred", "unknown"] = "unknown"

    @model_validator(mode="after")
    def _apply_url_is_a_web_link(self) -> "NormalizedListing":
        """Only an absolute http(s) Apply link may reach the site (SEC-03).

        A `javascript:`, `data:`, relative or malformed apply_url falls back to
        the listing's own source page when that one is a real web link. The
        listing is still ingested, so no crawl batch is rolled back and a
        full-inventory source does not read the listing as absent.
        """
        if http_url(self.apply_url) is None and http_url(self.source_url) is not None:
            self.apply_url = self.source_url
        return self


class SourceAdapter(Protocol):
    """Every adapter implements this. requires_browser MUST be False unless a
    source genuinely needs JS rendering (Doc 04 sec 5) - check for an
    underlying JSON/XHR endpoint before ever setting it True."""

    source_slug: str
    requires_browser: bool

    def fetch(self) -> Iterable[RawListing]: ...

    def parse(self, raw: RawListing) -> NormalizedListing: ...

    def health(self) -> Literal["ok", "degraded", "broken"]: ...
