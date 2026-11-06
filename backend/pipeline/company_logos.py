"""Deterministic company-domain discovery with an injected HTTP boundary."""

import json
import re
import time
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol
from urllib.parse import quote, urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

from core.domains import clean_domain, http_url, same_site
from pipeline.normalize import company_key

MAX_BODY_BYTES = 1_048_576
USER_AGENT = "AspirovaBot/1.0 (+https://www.aspirova.org)"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
CLEARBIT_API = "https://autocomplete.clearbit.com/v1/companies/suggest"
SIGNAL_WEIGHTS = {"wikidata": 2, "listing": 2, "clearbit": 1, "title": 1}
STRONG_PARKED_MARKERS = (
    "domain is for sale",
    "buy this domain",
    "this domain may be for sale",
    "domain for sale",
    "sedo",
    "afternic",
    "hugedomains",
    "dan.com",
)
WEAK_PARKED_MARKERS = ("parked", "godaddy", "coming soon")
PARKED_MARKERS = STRONG_PARKED_MARKERS + WEAK_PARKED_MARKERS
_STRONG_PARKED_PATTERN = re.compile(
    r"\b(?:"
    + "|".join(re.escape(marker) for marker in STRONG_PARKED_MARKERS)
    + r"|(?:[a-z0-9-]+\.)+[a-z]{2,63}\s+is\s+for\s+sale)\b",
    re.IGNORECASE,
)
_WEAK_PARKED_PATTERN = re.compile(
    r"\b(?:" + "|".join(re.escape(marker) for marker in WEAK_PARKED_MARKERS) + r")\b",
    re.IGNORECASE,
)
Params = Mapping[str, str | int]


@dataclass(frozen=True)
class FetchResult:
    status: int
    url: str
    headers: dict[str, str]
    content: bytes


class Fetcher(Protocol):
    def get(self, url: str, *, params: Params | None = None) -> FetchResult | None: ...


