"""Small shared boundary for the five public government notice adapters.

Only metadata is ingested. Date-only cutoffs mean 23:59:59 IST; date-only
publication dates mean midnight IST. Original strings remain in each payload.
"""

import re
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from time import monotonic, sleep
from typing import Any, Literal
from urllib.parse import urljoin, urlsplit

import httpx

from core.adapters import NormalizedListing, RawListing
from crawlers.common import (
    USER_AGENT,
    build_http_timeout,
    build_listings,
    content_hash,
    extract_text,
    is_plausible_deadline,
    request_with_retries,
)
from crawlers.robots import RobotsCache
from crawlers.student_relevance import classify_student_role, is_student_relevant_role

IST = timezone(timedelta(hours=5, minutes=30))
DATE_PATTERN = (
    r"(?:\d{1,2}[./-]\d{1,2}[./-]\d{4}|"
    r"\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+,?\s+\d{4}|"
    r"[A-Za-z]+\s+\d{1,2}(?:st|nd|rd|th)?,?\s*\d{4})"
)
_EXCLUDED = re.compile(
    r"\b(?:deputation|consultants?|directors?|head|retired|results?|answer[- ]?keys?|"
    r"admit[- ]?cards?|corrigendum|cancell?ation|cancell?ed|testimonials?|"
    r"(?:provisionally\s+)?selected\s+(?:list|candidates)|short[- ]?listed)\b",
    re.I,
)
_RESEARCH = re.compile(
    r"\b(?:(?:junior|senior|project)\s+research\s+fellow(?:ship)?s?|"
    r"research\s+(?:fellow(?:ship)?s?|associates?)|project\s+fellows?|JRF|SRF)\b",
    re.I,
)
_GOV_ENTRY = re.compile(
    r"\b(?:young\s+professionals?|scientists?\s*/?\s*engineers?\s*[-–'‘’\"( ]*SC|"
    r"technician\s*[-–]?\s*[AB]|(?:technical|scientific)\s+assistants?|STA-B|"
    r"junior\s+(?:personal\s+)?assistants?|assistants?)\b",
    re.I,
)
_GOV_INTERNS = re.compile(
    r"\b(?:interns?|internships?|apprentices?|apprenticeships?|trainees?)\b", re.I
)


def student_notice(title: str, role_label: str = "") -> bool:
    """Shared senior boundary, with explicit government research/entry signals.

    Research fellow is a student role here, although the general feed's bare
    'fellow' senior pattern also describes senior corporate appointments.
    """
    if _EXCLUDED.search(title) or _EXCLUDED.search(role_label):
        return False
    signal = f"{title} {role_label}".strip()
    scrubbed = _RESEARCH.sub("graduate", signal)
    scrubbed = re.sub(r"\bstaff\s+car\s+driver\b", "car driver", scrubbed, flags=re.I)
    scrubbed = _GOV_INTERNS.sub("intern", scrubbed)
    return is_student_relevant_role(scrubbed, "entry" if _GOV_ENTRY.search(signal) else "")


def notice_category(title: str) -> str:
    if _GOV_INTERNS.search(title):
        return "internship"
    return "job" if _RESEARCH.search(title) else classify_student_role(title)


def parse_date(value: str | None, *, end: bool = False) -> datetime | None:
    if not value or not value.strip():
        return None
    cleaned = re.sub(r"(?<=\d)(st|nd|rd|th)\b", "", value.strip(), flags=re.I)
    cleaned = re.sub(r"\bSept\b", "Sep", cleaned, flags=re.I)
    cleaned = re.sub(r"\s+", " ", cleaned.replace(",", " ")).strip()
    for fmt in (
        "%d/%m/%Y",
        "%d.%m.%Y",
        "%d-%m-%Y",
        "%d %B %Y",
        "%d %b %Y",
        "%B %d %Y",
        "%b %d %Y",
        "%Y-%m-%d",
    ):
        try:
            date = datetime.strptime(cleaned, fmt).replace(tzinfo=IST)
            return date.replace(hour=23, minute=59, second=59) if end else date
        except ValueError:
            continue
    raise ValueError(f"unrecognised government date: {value!r}")


def application_dates(text: str) -> list[str]:
    return re.findall(
        rf"(?:last\s+date|due\s+date|closing\s+date|deadline)[^.;\n]{{0,100}}?"
        rf"({DATE_PATTERN})",
        text,
        re.I,
    )


def official_url(value: str, base: str) -> str:
    url = urljoin(base, value)
    parts = urlsplit(url)
    host = parts.hostname or ""
    base_host = urlsplit(base).hostname
    if (
        parts.scheme not in {"http", "https"}
        or parts.username
        or parts.password
        or not (host == base_host or host.endswith((".gov.in", ".nic.in")))
    ):
        raise ValueError("not an official public notice URL")
    return url


class Node:
    """Minimal HTML tree using only the stdlib parser (no CSS engine)."""

    def __init__(self, tag: str, attrs: dict[str, str] | None = None) -> None:
        self.tag = tag
        self.attrs = attrs or {}
        self.children: list[Node | str] = []

    def has_class(self, value: str) -> bool:
        return value in self.attrs.get("class", "").split()

    def nodes(self, tag: str = "", cls: str = "") -> Iterator["Node"]:
        for child in self.children:
            if isinstance(child, Node):
                if (not tag or child.tag == tag) and (not cls or child.has_class(cls)):
                    yield child
                yield from child.nodes(tag, cls)

    def one(self, tag: str = "", cls: str = "") -> "Node":
        return next(self.nodes(tag, cls), Node("missing"))

    def text(self) -> str:
        def parts(node: Node) -> str:
            if node.tag in {"script", "style"}:
                return ""
            return "".join(c if isinstance(c, str) else parts(c) for c in node.children)

        return re.sub(r"\s+", " ", parts(self)).strip()


