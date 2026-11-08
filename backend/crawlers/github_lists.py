"""Metadata and employer links from the endorsed GitHub student lists (Doc 04).

The shared fetcher also supplies board discovery, before aggregator ATS exclusions.
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import sleep
from typing import Any, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from core.adapters import NormalizedListing, RawListing
from core.domains import clean_domain
from crawlers.common import USER_AGENT, build_http_timeout, content_hash, request_with_retries
from pipeline.location_country import derive_country
from pipeline.normalize import NEW_GRAD_TITLE_PATTERN, normalize_company_name, normalize_title

logger = logging.getLogger(__name__)
ATTRIBUTION = "GitHub internship lists (SimplifyJobs)"
# The first configured file wins duplicates across lists.
LIST_REPOS = (
    ("SimplifyJobs/Summer2027-Internships", "internship"),
    ("SimplifyJobs/New-Grad-Positions", "job"),
)
MIN_LIST_RECORDS = 1001
_GREENHOUSE_HOST = re.compile(r"(?:job-)?boards(?:\.eu)?\.greenhouse\.io$")
_ATS_HOSTS = {"jobs.lever.co", "jobs.ashbyhq.com", "apply.workable.com", "jobs.smartrecruiters.com"}
_NON_EMPLOYER_HOSTS = {"simplify.jobs", "go.vansh.nyc"}


def canonical_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parts = urlsplit(value.strip())
        host = (parts.hostname or "").lower()
        if parts.scheme not in {"http", "https"} or not host or parts.username or parts.password:
            return None
        if any(
            host == excluded or host.endswith("." + excluded) for excluded in _NON_EMPLOYER_HOSTS
        ):
            return None
        query = [
            (key, val)
            for key, val in parse_qsl(parts.query, keep_blank_values=True)
            if not key.lower().startswith("utm_") and key.lower() not in {"ref", "gh_src", "source"}
        ]
        path = parts.path
        # AshbyAdapter links to jobUrl (the job page), not its /application child.
        if host == "jobs.ashbyhq.com" and path.rstrip("/").endswith("/application"):
            path = path.rstrip("/")[: -len("/application")]
        return urlunsplit(
            (parts.scheme.lower(), parts.netloc.lower(), path, urlencode(sorted(query)), "")
        )
    except ValueError:
        return None


def is_board_ats_url(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return bool(
        _GREENHOUSE_HOST.fullmatch(host)
        or host in _ATS_HOSTS
        or host.endswith(".recruitee.com")
        or host.endswith(".myworkdayjobs.com")
    )


def company_domain(record: dict[str, Any]) -> str | None:
    url = canonical_url(record.get("company_url"))
    return clean_domain(url) if url else None


@dataclass
class ListFetch:
    records: list[dict[str, Any]] = field(default_factory=list)
    fetched_repos: list[str] = field(default_factory=list)
    record_counts: dict[str, int] = field(default_factory=dict)
    failures: dict[str, str] = field(default_factory=dict)

    @property
    def complete(self) -> bool:
        return (
            bool(LIST_REPOS)
            and not self.failures
            and all(
                repo in self.fetched_repos and self.record_counts.get(repo, 0) >= MIN_LIST_RECORDS
                for repo, _category in LIST_REPOS
            )
        )


def fetch_lists(client: httpx.Client) -> ListFetch:
    """One JSON GET per repo on success; shared bounded 429/5xx backoff."""
    result = ListFetch()
    for repo, category in LIST_REPOS:
        url = f"https://raw.githubusercontent.com/{repo}/dev/.github/scripts/listings.json"

        def request_once() -> httpx.Response:
            # Pace retries too, including a source asking for Retry-After: 0.
            sleep(0.5)
            return client.get(url)

        fetched = request_with_retries(request_once, max_retries=2, sleeper=sleep)
        response = fetched.response
        reason = fetched.terminal_reason
        if response is None or response.status_code != 200:
            reason = reason or (
                f"http_{response.status_code}" if response is not None else "request_error"
            )
        else:
            try:
                rows = response.json()
                if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                    raise ValueError("expected an array of records")
            except ValueError:
                reason = "invalid_list_json"
            else:
                result.fetched_repos.append(repo)
                result.record_counts[repo] = len(rows)
                result.records.extend(
                    row | {"list_repo": repo, "list_category": category} for row in rows
                )
                if len(rows) >= MIN_LIST_RECORDS:
                    continue
                reason = f"suspicious_record_count:{len(rows)}<{MIN_LIST_RECORDS}"
        result.failures[repo] = reason or "invalid_response"
        logger.warning("GitHub list %s failed: %s", repo, result.failures[repo])
    return result


def _posted_at(value: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(float(value), UTC)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return []


class GithubListsAdapter:
    source_slug = "github_lists"
    requires_browser = False

    def __init__(self, timeout: float = 15.0) -> None:
        self._client = httpx.Client(
            timeout=build_http_timeout(timeout), headers={"User-Agent": USER_AGENT}
        )
        self._last_health: Literal["ok", "degraded", "broken"] = "ok"
        self._fetch = ListFetch()
        self._counts: dict[str, int] = {}

    def fetch(self) -> list[RawListing]:
        self._fetch = fetch_lists(self._client)
        self._counts = {
            "raw_count": len(self._fetch.records),
            "skipped_ats_hosted": 0,
            "skipped_invalid_or_wrapped_url": 0,
            "duplicates": 0,
        }
        seen_urls: set[str] = set()
        seen_roles: set[tuple[str, str, str]] = set()
        listings: list[RawListing] = []
        malformed = False
        for record in self._fetch.records:
            if record.get("active") is not True or record.get("is_visible") is not True:
                continue
            url = canonical_url(record.get("url"))
            if not url:
                self._counts["skipped_invalid_or_wrapped_url"] += 1
                continue
            if is_board_ats_url(url):
                self._counts["skipped_ats_hosted"] += 1
                continue
            company = record.get("company_name")
            title = record.get("title")
            if (
                not isinstance(company, str)
                or not company.strip()
                or not isinstance(title, str)
                or not title.strip()
            ):
                malformed = True
                continue
            locations = _strings(record.get("locations"))
            role = (
                normalize_company_name(company),
                normalize_title(title),
                (locations[0] if locations else "").casefold(),
            )
            if url in seen_urls or role in seen_roles:
                self._counts["duplicates"] += 1
                continue
            seen_urls.add(url)
            seen_roles.add(role)
            payload = record | {"url": url}
            listings.append(
                RawListing(
                    source_slug=self.source_slug,
                    external_id=url,
                    source_url=url,
                    content_hash=content_hash(payload),
                    raw_payload=payload,
                )
            )
        self._counts["student_relevant_count"] = len(listings)
        self._last_health = "ok" if self._fetch.complete and not malformed else "degraded"
        return listings

    def parse(self, raw: RawListing) -> NormalizedListing:
        record = raw.raw_payload
        title = record["title"].strip()
        category = record["list_category"]
        # The existing new_grad filter uses NEW_GRAD_TITLE_PATTERN, not a meta flag.
        # Preserve the exact upstream title for provenance when the list supplies the signal.
        if category == "job" and not re.search(NEW_GRAD_TITLE_PATTERN, title, re.IGNORECASE):
            title += " (New Grad)"
        locations = _strings(record.get("locations"))
        location = "; ".join(locations) or None
        terms = _strings(record.get("terms") or record.get("season"))
        sponsorship = str(record.get("sponsorship") or "not specified")
        summary = (
            f"{record['company_name']} lists an opportunity for {title}"
            f"{(' for ' + ', '.join(terms)) if terms else ''}"
            f"{(' in ' + location) if location else ''}; sponsorship: {sponsorship}."
        )
        return NormalizedListing(
            source_slug=self.source_slug,
            external_id=raw.external_id,
            source_url=raw.source_url,
            title=title,
            company_name=record["company_name"],
            company_domain=company_domain(record),
            location=location,
            country=derive_country(location),
            is_remote=any(re.search(r"\bremote\b", value, re.IGNORECASE) for value in locations),
            category=category,
            description_raw=summary,
            apply_url=raw.source_url,
            posted_at=_posted_at(record.get("date_posted")),
            deadline_confidence="unknown",
            meta={
                "summary_source": "extracted",
                "terms": terms,
                "sponsorship": record.get("sponsorship"),
                "degrees": record.get("degrees"),
                "list_repo": record["list_repo"],
                "original_title": record["title"],
                "attribution": ATTRIBUTION,
            },
        )

    def health(self) -> Literal["ok", "degraded", "broken"]:
        return self._last_health

    def coverage(self) -> dict[str, Any]:
        return {
            "mode": "full_list",
            "status": (
                "complete" if self._fetch.complete and self._last_health == "ok" else "partial"
            ),
            "expected_total": None,
            "note": "configured files enumerate every listing, including active:false closures",
            "details": self._counts
            | {
                "fetched_repos": self._fetch.fetched_repos,
                "record_counts": self._fetch.record_counts,
                "min_list_records": MIN_LIST_RECORDS,
                "failures": self._fetch.failures,
            },
        }
