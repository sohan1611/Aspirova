"""Shared across every SourceAdapter (Doc 04 sec 3/11): one honest,
consistent bot identity, one canonical content-hashing scheme, and one
HTML-to-text extractor, so every source presents itself identically to the
sites it crawls and change-detection (Doc 04 sec 6) works the same way
everywhere.
"""

import hashlib
import html
import json
import logging
import re
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from typing import TypeVar

from bs4 import BeautifulSoup

USER_AGENT = (
    "AspirovaBot/0.1 (+https://github.com/sohan1611/Aspirova; student project, contact via repo)"
)
MAX_DEADLINE_HORIZON = timedelta(days=550)
LIST_ITEM_START = "\ue000"
LIST_ITEM_END = "\ue001"
logger = logging.getLogger(__name__)

ItemT = TypeVar("ItemT")
ListingT = TypeVar("ListingT")


def content_hash(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_listings(
    items: Iterable[ItemT],
    build_one: Callable[[ItemT], ListingT],
    *,
    source_slug: str,
) -> list[ListingT]:
    listings: list[ListingT] = []
    for item in items:
        try:
            listings.append(build_one(item))
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            logger.warning("skipping malformed %s listing: %s", source_slug, exc)
    return listings


def extract_text(raw_html: str | None) -> str:
    """Strips HTML to plain text. html.unescape() first recovers markup a
    source may have HTML-entity-double-encoded (Greenhouse's `content`
    field does this - confirmed against a real cloudflare.io payload); it
    is a no-op for any source that does NOT double-encode, so this is safe
    unconditionally across every source that uses it."""
    if not raw_html:
        return ""
    unescaped = html.unescape(raw_html)
    soup = BeautifulSoup(unescaped, "html.parser")

    for tag in soup.find_all("br"):
        tag.replace_with("\n")
    list_items = soup.find_all("li")
    for tag in list_items:
        tag.insert(0, f"{LIST_ITEM_START}- ")
        tag.append(LIST_ITEM_END)
    block_tags = [
        "p",
        "div",
        "section",
        "article",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "tr",
    ]
    for tag in soup.find_all(block_tags):
        tag.append("\n")

    text = soup.get_text()
    if list_items:
        text = re.sub(
            rf"\s*{re.escape(LIST_ITEM_END)}\s*{re.escape(LIST_ITEM_START)}",
            "\n",
            text,
        )
        text = text.replace(LIST_ITEM_START, "").replace(LIST_ITEM_END, "\n")
    text = re.sub(r"(?:\r?\n){3,}", "\n\n", text)
    return "\n".join(line.rstrip() for line in text.splitlines()).strip()


def is_plausible_deadline(dt: datetime | None) -> bool:
    if dt is None:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt <= datetime.now(UTC) + MAX_DEADLINE_HORIZON
