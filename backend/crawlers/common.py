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
import random
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import TypeVar

import httpx
from bs4 import BeautifulSoup

USER_AGENT = (
    "AspirovaBot/0.1 (+https://github.com/sohan1611/Aspirova; student project, contact via repo)"
)
MAX_DEADLINE_HORIZON = timedelta(days=550)
DEFAULT_HTTP_TIMEOUT_SECONDS = 15.0
DEFAULT_RETRY_BASE_DELAY_SECONDS = 2.0
DEFAULT_RETRY_MAX_DELAY_SECONDS = 60.0
DEFAULT_RETRY_JITTER_SECONDS = 0.5
RETRYABLE_HTTP_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
LIST_ITEM_START = "\ue000"
LIST_ITEM_END = "\ue001"
logger = logging.getLogger(__name__)

ItemT = TypeVar("ItemT")
ListingT = TypeVar("ListingT")


@dataclass(frozen=True)
class RetriedResponse:
    response: httpx.Response | None
    attempts_made: int
    terminal_reason: str | None = None
    retry_reasons: tuple[str, ...] = ()


def build_http_timeout(timeout: float = DEFAULT_HTTP_TIMEOUT_SECONDS) -> httpx.Timeout:
    return httpx.Timeout(
        connect=timeout,
        read=timeout,
        write=timeout,
        pool=timeout,
    )


def request_with_retries(
    request_once: Callable[[], httpx.Response],
    *,
    max_retries: int,
    sleeper: Callable[[float], None],
    base_delay_seconds: float = DEFAULT_RETRY_BASE_DELAY_SECONDS,
    max_delay_seconds: float = DEFAULT_RETRY_MAX_DELAY_SECONDS,
    jitter_seconds: float = DEFAULT_RETRY_JITTER_SECONDS,
    now: Callable[[], datetime] | None = None,
) -> RetriedResponse:
    """Run one HTTP request with bounded transient retry handling.

    Retry-After is source policy, so it wins over local backoff. Without it,
    retries use exponential delay plus small additive jitter to avoid a fixed
    retry cadence from shared CI runner IPs.
    """
    attempts_made = 0
    retry_reasons: list[str] = []
    max_attempts = max(max_retries, 0) + 1

    while attempts_made < max_attempts:
        attempts_made += 1
        try:
            response = request_once()
        except httpx.RequestError:
            terminal_reason = "request_error"
            if attempts_made >= max_attempts:
                return RetriedResponse(
                    response=None,
                    attempts_made=attempts_made,
                    terminal_reason=terminal_reason,
                    retry_reasons=tuple(retry_reasons),
                )
            retry_reasons.append(terminal_reason)
            sleeper(
                _retry_delay_seconds(
                    None,
                    retry_number=attempts_made,
                    base_delay_seconds=base_delay_seconds,
                    max_delay_seconds=max_delay_seconds,
                    jitter_seconds=jitter_seconds,
                    now=now,
                )
            )
            continue

        if response.status_code not in RETRYABLE_HTTP_STATUS_CODES:
            return RetriedResponse(
                response=response,
                attempts_made=attempts_made,
                retry_reasons=tuple(retry_reasons),
            )

        terminal_reason = f"http_{response.status_code}"
        if attempts_made >= max_attempts:
            return RetriedResponse(
                response=response,
                attempts_made=attempts_made,
                terminal_reason=terminal_reason,
                retry_reasons=tuple(retry_reasons),
            )

        retry_reasons.append(terminal_reason)
        sleeper(
            _retry_delay_seconds(
                response,
                retry_number=attempts_made,
                base_delay_seconds=base_delay_seconds,
                max_delay_seconds=max_delay_seconds,
                jitter_seconds=jitter_seconds,
                now=now,
            )
        )

    return RetriedResponse(
        response=None,
        attempts_made=attempts_made,
        terminal_reason="request_error",
        retry_reasons=tuple(retry_reasons),
    )


def _retry_delay_seconds(
    response: httpx.Response | None,
    *,
    retry_number: int,
    base_delay_seconds: float,
    max_delay_seconds: float,
    jitter_seconds: float,
    now: Callable[[], datetime] | None,
) -> float:
    retry_after_seconds = _retry_after_seconds(response, now=now)
    if retry_after_seconds is not None:
        return retry_after_seconds

    exponential_delay = min(
        max_delay_seconds,
        base_delay_seconds * (2 ** max(retry_number - 1, 0)),
    )
    jitter = random.uniform(0.0, max(jitter_seconds, 0.0)) if jitter_seconds > 0 else 0.0
    return exponential_delay + jitter


def _retry_after_seconds(
    response: httpx.Response | None,
    *,
    now: Callable[[], datetime] | None,
) -> float | None:
    if response is None:
        return None

    retry_after = response.headers.get("Retry-After")
    if not retry_after:
        return None

    try:
        return max(float(retry_after), 0.0)
    except ValueError:
        pass

    try:
        retry_at = parsedate_to_datetime(retry_after)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=UTC)
    current_time = now() if now is not None else datetime.now(UTC)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=UTC)
    return max((retry_at - current_time).total_seconds(), 0.0)


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
