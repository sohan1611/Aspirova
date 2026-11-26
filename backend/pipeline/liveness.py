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
from threading import TIMEOUT_MAX
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
from crawlers.workday import REQUEST_DELAY_SECONDS, cxs_endpoints, job_posting_info, tenant_lock
from pipeline.retirement import ROLLING_WINDOW_SOURCES, meta_without_closed_reason
from pipeline.destination_check import (
    CheckBudgetExceeded,
    inspect_destination,
    observation_liveness,
)
from core.destination_facts import (
    classify_destination_facts,
    destination_input_key,
    retain_alive_verification,
    url_key,
)

DEFAULT_LIMIT = 1500
DEFAULT_MAX_SECONDS = 600
DEFAULT_CONCURRENCY = 10
BATCH_SIZE = 50
HTTP_TIMEOUT_SECONDS = 10.0
WORKDAY_BACKOFF_SECONDS = 30.0
WORKDAY_TIMEOUT_BURST = 3
# The Tier 1 crawl workflow schedules liveness once a day.
FRESHNESS_RUN_INTERVAL = timedelta(days=1)
PARTIAL_SOURCES = ROLLING_WINDOW_SOURCES | {"workday", "amazon", "hackerearth"}

LivenessStatus = Literal["alive", "closed", "inconclusive"]
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


@dataclass
class LivenessSourceCounts:
    scanned: int = 0
    closed: int = 0
    alive: int = 0
    inconclusive: int = 0
    reopened: int = 0
    reasons: Counter[str] = field(default_factory=Counter)


@dataclass
class LivenessResult(LivenessSourceCounts):
    timed_out: bool = False
    gone: int = 0
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

    def _request(
        self, client: httpx.Client, method: str, url: str, **kwargs: Any
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
            if response.status_code in {429, 503}:
                defer(max(WORKDAY_BACKOFF_SECONDS, retry_after_seconds(response) or 0.0))
            return response

        lock = tenant_lock(f"https://{host}")
        if not lock.acquire(timeout=min(TIMEOUT_MAX, max(0, self.deadline - monotonic()))):
            raise CheckBudgetExceeded
        try:
            if monotonic() < self.cooldown_until.get(cluster, 0):
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


def fetch_destination_observation(
    url: str,
    client: httpx.Client,
    *,
    workday_checker: WorkdayLivenessChecker | None = None,
    allowed_board: tuple[str, str] | None = None,
    expected_title: str | None = None,
) -> dict:
    if _workday_host(url):
        observation = (workday_checker or WorkdayLivenessChecker()).observe(
            url, client, expected_title=expected_title
        )
        # CXS has no HTML fallback; rescue needs positive same-posting evidence.
        return observation
    return inspect_destination(
        url, client, allowed_board=allowed_board, expected_title=expected_title
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
        eligible = or_(
            models.Opportunity.closed_at.is_(None),
            models.Opportunity.meta["closed_reason"].astext == "rolling_window_ttl",
        ) & (verified < now - func.make_interval(0, 0, 0, 0, cadence_value("check_hours")))
        stale_at = verified + func.make_interval(0, 0, 0, 0, cadence_value("stale_hours"))
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
        if status == "alive" and observations.get(c.id, {}).get("same_posting") is True
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
        .values(closed_at=None, meta=meta_without_closed_reason())
        .execution_options(synchronize_session=False)
        .returning(models.Opportunity.id)
    ).all()
    confirmed_ids.update(reopened)
    return len(reopened)


def _checked_batches(
    candidates: list[LivenessCandidate],
    *,
    checker: Callable[[LivenessCandidate], tuple[LivenessStatus, dict | None]],
    concurrency: int,
    batch_size: int,
    deadline: float,
    cooldown_until: dict[str, float],
) -> Iterator[list[tuple[LivenessCandidate, LivenessStatus, dict | None]]]:
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
        batch: list[tuple[LivenessCandidate, LivenessStatus, dict | None]] = []
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
                    yield batch
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
                    status, observation = future.result()
                except Exception:
                    status, observation = "inconclusive", None
                if status not in {"alive", "closed", "inconclusive"}:
                    status = "inconclusive"
                batch.append((candidates[index], status, observation))
        if batch:
            yield batch


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

        def observe(candidate: LivenessCandidate) -> tuple[LivenessStatus, dict | None]:
            if checker is not None:
                # Injected statuses alone carry no positive HTTP evidence.
                return checker(candidate.apply_url), None
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
            )
            return observation_liveness(observation), observation

        for batch in _checked_batches(
            candidates,
            checker=observe,
            concurrency=concurrency,
            batch_size=batch_size,
            deadline=deadline,
            cooldown_until=workday_checker.cooldown_until,
        ):
            checks = [(candidate, status) for candidate, status, _ in batch]
            observations = {
                candidate.id: observation
                for candidate, _, observation in batch
                if observation is not None
            }
            gone_ids = [candidate.id for candidate, status in checks if status == "closed"]
            if apply:
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
                    if rescue
                    and status == "alive"
                    and observations.get(c.id, {}).get("same_posting") is True
                }

            result.gone += len(gone_ids)
            for candidate, status, observation in batch:
                source = candidate.source if candidate.source in SOURCE_CADENCE else "other"
                counts = result.by_source[source]
                reason = _inconclusive_reason(observation) if status == "inconclusive" else None
                for total in (result, counts):
                    total.scanned += 1
                    total.closed += candidate.id in closed_ids
                    total.reopened += candidate.id in reopened_ids
                    total.alive += status == "alive"
                    if reason is not None:
                        total.inconclusive += 1
                        total.reasons[reason] += 1

    result.timed_out = result.scanned < len(candidates)
    return result