class HttpFetcher:
    """Bound requests and throttle every hop, including redirects, per host."""

    def __init__(
        self,
        client: httpx.Client,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.client = client
        self.clock = clock
        self.sleep = sleep
        self._last_request: dict[str, float] = {}

    def get(self, url: str, *, params: Params | None = None) -> FetchResult | None:
        try:
            for redirects in range(6):
                if not http_url(url):
                    return None
                host = urlsplit(url).hostname or ""
                previous = self._last_request.get(host)
                if previous is not None:
                    self.sleep(max(0.0, previous + 1.0 - self.clock()))
                self._last_request[host] = self.clock()
                with self.client.stream(
                    "GET",
                    url,
                    params=params,
                    headers={"User-Agent": USER_AGENT},
                    timeout=10.0,
                    follow_redirects=False,
                ) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if redirects == 5 or not location:
                            return None
                        url = urljoin(str(response.url), location)
                        params = None
                        continue
                    if int(response.headers.get("content-length", "0")) > MAX_BODY_BYTES:
                        return None
                    content = bytearray()
                    for chunk in response.iter_bytes(chunk_size=65_536):
                        content.extend(chunk)
                        if len(content) > MAX_BODY_BYTES:
                            return None
                    return FetchResult(
                        response.status_code,
                        str(response.url),
                        dict(response.headers),
                        bytes(content),
                    )
        except Exception:
            # Network, streaming and malformed-response failures contribute no signal.
            return None
        return None


@dataclass
class Candidate:
    domain: str
    signals: set[str] = field(default_factory=set)
    p154_filename: str | None = None


@dataclass(frozen=True)
class Homepage:
    domain: str
    url: str = ""
    allowed: bool = True
    titles: tuple[str, ...] = ()
    icons: tuple[str, ...] = ()
    parked: bool = False


@dataclass(frozen=True)
class CandidateScore:
    signals: list[str]
    score: int
    parked: bool


@dataclass(frozen=True)
class Decision:
    status: Literal["found", "ambiguous", "not_found"]
    domain: str | None
    candidates: dict[str, CandidateScore]
    p154_filename: str | None = None
    homepage: Homepage | None = None


def _json_response(result: FetchResult | None) -> Any:
    if result is None or result.status != 200:
        return None
    try:
        return json.loads(result.content)
    except (ValueError, UnicodeError):
        return None


def _claim_value(claim: dict[str, Any]) -> Any:
    return claim.get("mainsnak", {}).get("datavalue", {}).get("value")


def wikidata_candidates(fetcher: Fetcher, name: str) -> list[Candidate]:
    key = company_key(name)
    if not key:
        return []
    search = _json_response(
        fetcher.get(
            WIKIDATA_API,
            params={
                "action": "wbsearchentities",
                "search": name,
                "language": "en",
                "type": "item",
                "limit": 7,
                "format": "json",
            },
        )
    )
    if not isinstance(search, dict):
        return []
    ids = [entry["id"] for entry in search.get("search", [])[:7] if entry.get("id")]
    if not ids:
        return []
    data = _json_response(
        fetcher.get(
            WIKIDATA_API,
            params={
                "action": "wbgetentities",
                "ids": "|".join(ids),
                "props": "labels|aliases|claims",
                "languages": "en",
                "format": "json",
            },
        )
    )
    if not isinstance(data, dict) or not isinstance(data.get("entities"), dict):
        return []
    candidates = []
    for entity_id in ids:
        entity = data["entities"].get(entity_id, {})
        names = [entity.get("labels", {}).get("en", {}).get("value", "")]
        names.extend(alias.get("value", "") for alias in entity.get("aliases", {}).get("en", []))
        if not any(company_key(value) == key for value in names if isinstance(value, str)):
            continue
        claims = entity.get("claims", {})
        if any(
            isinstance(value := _claim_value(claim), dict) and value.get("id") == "Q5"
            for claim in claims.get("P31", [])
        ):
            continue
        filename = next(
            (
                value
                for claim in claims.get("P154", [])
                if isinstance(value := _claim_value(claim), str) and value
            ),
            None,
        )
        for claim in claims.get("P856", []):
            if "P582" in claim.get("qualifiers", {}):
                continue
            website = http_url(_claim_value(claim))
            domain = clean_domain(website, owner_key=key)
            if domain:
                candidates.append(Candidate(domain, {"wikidata"}, filename))
    return candidates


def clearbit_candidates(fetcher: Fetcher, name: str) -> list[Candidate]:
    key = company_key(name)
    if not key:
        return []
    suggestions = _json_response(fetcher.get(CLEARBIT_API, params={"query": name}))
    if not isinstance(suggestions, list):
        return []
    candidates = []
    for suggestion in suggestions:
        if not isinstance(suggestion, dict) or not isinstance(suggestion.get("name"), str):
            continue
        if company_key(suggestion["name"]) != key:
            continue
        domain = clean_domain(suggestion.get("domain"), owner_key=key)
        if domain:
            candidates.append(Candidate(domain, {"clearbit"}))
    return candidates


_LISTING_HOST = re.compile(
    r"https?://[^\s<>\"']+|(?<![\w@.-])(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+"
    r"[a-z]{2,63}(?![\w-]|\.[a-z0-9])",
    re.IGNORECASE,
)


def listing_candidates(texts: list[str], *, owner_key: str | None = None) -> list[Candidate]:
    hosts: Counter[str] = Counter()
    for text in texts:
        for match in _LISTING_HOST.finditer(text):
            domain = clean_domain(match.group().rstrip(".,;:!?)]}"), owner_key=owner_key)
            if domain:
                hosts[domain] += 1
    return [Candidate(domain, {"listing"}) for domain, _ in hosts.most_common(5)]


def inspect_homepage(
    fetcher: Fetcher, domain: str, robots_cache: dict[str, RobotFileParser]
) -> Homepage:
    url = f"https://{domain}/"
    if domain not in robots_cache:
        robots_url = urljoin(url, "robots.txt")
        robots = fetcher.get(robots_url)
        parser = RobotFileParser(robots_url)
        parser.parse(
            robots.content.decode("utf-8", errors="replace").splitlines()
            if robots is not None and robots.status == 200
            else []
        )
        robots_cache[domain] = parser
    if not robots_cache[domain].can_fetch("AspirovaBot", url):
        return Homepage(domain, allowed=False)
    result = fetcher.get(url)
    if result is None:
        return Homepage(domain)
    if result.status != 200 or not http_url(result.url):
        return Homepage(domain, url=result.url)
    soup = BeautifulSoup(result.content, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    titles = [title]
    for meta in soup.find_all("meta"):
        if str(meta.get("property") or meta.get("name") or "").lower() in {
            "og:site_name",
            "og:title",
            "application-name",
        }:
            titles.append(str(meta.get("content", "")))
    icons: list[tuple[int, str]] = []
    for link in soup.find_all("link"):
        rel = {str(value).lower() for value in link.get("rel", [])}
        if not rel.intersection({"apple-touch-icon", "apple-touch-icon-precomposed", "icon"}):
            continue
        href = link.get("href")
        try:
            icon = http_url(urljoin(result.url, href)) if isinstance(href, str) else None
        except ValueError:
            continue
        if (
            not icon
            or urlsplit(icon).path.lower().endswith(".svg")
            or str(link.get("type", "")).lower().split(";")[0].strip() == "image/svg+xml"
        ):
            continue
        sizes = re.findall(r"(\d+)x(\d+)", str(link.get("sizes", "")), re.IGNORECASE)
        area = max((int(width) * int(height) for width, height in sizes), default=0)
        icons.append((area, icon))
    icons.sort(key=lambda item: item[0], reverse=True)
    for element in soup(["script", "style", "noscript", "template", "head", "title"]):
        element.decompose()
    visible = soup.get_text(" ", strip=True)
    visible_prefix = visible.encode("utf-8")[:5120].decode("utf-8", errors="ignore")
    strong_marker = _STRONG_PARKED_PATTERN.search(title) or _STRONG_PARKED_PATTERN.search(
        visible_prefix
    )
    weak_marker = _WEAK_PARKED_PATTERN.search(title) or (
        len(visible) < 1000 and _WEAK_PARKED_PATTERN.search(visible)
    )
    return Homepage(
        domain,
        url=result.url,
        titles=tuple(value for value in titles if value),
        icons=tuple(dict.fromkeys(icon for _, icon in icons)),
        parked=bool(strong_marker or weak_marker),
    )


def title_matches(key: str, homepage: Homepage) -> bool:
    final_host = clean_domain(http_url(homepage.url), owner_key=key)
    if (
        not key
        or not homepage.allowed
        or not final_host
        or not same_site(homepage.domain, final_host)
    ):
        return False
    return any(
        f" {key} " in f" {re.sub(r'[\W_]+', ' ', title.lower()).strip()} "
        for title in homepage.titles
    )


def _merge_candidates(candidates: list[Candidate], key: str) -> list[Candidate]:
    merged: dict[str, Candidate] = {}
    for candidate in sorted(
        candidates, key=lambda candidate: (len(candidate.domain), candidate.domain)
    ):
        domain = clean_domain(candidate.domain, owner_key=key)
        if not domain:
            continue
        parent = next((host for host in merged if same_site(host, domain)), domain)
        target = merged.setdefault(parent, Candidate(parent))
        target.signals.update(candidate.signals)
        if target.p154_filename is None:
            target.p154_filename = candidate.p154_filename
    return list(merged.values())


def score_candidates(
    key: str, candidates: list[Candidate], homepages: Mapping[str, Homepage]
) -> Decision:
    threshold = 4 if len(key.split()) == 1 else 3
    merged = _merge_candidates(candidates, key)
    evidence = {}
    for candidate in merged:
        signals = candidate.signals.copy()
        pages = [page for host, page in homepages.items() if same_site(host, candidate.domain)]
        if any(title_matches(key, page) for page in pages):
            signals.add("title")
        parked = any(page.parked for page in pages)
        evidence[candidate.domain] = CandidateScore(
            signals=sorted(signals),
            score=0 if parked else sum(SIGNAL_WEIGHTS[signal] for signal in signals),
            parked=parked,
        )
    winners = [candidate for candidate in merged if evidence[candidate.domain].score >= threshold]
    if len(winners) != 1:
        return Decision("ambiguous" if winners else "not_found", None, evidence)
    winner = winners[0]
    return Decision(
        "found",
        winner.domain,
        evidence,
        winner.p154_filename,
        homepages.get(winner.domain),
    )


def discover_domain(
    fetcher: Fetcher,
    name: str,
    listing_texts: list[str],
    robots_cache: dict[str, RobotFileParser],
) -> Decision:
    key = company_key(name)
    if not key:
        return Decision("not_found", None, {})
    threshold = 4 if len(key.split()) == 1 else 3
    candidates = _merge_candidates(
        wikidata_candidates(fetcher, name)
        + clearbit_candidates(fetcher, name)
        + listing_candidates(listing_texts, owner_key=key),
        key,
    )
    homepages = {
        candidate.domain: inspect_homepage(fetcher, candidate.domain, robots_cache)
        for candidate in candidates
        if sum(SIGNAL_WEIGHTS[signal] for signal in candidate.signals) >= threshold - 1
    }
    return score_candidates(key, candidates, homepages)


def wikimedia_logo_url(filename: str) -> str:
    return (
        "https://commons.wikimedia.org/wiki/Special:FilePath/"
        + quote(filename, safe="")
        + "?width=256"
    )


def icon_candidates(domain: str, homepage: Homepage, p154_filename: str | None) -> list[str]:
    urls = list(homepage.icons) if homepage.allowed else []
    urls.extend(
        [
            f"https://{domain}/apple-touch-icon.png",
            f"https://icons.duckduckgo.com/ip3/{domain}.ico",
            f"https://www.google.com/s2/favicons?domain={domain}&sz=128",
        ]
    )
    if p154_filename:
        urls.append(wikimedia_logo_url(p154_filename))
    return list(dict.fromkeys(urls))
