"""Bounded destination checks, verification refresh and recent-closure rescue.

The scheduled worker uses source cadence, including dated and rolling feeds.
Legacy callers keep the undated-only queue. Only 404/410 and the existing
Greenhouse soft-404 rule close rows; unknown checks never reset verification.
"""

from collections import Counter, defaultdict, deque
from collections.abc import Callable, Iterator
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from heapq import heappop, heappush
from threading import Lock, TIMEOUT_MAX
from time import monotonic, sleep
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx
from sqlalchemy import (
    BigInteger,
    DateTime,
    and_,
    case,
    cast,
    column,
    func,
    or_,
    select,
    text,
    tuple_,
    update,
    values,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from api.filters import open_opportunity_filters
from core import models
from core.freshness import (
    SOURCE_CADENCE,
    cadence_value,
    verified_expression,
    RESCUE_WINDOW_DAYS,
    RESCUE_RECHECK_HOURS,
    RESCUE_DELAY_SECONDS,
)
from core.listing_safety import without_manual_override, without_safety_flag
from crawlers.common import USER_AGENT, request_with_retries, retry_after_seconds
from crawlers.workday import (
    PAGE_SIZE,
    REQUEST_DELAY_SECONDS,
    SEARCH_TERMS,
    cxs_endpoints,
    cxs_search_body,
    cxs_search_page,
    job_posting_info,
    tenant_lock,
)
from pipeline.retirement import ROLLING_WINDOW_SOURCES, meta_without_closed_reason
from pipeline.destination_check import (
    CheckBudgetExceeded,
    inspect_destination,
    observation_liveness,
    public_dns,
)
from core.destination_facts import (
    classify_destination_facts,
    destination_input_key,
    registrable_domain,
    retain_alive_verification,
    url_key,
)

DEFAULT_LIMIT = 1500
DEFAULT_MAX_SECONDS = 600
DEFAULT_CONCURRENCY = 10
BATCH_SIZE = 50
HTTP_TIMEOUT_SECONDS = 10.0
WORKDAY_BACKOFF_SECONDS = 30.0
WORKDAY_MAX_BACKOFF_SECONDS = 480.0
WORKDAY_TIMEOUT_BURST = 3
FORBIDDEN_BURST = 3
WORKDAY_LIST_PAGE_CAP = 16
# The Tier 1 crawl workflow schedules liveness once a day.
FRESHNESS_RUN_INTERVAL = timedelta(days=1)
PARTIAL_SOURCES = ROLLING_WINDOW_SOURCES | {"workday", "amazon", "hackerearth"}

LivenessStatus = Literal["alive", "closed", "inconclusive"]
CheckStatus = Literal["alive", "closed", "inconclusive", "skipped"]
SKIP_REASONS = ("skipped_403", "list_unmatched", "list_absent")
INCONCLUSIVE_REASONS = (
    "timeout",
    "403",
    "429",
    "5xx",
    "other_4xx",
    "parse_or_shape",
    "redirect",
    "lock_or_budget",
    "other",
)


@dataclass(frozen=True)
class LivenessCandidate:
    id: int
    apply_url: str
    ats_type: str | None = None
    ats_board_id: str | None = None
    title: str | None = None
    source: str | None = None


Check = tuple[LivenessCandidate, CheckStatus, dict | None]


@dataclass
class LivenessSourceCounts:
    scanned: int = 0
    closed: int = 0
    alive: int = 0
    inconclusive: int = 0
    reopened: int = 0
    skipped: int = 0
    reasons: Counter[str] = field(default_factory=Counter)


@dataclass
class LivenessResult(LivenessSourceCounts):
    timed_out: bool = False
    gone: int = 0
    workday_list: Counter[str] = field(default_factory=Counter)
    by_source: dict[str, LivenessSourceCounts] = field(
        default_factory=lambda: defaultdict(LivenessSourceCounts)
    )


def _inconclusive_reason(observation: dict | None) -> str:
    if observation is None:
        return "other"
    reason = observation.get("failure_reason")
    if reason in INCONCLUSIVE_REASONS:
        return reason
    code = observation.get("http_status")
    if code in {403, 429}:
        return str(code)
    if code is not None:
        if 500 <= code < 600:
            return "5xx"
        if 400 <= code < 500:
            return "other_4xx"
        if 300 <= code < 400:
            return "redirect"
    return "other"


class ForbiddenHosts:
    """Remember a run's consecutive 403s for ordinary destination hosts."""

    def __init__(self) -> None:
        self._counts: Counter[str] = Counter()
        self._lock = Lock()

    def blocked(self, host: str) -> bool:
        with self._lock:
            return self._counts[host.removeprefix("www.")] >= FORBIDDEN_BURST

    def record(self, host: str, status: int) -> None:
        host = host.removeprefix("www.")
        with self._lock:
            if self._counts[host] >= FORBIDDEN_BURST:
                return
            if status == 403:
                self._counts[host] += 1
            else:
                self._counts.pop(host, None)


def _skip(candidate: LivenessCandidate, reason: str) -> Check:
    return candidate, "skipped", {"failure_reason": reason}


def classify_liveness_status_code(status_code: int) -> LivenessStatus:
    if status_code in {404, 410}:
        return "closed"
    if 200 <= status_code < 400:
        return "alive"
    return "inconclusive"


def _classify_status_code(status_code: int) -> LivenessStatus:
    return classify_liveness_status_code(status_code)


def _workday_host(url: str) -> str | None:
    try:
        host = urlsplit(url).hostname or ""
    except ValueError:
        return None
    return host if host.endswith(".myworkdayjobs.com") else None


def _workday_cluster(url: str) -> str | None:
    host = _workday_host(url)
    return host.rsplit(".", 3)[-3] if host else None


def _valid_workday_detail(response: httpx.Response) -> bool:
    try:
        return job_posting_info(response.json()) is not None
    except ValueError:
        return False


class WorkdayLivenessChecker:
    """Check the posting API while retaining the crawler's tenant pacing."""

    def __init__(self, deadline: float = float("inf")) -> None:
        self.deadline = deadline
        self.cooldown_until: dict[str, float] = {}
        self.consecutive_timeouts: Counter[str] = Counter()
        self.forbidden = ForbiddenHosts()
        self.backoffs: dict[str, float] = {}

    def _request(
        self,
        client: httpx.Client,
        method: str,
        url: str,
        *,
        on_attempt: Callable[[], None] | None = None,
        **kwargs: Any,
    ) -> httpx.Response | None:
        host = urlsplit(url).hostname or ""
        cluster = _workday_cluster(url) or host
        last_response: httpx.Response | None = None
        last_error: httpx.RequestError | None = None

        def paced_sleep(delay: float) -> None:
            if monotonic() + delay >= self.deadline:
                self.cooldown_until[cluster] = self.deadline
                raise CheckBudgetExceeded
            sleep(delay)

        def defer(delay: float) -> None:
            self.cooldown_until[cluster] = monotonic() + delay
            # End this attempt with its recorded HTTP or transport outcome.
            raise CheckBudgetExceeded

        def retry_sleep(delay: float) -> None:
            if delay >= WORKDAY_BACKOFF_SECONDS:
                defer(delay)
            paced_sleep(delay)

        def once() -> httpx.Response:
            nonlocal last_response, last_error
            paced_sleep(REQUEST_DELAY_SECONDS)
            try:
                if on_attempt is not None:
                    on_attempt()
                response = client.request(
                    method,
                    url,
                    headers={"User-Agent": USER_AGENT},
                    follow_redirects=False,
                    **kwargs,
                )
            except httpx.RequestError as exc:
                last_response, last_error = None, exc
                if isinstance(exc, httpx.TimeoutException):
                    self.consecutive_timeouts[cluster] += 1
                    if self.consecutive_timeouts[cluster] >= WORKDAY_TIMEOUT_BURST:
                        self.consecutive_timeouts.pop(cluster)
                        defer(WORKDAY_BACKOFF_SECONDS)
                else:
                    self.consecutive_timeouts.pop(cluster, None)
                raise
            last_response, last_error = response, None
            self.consecutive_timeouts.pop(cluster, None)
            self.forbidden.record(cluster, response.status_code)
            if response.status_code in {429, 503}:
                backoff = self.backoffs.get(cluster, WORKDAY_BACKOFF_SECONDS)
                self.backoffs[cluster] = min(backoff * 2, WORKDAY_MAX_BACKOFF_SECONDS)
                defer(max(backoff, retry_after_seconds(response) or 0.0))
            if response.is_success:
                self.backoffs.pop(cluster, None)
            return response

        lock = tenant_lock(f"https://{host}")
        if not lock.acquire(timeout=min(TIMEOUT_MAX, max(0, self.deadline - monotonic()))):
            raise CheckBudgetExceeded
        try:
            if self.forbidden.blocked(cluster) or monotonic() < self.cooldown_until.get(cluster, 0):
                raise CheckBudgetExceeded
            try:
                retried = request_with_retries(once, max_retries=1, sleeper=retry_sleep)
            except CheckBudgetExceeded:
                if last_response is not None:
                    return last_response
                if last_error is not None:
                    raise last_error
                raise
            if last_error is not None:
                raise last_error
            return retried.response
        finally:
            lock.release()

    def observe(self, url: str, client: httpx.Client, *, expected_title: str | None = None) -> dict:
        endpoints = cxs_endpoints(url)
        if endpoints is None:
            return {
                "url_key": url_key(url),
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "status": "unknown",
                "warnings": [],
                "failure_reason": "parse_or_shape",
            }
        # A Workday SPA can return 200 for a missing job; retain the CXS detail check.
        # TRUST-01 supersedes controlled-403 closure: an auth response is never absence.
        return inspect_destination(
            url,
            client,
            request_url=endpoints[1],
            request=lambda target: self._request(client, "GET", target),
            expected_title=expected_title,
            valid_response=_valid_workday_detail,
        )

    def check(self, url: str, client: httpx.Client) -> LivenessStatus:
        return observation_liveness(self.observe(url, client))

    def sweep(
        self, client: httpx.Client, endpoint: str, candidates: list[LivenessCandidate]
    ) -> tuple[list[Check], Counter[str]]:
        counts: Counter[str] = Counter()
        parts = urlsplit(endpoint)
        host = parts.hostname or ""
        if not public_dns(host, 443):
            counts["other"] += 1
            return [_skip(candidate, "list_unmatched") for candidate in candidates], counts

        by_detail: dict[str, list[LivenessCandidate]] = defaultdict(list)
        for candidate in candidates:
            endpoints = cxs_endpoints(candidate.apply_url)
            if endpoints is not None:
                by_detail[endpoints[1]].append(candidate)
        titles = [(candidate.title or "").casefold() for candidate in candidates]
        weights = {term: sum(term in title for title in titles) for term in SEARCH_TERMS}
        terms = sorted(
            (term for term in SEARCH_TERMS if weights[term]), key=weights.get, reverse=True
        )
        queue = deque((term, 0, 0) for term in (terms or [""]))
        matches: list[Check] = []
        board = endpoint.removesuffix("/jobs")
        cluster = _workday_cluster(endpoint) or host
        domain = registrable_domain(host)

        def read_page(
            term: str, offset: int, *, exact_title: bool = False
        ) -> tuple[int, int, list[dict[str, Any]]] | None:
            def count_request() -> None:
                counts["requests"] += 1
                if exact_title:
                    counts["exact_title_requests"] += 1

            try:
                response = self._request(
                    client,
                    "POST",
                    endpoint,
                    on_attempt=count_request,
                    json=cxs_search_body(term, offset),
                )
            except httpx.TimeoutException:
                counts["timeout"] += 1
                return None
            except CheckBudgetExceeded:
                counts["lock_or_budget"] += 1
                return None
            except httpx.RequestError:
                counts["other"] += 1
                return None
            if response is None or not response.is_success:
                code = response.status_code if response is not None else None
                reason = (
                    str(code) if code in {404, 410} else _inconclusive_reason({"http_status": code})
                )
                counts[reason] += 1
                return None
            try:
                page = cxs_search_page(response.json(), offset)
            except ValueError:
                page = None
            if page is None:
                counts["parse_or_shape"] += 1
                return None
            counts["pages"] += 1
            return response.status_code, *page

        def record_matches(code: int, postings: list[dict[str, Any]]) -> int:
            before = len(matches)
            checked_at = datetime.now(timezone.utc).isoformat()
            for posting in postings:
                path = posting.get("externalPath")
                title = posting.get("title")
                if not isinstance(path, str) or not isinstance(title, str) or not title.strip():
                    continue
                # The exact tenant, site and external posting path are required.
                # Search text, title and requisition-like bullet fields alone
                # cannot prove the listing identified by a different path.
                for candidate in by_detail.pop(board + path, ()):
                    matches.append(
                        (
                            candidate,
                            "alive",
                            {
                                "url_key": url_key(candidate.apply_url),
                                "status": "alive",
                                "http_status": code,
                                "checked_at": checked_at,
                                "same_posting": True,
                                "evidence": "workday_cxs_list",
                                "terminal_host": host,
                                "terminal_domain": domain,
                                "warnings": [],
                            },
                        )
                    )
            return len(matches) - before

        first_pages: set[str] = set()
        term_sweep_failed = False
        for _ in range(WORKDAY_LIST_PAGE_CAP):
            if not queue or not by_detail:
                break
            term, offset, total = queue.popleft()
            page = read_page(term, offset)
            if page is None:
                term_sweep_failed = True
                break
            code, page_total, postings = page
            record_matches(code, postings)
            if offset == 0:
                first_pages.add(term)
                total = page_total
            if len(postings) >= PAGE_SIZE and offset + PAGE_SIZE < total:
                queue.append((term, offset + PAGE_SIZE, total))

        if not term_sweep_failed:
            by_title: dict[str, set[str]] = defaultdict(set)
            for detail, rows in by_detail.items():
                for candidate in rows:
                    if candidate.title and candidate.title.strip():
                        by_title[candidate.title].add(detail)
            for title, details in by_title.items():
                if title in first_pages or not any(detail in by_detail for detail in details):
                    continue
                page = read_page(title, 0, exact_title=True)
                if page is None:
                    break
                first_pages.add(title)
                code, _, postings = page
                counts["exact_title_verified"] += record_matches(code, postings)

        counts["verified"] = len(matches)
        unmatched = "skipped_403" if self.forbidden.blocked(cluster) else "list_unmatched"
        for rows in by_detail.values():
            for candidate in rows:
                reason = (
                    "list_absent"
                    if candidate.title and candidate.title in first_pages
                    else unmatched
                )
                if reason == "list_absent":
                    counts["list_absent"] += 1
                matches.append(_skip(candidate, reason))
        return matches, counts


def fetch_destination_observation(
    url: str,
    client: httpx.Client,
    *,
    workday_checker: WorkdayLivenessChecker | None = None,
    allowed_board: tuple[str, str] | None = None,
    expected_title: str | None = None,
    forbidden_hosts: ForbiddenHosts | None = None,
) -> dict:
    if _workday_host(url):
        observation = (workday_checker or WorkdayLivenessChecker()).observe(
            url, client, expected_title=expected_title
        )
        # CXS has no HTML fallback; rescue needs positive same-posting evidence.
        return observation
    return inspect_destination(
        url,
        client,
        allowed_board=allowed_board,
        expected_title=expected_title,
        host_blocked=forbidden_hosts.blocked if forbidden_hosts else None,
        record_response=forbidden_hosts.record if forbidden_hosts else None,
    )


def fetch_url_liveness_status(
    url: str,
    client: httpx.Client,
    *,
    workday_checker: WorkdayLivenessChecker | None = None,
) -> LivenessStatus:
    return observation_liveness(
        fetch_destination_observation(
            url,
            client,
            workday_checker=workday_checker,
        )
    )


def _fetch_liveness_status(apply_url: str, client: httpx.Client) -> LivenessStatus:
    return fetch_url_liveness_status(apply_url, client)


def _select_candidates(session: Session, *, limit: int) -> list[LivenessCandidate]:
    checked_at = models.Opportunity.meta["liveness_checked_at"].astext
    rows = session.execute(
        select(
            models.Opportunity.id,
            models.Opportunity.apply_url,
            models.Company.ats_type,
            models.Company.ats_board_id,
            models.Opportunity.primary_source,
        )
        .outerjoin(models.Company, models.Opportunity.company_id == models.Company.id)
        .where(
            models.Opportunity.status == "active",
            without_safety_flag(),
            without_manual_override(),
            models.Opportunity.deadline.is_(None),
            models.Opportunity.closed_at.is_(None),
            models.Opportunity.last_seen_at < func.now() - text("interval '4 days'"),
            or_(
                models.Opportunity.primary_source.is_(None),
                models.Opportunity.primary_source.not_in(ROLLING_WINDOW_SOURCES),
            ),
            or_(
                checked_at.is_(None),
                cast(checked_at, DateTime(timezone=True)) < func.now() - text("interval '3 days'"),
            ),
        )
        .order_by(
            checked_at.asc().nulls_first(),
            models.Opportunity.last_seen_at.asc(),
            models.Opportunity.id.asc(),
        )
        .limit(limit)
    ).all()
    return [
        LivenessCandidate(
            id=row.id,
            apply_url=row.apply_url,
            ats_type=row.ats_type,
            ats_board_id=row.ats_board_id,
            source=row.primary_source,
        )
        for row in rows
    ]


def _select_freshness_candidates(
    session: Session, *, limit: int, rescue: bool = False, now: datetime
) -> list[LivenessCandidate]:
    """The scheduled service also checks dated listings and partial feeds.

    Legacy callers retain their undated-only queue. The public worker opts in
    to this cadence queue, with bounded recent-closure rescue as a separate run.
    """
    from pipeline.expire import FULL_INVENTORY_SOURCES

    checked = cast(models.Opportunity.meta["liveness_checked_at"].astext, DateTime(timezone=True))
    verified = verified_expression()
    retry_due = or_(
        checked.is_(None),
        checked
        < now
        - func.make_interval(
            0, 0, 0, 0, RESCUE_RECHECK_HOURS if rescue else cadence_value("check_hours")
        ),
    )
    priority = (cadence_value("priority"), checked.asc().nulls_first(), verified.asc())
    if rescue:
        eligible = (
            (models.Opportunity.closed_at >= now - timedelta(days=RESCUE_WINDOW_DAYS))
            & (models.Opportunity.closed_at <= now)
            & or_(
                models.Opportunity.primary_source.in_(PARTIAL_SOURCES),
                models.Opportunity.meta["closed_reason"].astext == "absence",
                # Before TRUST-02, absence closure had no reason. Restrict unknown
                # reasons to sources that actually support inventory retirement.
                models.Opportunity.primary_source.in_(
                    FULL_INVENTORY_SOURCES
                    | {
                        "greenhouse",
                        "lever",
                        "ashby",
                        "smartrecruiters",
                        "workable",
                        "recruitee",
                        "keka",
                    }
                )
                & models.Opportunity.meta["closed_reason"].astext.is_(None),
            )
        )
    else:
        stale_at = verified + func.make_interval(0, 0, 0, 0, cadence_value("stale_hours"))
        eligible = (
            or_(
                models.Opportunity.closed_at.is_(None),
                models.Opportunity.meta["closed_reason"].astext == "rolling_window_ttl",
            )
            & (verified < now - func.make_interval(0, 0, 0, 0, cadence_value("check_hours")))
            & (stale_at <= now + FRESHNESS_RUN_INTERVAL)
        )
        urgent = case(
            (
                models.Opportunity.primary_source.in_(PARTIAL_SOURCES)
                & (stale_at <= now + FRESHNESS_RUN_INTERVAL),
                and_(*open_opportunity_filters(require_recent_verification=False)),
            ),
            else_=False,
        )
        # Try urgent postings that have no attempt since their last confirmation
        # first so a persistent block cannot use the whole daily budget on retries.
        priority = (
            case((urgent, case((checked > verified, 1), else_=0)), else_=2),
            case((urgent, stale_at)).asc(),
            *priority,
        )
    rows = session.execute(
        select(
            models.Opportunity.id,
            models.Opportunity.apply_url,
            models.Company.ats_type,
            models.Company.ats_board_id,
            models.Opportunity.title,
            models.Opportunity.primary_source,
        )
        .outerjoin(models.Company, models.Company.id == models.Opportunity.company_id)
        .where(
            models.Opportunity.status == "active",
            without_safety_flag(),
            without_manual_override(),
            or_(models.Opportunity.deadline.is_(None), models.Opportunity.deadline > now),
            eligible,
            retry_due,
        )
        .order_by(*priority, models.Opportunity.id)
        .limit(limit)
    ).all()
    return [LivenessCandidate(*row) for row in rows]


def _reopen_verified(
    session: Session,
    checks: list[tuple[LivenessCandidate, LivenessStatus]],
    observations: dict[int, dict],
    checked_at: datetime,
    *,
    rescue: bool,
    confirmed_ids: set[int],
) -> int:
    expected = [
        (c.id, c.apply_url)
        for c, status in checks
        if status == "alive" and _can_reopen(c, observations.get(c.id, {}))
    ]
    if not expected:
        return 0
    reopened = session.scalars(
        update(models.Opportunity)
        .where(
            tuple_(models.Opportunity.id, models.Opportunity.apply_url).in_(expected),
            models.Opportunity.status == "active",
            without_safety_flag(),
            without_manual_override(),
            models.Opportunity.closed_at <= checked_at,
            or_(models.Opportunity.deadline.is_(None), models.Opportunity.deadline > func.now()),
            (
                True
                if rescue
                else models.Opportunity.meta["closed_reason"].astext == "rolling_window_ttl"
            ),
        )
        .values(
            closed_at=None,
            meta=meta_without_closed_reason().op("||")(
                func.jsonb_build_object("liveness_reopened_at", func.now())
            ),
        )
        .execution_options(synchronize_session=False)
        .returning(models.Opportunity.id)
    ).all()
    confirmed_ids.update(reopened)
    return len(reopened)


def _can_reopen(candidate: LivenessCandidate, observation: dict) -> bool:
    if (
        observation.get("same_posting") is not True
        or observation.get("evidence") == "workday_cxs_list"
    ):
        return False
    if candidate.source not in ROLLING_WINDOW_SOURCES:
        return True
    # A retained board page can repeat the old title at the old path after expiry.
    # Re-seen inventory still reopens TTL rows in the crawler.
    terminal_host = observation.get("terminal_host")
    return all(
        classify_destination_facts(url)["type"] != "aggregator"
        for url in (candidate.apply_url, f"https://{terminal_host}" if terminal_host else None)
    )


def _checked_batches(
    candidates: list[LivenessCandidate],
    *,
    checker: Callable[[LivenessCandidate], list[Check]],
    concurrency: int,
    batch_size: int,
    deadline: float,
    cooldown_until: dict[str, float],
) -> Iterator[list[Check]]:
    # One in-flight check per Workday data centre (wdN), even across tenants.
    # With the existing request delay, each data centre is capped at two
    # request starts per second, including retries. Other URLs use the pool.
    clusters = [_workday_cluster(candidate.apply_url) for candidate in candidates]
    followers: dict[str, deque[int]] = defaultdict(deque)
    ready: list[int] = []
    cooling: list[tuple[float, int]] = []
    for index, cluster in enumerate(clusters):
        if cluster is None or cluster not in followers:
            heappush(ready, index)
        if cluster is not None:
            followers[cluster].append(index)

    workers = min(concurrency, batch_size)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        pending: dict[Future, int] = {}
        batch: list[Check] = []
        while ready or pending or cooling:
            now = monotonic()
            while cooling and cooling[0][0] <= now:
                _, index = heappop(cooling)
                heappush(ready, index)
            while (
                ready
                and len(pending) < workers
                and len(batch) < batch_size
                and monotonic() < deadline
            ):
                index = heappop(ready)
                pending[executor.submit(checker, candidates[index])] = index

            next_ready = cooling[0][0] if cooling else deadline
            resumes_in_budget = next_ready < deadline and monotonic() < deadline
            if not pending:
                if batch:
                    # The caller writes and commits with no network work in flight.
                    for start in range(0, len(batch), batch_size):
                        yield batch[start : start + batch_size]
                    batch = []
                elif resumes_in_budget:
                    sleep(max(0.0, next_ready - monotonic()))
                else:
                    break
                continue

            wait_seconds = (
                max(0.0, next_ready - monotonic())
                if resumes_in_budget and len(pending) < workers and len(batch) < batch_size
                else None
            )
            completed, _ = wait(pending, timeout=wait_seconds, return_when=FIRST_COMPLETED)
            for future in completed:
                index = pending.pop(future)
                cluster = clusters[index]
                if cluster is not None:
                    queue = followers[cluster]
                    queue.popleft()
                    if queue:
                        resumes_at = cooldown_until.get(cluster, 0.0)
                        if resumes_at > monotonic():
                            heappush(cooling, (resumes_at, queue[0]))
                        else:
                            heappush(ready, queue[0])
                try:
                    batch.extend(future.result())
                except Exception:
                    batch.append((candidates[index], "inconclusive", None))
        for start in range(0, len(batch), batch_size):
            yield batch[start : start + batch_size]


def _mark_closed(
    session: Session,
    *,
    opportunity_ids: list[int],
    detected_at: datetime,
    expected_urls: dict[int, str] | None = None,
    confirmed_ids: set[int] | None = None,
) -> int:
    if not opportunity_ids:
        return 0
    statement = (
        update(models.Opportunity)
        .where(
            models.Opportunity.id.in_(opportunity_ids),
            (
                tuple_(models.Opportunity.id, models.Opportunity.apply_url).in_(
                    list(expected_urls.items())
                )
                if expected_urls is not None
                else True
            ),
            models.Opportunity.status == "active",
            without_safety_flag(),
            without_manual_override(),
            models.Opportunity.closed_at.is_(None),
            models.Opportunity.last_seen_at <= detected_at,
        )
        .values(closed_at=detected_at)
        .execution_options(synchronize_session=False)
    )
    if confirmed_ids is not None:
        closed = session.scalars(statement.returning(models.Opportunity.id)).all()
        confirmed_ids.update(closed)
        return len(closed)
    result = session.execute(statement)
    return int(result.rowcount or 0)


def _stamp_checked(session: Session, opportunity_ids: list[int], detected_at: datetime) -> None:
    # JSONB merge preserves summary_source and other metadata. Neither meta nor
    # closed_at changes text columns guarded by migration e5a9c2f1b6d3, so the
    # search trigger returns without recomputing search_tsv.
    session.execute(
        update(models.Opportunity)
        .where(
            models.Opportunity.id.in_(opportunity_ids),
            models.Opportunity.status == "active",
            without_safety_flag(),
            without_manual_override(),
        )
        .values(
            meta=func.coalesce(
                func.nullif(models.Opportunity.meta, text("'null'::jsonb")), text("'{}'::jsonb")
            ).op("||")(
                func.jsonb_build_object(
                    "liveness_checked_at", detected_at.astimezone(timezone.utc).isoformat()
                )
            )
        )
        .execution_options(synchronize_session=False)
    )


def _store_observations(
    session: Session,
    checks: list[tuple[LivenessCandidate, LivenessStatus]],
    observations: dict[int, dict],
    checked_at: datetime,
) -> None:
    candidates = [
        (candidate.id, candidate.apply_url)
        for candidate, _ in checks
        if candidate.id in observations
    ]
    if not candidates:
        return
    rows = session.execute(
        select(
            models.Opportunity.id,
            models.Opportunity.apply_url,
            models.Opportunity.primary_source,
            models.Opportunity.company_id,
            models.Opportunity.destination_facts,
            models.Company.domain,
            models.Company.ats_type,
            models.Company.ats_board_id,
        )
        .outerjoin(models.Company, models.Opportunity.company_id == models.Company.id)
        .where(
            tuple_(models.Opportunity.id, models.Opportunity.apply_url).in_(candidates),
            models.Opportunity.status == "active",
            without_safety_flag(),
            without_manual_override(),
        )
        .with_for_update(of=models.Opportunity)
    ).all()
    updates = []
    for row in rows:
        context = dict(
            source=row.primary_source,
            company_id=row.company_id,
            company_domain=row.domain,
            ats_type=row.ats_type,
            ats_board_id=row.ats_board_id,
        )
        previous = row.destination_facts if isinstance(row.destination_facts, dict) else {}
        computed_at = (
            previous.get("computed_at")
            if previous.get("input_key") == destination_input_key(row.apply_url, **context)
            else None
        )
        facts = classify_destination_facts(
            row.apply_url,
            **context,
            computed_at=computed_at or checked_at.isoformat(),
            observation=observations[row.id],
        )
        updates.append((row.id, retain_alive_verification(facts, previous)))
    if updates:
        parsed = values(
            column("id", BigInteger), column("facts", JSONB), name="destination_updates"
        ).data(updates)
        # One locked read and one write per batch, not per listing. Core bypasses
        # ORM hooks; neither statement changes the opportunity's metadata.
        session.execute(
            update(models.Opportunity)
            .where(models.Opportunity.id == parsed.c.id)
            .values(destination_facts=parsed.c.facts)
            .execution_options(synchronize_session=False)
        )


def check_listing_liveness(
    session: Session,
    *,
    apply: bool = False,
    limit: int = DEFAULT_LIMIT,
    max_seconds: int = DEFAULT_MAX_SECONDS,
    concurrency: int = DEFAULT_CONCURRENCY,
    batch_size: int = BATCH_SIZE,
    commit_each_batch: bool = True,
    now: datetime | None = None,
    checker: Callable[[str], LivenessStatus] | None = None,
    freshness_mode: bool = False,
    rescue: bool = False,
    changed_slugs: set[str] | None = None,
) -> LivenessResult:
    """Refresh verification and apply proven closure/reopen in committed batches."""
    if limit < 1:
        raise ValueError("limit must be at least 1")
    if max_seconds < 1:
        raise ValueError("max_seconds must be at least 1")
    if concurrency < 1:
        raise ValueError("concurrency must be at least 1")
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")

    detected_at = now or datetime.now(timezone.utc)
    deadline = monotonic() + max_seconds
    # Freeze every value before a commit can expire ORM state supplied by a caller.
    candidates = (
        _select_freshness_candidates(session, limit=limit, rescue=rescue, now=detected_at)
        if freshness_mode or rescue
        else _select_candidates(session, limit=limit)
    )
    result = LivenessResult()
    workday_checker = WorkdayLivenessChecker(deadline)
    forbidden_hosts = ForbiddenHosts()
    boards: dict[str, list[LivenessCandidate]] = defaultdict(list)
    if freshness_mode and not rescue and checker is None:
        for candidate in candidates:
            if candidate.source == "workday" and (endpoints := cxs_endpoints(candidate.apply_url)):
                boards[endpoints[0]].append(candidate)
    sweeps = {rows[0].id: (endpoint, rows) for endpoint, rows in boards.items() if len(rows) > 1}
    followers = {candidate.id for _, rows in sweeps.values() for candidate in rows[1:]}
    sweep_counts: dict[int, Counter[str]] = {}
    slugs = (
        dict(
            session.execute(
                select(models.Opportunity.id, models.Opportunity.slug).where(
                    models.Opportunity.id.in_([c.id for c in candidates])
                )
            ).all()
        )
        if changed_slugs is not None
        else {}
    )

    # Candidate selection and the script's SET start a transaction. Commit
    # before starting network work to preserve #224; each write also commits
    # before the scheduler resumes. Tests can opt out to keep fixture isolation.
    if candidates and commit_each_batch:
        session.commit()

    client_context = (
        httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=HTTP_TIMEOUT_SECONDS)
        if checker is None
        else nullcontext()
    )
    with client_context as client:

        def observe(candidate: LivenessCandidate) -> list[Check]:
            if checker is not None:
                # Injected statuses alone carry no positive HTTP evidence.
                status = checker(candidate.apply_url)
                return [
                    (candidate, status if status in {"alive", "closed"} else "inconclusive", None)
                ]
            cluster = _workday_cluster(candidate.apply_url)
            sweep = sweeps.get(candidate.id)
            if cluster is not None and workday_checker.forbidden.blocked(cluster):
                return [_skip(row, "skipped_403") for row in (sweep[1] if sweep else [candidate])]
            if sweep is not None:
                checks, counts = workday_checker.sweep(client, *sweep)
                sweep_counts[candidate.id] = counts
                return checks
            if rescue:
                # Rescue is serial in the worker, at most one posting per second.
                sleep(RESCUE_DELAY_SECONDS)
            board = (
                (candidate.ats_type, candidate.ats_board_id)
                if candidate.ats_type and candidate.ats_board_id
                else None
            )
            observation = fetch_destination_observation(
                candidate.apply_url,
                client,
                workday_checker=workday_checker,
                allowed_board=board,
                expected_title=candidate.title,
                forbidden_hosts=forbidden_hosts,
            )
            if observation.get("failure_reason") == "skipped_403":
                return [_skip(candidate, "skipped_403")]
            return [(candidate, observation_liveness(observation), observation)]

        for batch in _checked_batches(
            [candidate for candidate in candidates if candidate.id not in followers],
            checker=observe,
            concurrency=concurrency,
            batch_size=batch_size,
            deadline=deadline,
            cooldown_until=workday_checker.cooldown_until,
        ):
            checks = [(candidate, status) for candidate, status, _ in batch if status != "skipped"]
            observations = {
                candidate.id: observation
                for candidate, status, observation in batch
                if status != "skipped" and observation is not None
            }
            gone_ids = [candidate.id for candidate, status in checks if status == "closed"]
            if apply and checks:
                closed_ids: set[int] = set()
                reopened_ids: set[int] = set()
                _stamp_checked(session, [candidate.id for candidate, _ in checks], detected_at)
                _store_observations(session, checks, observations, detected_at)
                _reopen_verified(
                    session,
                    checks,
                    observations,
                    detected_at,
                    rescue=rescue,
                    confirmed_ids=reopened_ids,
                )
                _mark_closed(
                    session,
                    opportunity_ids=gone_ids,
                    detected_at=detected_at,
                    expected_urls={c.id: c.apply_url for c, status in checks if status == "closed"},
                    confirmed_ids=closed_ids,
                )
                if commit_each_batch:
                    session.commit()
                if changed_slugs is not None:
                    changed_slugs.update(slugs[c.id] for c, _ in checks if c.id in slugs)
            else:
                closed_ids = set(gone_ids)
                reopened_ids = {
                    c.id
                    for c, status in checks
                    if rescue and status == "alive" and _can_reopen(c, observations.get(c.id, {}))
                }

            result.gone += len(gone_ids)
            for candidate, status, observation in batch:
                source = candidate.source if candidate.source in SOURCE_CADENCE else "other"
                counts = result.by_source[source]
                reason = _inconclusive_reason(observation) if status == "inconclusive" else None
                for total in (result, counts):
                    if status == "skipped":
                        total.skipped += 1
                        total.reasons[observation["failure_reason"]] += 1
                        continue
                    total.scanned += 1
                    total.closed += candidate.id in closed_ids
                    total.reopened += candidate.id in reopened_ids
                    total.alive += status == "alive"
                    if reason is not None:
                        total.inconclusive += 1
                        total.reasons[reason] += 1

    for counts in sweep_counts.values():
        result.workday_list.update(counts)
    result.timed_out = result.scanned + result.skipped < len(candidates) or bool(
        result.workday_list["lock_or_budget"]
    )
    return result
