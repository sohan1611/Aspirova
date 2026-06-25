"""SourceAdapter contract — every crawl source plugs into this, and only this
(Doc 02 sec 3.3, Doc 04 sec 3). Adding a source = adding an adapter; the
ingestion pipeline never changes.
"""

from datetime import datetime
from typing import Iterable, Literal, Protocol

from pydantic import BaseModel


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
    location: str | None = None
    is_remote: bool | None = None
    category: str | None = None
    description_raw: str
    apply_url: str
    posted_at: datetime | None = None
    deadline: datetime | None = None
    deadline_confidence: Literal["explicit", "inferred", "unknown"] = "unknown"


class SourceAdapter(Protocol):
    """Every adapter implements this. requires_browser MUST be False unless a
    source genuinely needs JS rendering (Doc 04 sec 5) - check for an
    underlying JSON/XHR endpoint before ever setting it True."""

    source_slug: str
    requires_browser: bool

    def fetch(self) -> Iterable[RawListing]: ...

    def parse(self, raw: RawListing) -> NormalizedListing: ...

    def health(self) -> Literal["ok", "degraded", "broken"]: ...