class _Tree(HTMLParser):
    def __init__(self, html: str) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("document")
        self.stack = [self.root]
        self.feed(html)
        self.close()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = Node(tag, {k: v or "" for k, v in attrs})
        self.stack[-1].children.append(node)
        if tag not in {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        }:
            self.stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data)


def html_tree(html: str) -> Node:
    if "</html>" not in html.lower():
        raise ValueError("truncated HTML document")
    root = _Tree(html).root
    title = root.one("title").text()
    if re.search(
        r"captcha|access denied|attention required|error|service unavailable", title, re.I
    ):
        raise ValueError("challenge/error document")
    if re.search(r"verify you are human|cf-chl-|request could not be satisfied", html, re.I):
        raise ValueError("challenge document")
    return root


class RobotsDenied(ValueError):
    pass


class GovernmentAdapter:
    requires_browser = False
    source_slug: str

    def __init__(self, timeout: float = 15.0, *, now: Callable[[], datetime] | None = None) -> None:
        self._client = httpx.Client(
            timeout=build_http_timeout(timeout), headers={"User-Agent": USER_AGENT}
        )
        self._now = now or (lambda: datetime.now(IST))
        self._last_health: Literal["ok", "degraded", "broken"] = "degraded"
        self._counts: dict[str, int] = {}
        self._error: str | None = None
        self._expected: int | None = None
        self._last_request: dict[str, float] = {}
        self._robots = RobotsCache(self._request)

    def _request(self, url: str) -> httpx.Response:
        def once() -> httpx.Response:
            host = urlsplit(url).netloc
            delay = self._robots.delay(url)
            remaining = delay - (monotonic() - self._last_request.get(host, -delay))
            if remaining > 0:
                sleep(remaining)
            self._last_request[host] = monotonic()
            return self._client.get(url)

        fetched = request_with_retries(once, max_retries=1, sleeper=sleep)
        if fetched.response is None:
            raise httpx.RequestError(fetched.terminal_reason or "request failed")
        return fetched.response

    def get(self, url: str) -> httpx.Response:
        for _ in range(6):
            if not self._robots.allowed(url):
                raise RobotsDenied(f"robots disallowed/unreachable: {url}")
            response = self._request(url)
            if response.status_code in {301, 302, 303, 307, 308}:
                target = urljoin(url, response.headers.get("Location", ""))
                url = official_url(target, url)
                continue
            if response.status_code != 200:
                raise ValueError(f"HTTP {response.status_code}: {url}")
            return response
        raise ValueError("too many redirects")

    def collect(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    def fetch(self) -> list[RawListing]:
        self._robots = RobotsCache(self._request)
        self._expected = None
        self._error = None
        self._counts = {
            "raw_count": 0,
            "skipped_irrelevant": 0,
            "skipped_closed": 0,
            "duplicates": 0,
            "student_relevant_count": 0,
        }
        try:
            records = self.collect()
            self._counts["raw_count"] = len(records)
            kept = []
            for record in records:
                if not student_notice(record["title"], record.get("role_label", "")):
                    self._counts["skipped_irrelevant"] += 1
                    continue
                kept.append(record)
            listings = build_listings(kept, self._raw, source_slug=self.source_slug)
            if len(listings) != len(kept):
                raise ValueError("malformed notice")
            self._counts["student_relevant_count"] = len(listings)
            self._last_health = "ok"
            return listings
        except (httpx.RequestError, ValueError, KeyError, TypeError, AttributeError) as exc:
            self._error = str(exc)
            self._last_health = "broken" if isinstance(exc, RobotsDenied) else "degraded"
            return []

    def _raw(self, record: dict[str, Any]) -> RawListing:
        if not record["external_id"] or not record["title"].strip():
            raise ValueError("missing notice identity/title")
        url = record["url"]
        return RawListing(
            source_slug=self.source_slug,
            external_id=record["external_id"],
            source_url=url,
            content_hash=content_hash(record),
            raw_payload=record,
        )

    def parse(self, raw: RawListing) -> NormalizedListing:
        record = raw.raw_payload
        deadline = datetime.fromisoformat(record["deadline"]) if record.get("deadline") else None
        if deadline is not None and not is_plausible_deadline(deadline):
            deadline = None
        return NormalizedListing(
            source_slug=self.source_slug,
            external_id=raw.external_id,
            source_url=raw.source_url,
            title=record["title"],
            company_name=record["company"],
            country="IN",
            location=record.get("location"),
            category=notice_category(record["title"]),
            description_raw=extract_text(record.get("description") or record["title"]),
            apply_url=raw.source_url,
            posted_at=(
                datetime.fromisoformat(record["posted_at"]) if record.get("posted_at") else None
            ),
            deadline=deadline,
            deadline_confidence=record.get("confidence", "unknown") if deadline else "unknown",
            meta={
                "summary_source": "extracted",
                "original_title": record["title"],
                "date_only_deadline_assumption": "23:59:59 Asia/Kolkata",
                **record.get("meta", {}),
            },
        )

    def health(self) -> Literal["ok", "degraded", "broken"]:
        return self._last_health

    def filter_counts(self) -> dict[str, int]:
        return dict(self._counts)

    def coverage(self) -> dict[str, Any]:
        return {
            "mode": "government_notices",
            "status": "complete" if self.health() == "ok" else "partial",
            "expected_total": self._expected,
            "note": "Board traversal only; absence is never evidence of closure.",
            "details": {**self._counts, "error": self._error},
        }


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
