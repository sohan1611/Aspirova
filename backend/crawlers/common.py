"""Shared across every SourceAdapter (Doc 04 sec 3/11): one honest,
consistent bot identity, one canonical content-hashing scheme, and one
HTML-to-text extractor, so every source presents itself identically to the
sites it crawls and change-detection (Doc 04 sec 6) works the same way
everywhere.
"""

import hashlib
import html
import json
from datetime import UTC, datetime, timedelta

from bs4 import BeautifulSoup

USER_AGENT = (
    "AspirovaBot/0.1 (+https://github.com/sohan1611/Aspirova; student project, contact via repo)"
)
MAX_DEADLINE_HORIZON = timedelta(days=550)


def content_hash(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def extract_text(raw_html: str | None) -> str:
    """Strips HTML to plain text. html.unescape() first recovers markup a
    source may have HTML-entity-double-encoded (Greenhouse's `content`
    field does this - confirmed against a real cloudflare.io payload); it
    is a no-op for any source that does NOT double-encode, so this is safe
    unconditionally across every source that uses it."""
    if not raw_html:
        return ""
    unescaped = html.unescape(raw_html)
    return BeautifulSoup(unescaped, "html.parser").get_text(separator=" ", strip=True)


def is_plausible_deadline(dt: datetime | None) -> bool:
    if dt is None:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt <= datetime.now(UTC) + MAX_DEADLINE_HORIZON
