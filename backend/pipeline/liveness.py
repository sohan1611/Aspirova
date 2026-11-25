"""Bounded liveness checks for active undated listings.

This covers the small slice of listings that cannot be refreshed by deadline
logic and have not been confirmed by a real crawl in the last four days. Only
404/410 responses and confirmed Greenhouse soft-404s
mark a listing closed.
Every completed check rotates out of the queue for three days.
"""

from collections.abc import Callable, Iterable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from time import monotonic, sleep
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx
from sqlalchemy import (
    BigInteger,
    DateTime,
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

from core import models
from core.listing_safety import without_manual_override, without_safety_flag
from crawlers.common import USER_AGENT, request_with_retries
from crawlers.workday import REQUEST_DELAY_SECONDS, cxs_endpoints, tenant_lock
from pipeline.retirement import ROLLING_WINDOW_SOURCES
from pipeline.destination_check import inspect_destination, observation_liveness
from core.destination_facts import classify_destination_facts, destination_input_key

DEFAULT_LIMIT = 1500
DEFAULT_MAX_SECONDS = 600
DEFAULT_CONCURRENCY = 10
BATCH_SIZE = 50
HTTP_TIMEOUT_SECONDS = 10.0

LivenessStatus = Literal["alive", "closed", "inconclusive"]


@dataclass(frozen=True)
class LivenessCandidate:
    id: int
    apply_url: str
    ats_type: str | None = None
    ats_board_id: str | None = None


@dataclass
class LivenessResult:
    scanned: int = 0
    closed: int = 0
    alive: int = 0
    inconclusive: int = 0
    timed_out: bool = False


def _chunks(
    candidates: list[LivenessCandidate], batch_size: int
) -> Iterable[list[LivenessCandidate]]:
    for index in range(0, len(candidates), batch_size):
        yield candidates[index : index + batch_size]


def _estimated_batch_seconds(candidate_count: int, concurrency: int) -> float:
    waves = (candidate_count + concurrency - 1) // concurrency
    return waves * HTTP_TIMEOUT_SECONDS


def classify_liveness_status_code(status_code: int) -> LivenessStatus:
    if status_code in {404, 410}:
        return "closed"
    if 200 <= status_code < 400:
        return "alive"
    return "inconclusive"


def _classify_status_code(status_code: int) -> LivenessStatus:
    return classify_liveness_status_code(status_code)


class WorkdayLivenessChecker:
    """Check the posting API while retaining the crawler's tenant pacing."""

    def _request(
        self, client: httpx.Client, method: str, url: str, **kwargs: Any
    ) -> httpx.Response | None:
        base = f"https://{urlsplit(url).hostname}"

        def once() -> httpx.Response:
            sleep(REQUEST_DELAY_SECONDS)
            return client.request(
                method, url, headers={"User-Agent": USER_AGENT}, follow_redirects=False, **kwargs
            )

        with tenant_lock(base):
            return request_with_retries(once, max_retries=1, sleeper=sleep).response

    def observe(self, url: str, client: httpx.Client) -> dict:
        endpoints = cxs_endpoints(url)
        if endpoints is None:
            from core.destination_facts import url_key

            return {"url_key": url_key(url), "status": "unknown", "warnings": []}
        # A Workday SPA can return 200 for a missing job; retain the CXS detail check.
        # TRUST-01 supersedes controlled-403 closure: an auth response is never absence.
        return inspect_destination(
            url,
            client,
            request_url=endpoints[1],
            request=lambda target: self._request(client, "GET", target),
        )

    def check(self, url: str, client: httpx.Client) -> LivenessStatus:
        return observation_liveness(self.observe(url, client))


def fetch_destination_observation(
    url: str,
    client: httpx.Client,
    *,
    workday_checker: WorkdayLivenessChecker | None = None,
    allowed_board: tuple[str, str] | None = None,
) -> dict:
    try:
        host = urlsplit(url).hostname or ""
    except ValueError:
        host = ""
    if host.endswith(".myworkdayjobs.com"):
        return (workday_checker or WorkdayLivenessChecker()).observe(url, client)
    return inspect_destination(url, client, allowed_board=allowed_board)


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
            id=row.id, apply_url=row.apply_url, ats_type=row.ats_type, ats_board_id=row.ats_board_id
        )
        for row in rows
    ]


def _check_candidates(
    candidates: list[LivenessCandidate],
    *,
    checker: Callable[[str], LivenessStatus],
    concurrency: int,
) -> list[tuple[LivenessCandidate, LivenessStatus]]:
    if not candidates:
        return []

    max_workers = min(concurrency, len(candidates))
    results: list[tuple[LivenessCandidate, LivenessStatus]] = []
    executor = ThreadPoolExecutor(max_workers=max_workers)
    future_to_candidate = {
        executor.submit(checker, candidate.apply_url): candidate for candidate in candidates
    }
    try:
        while future_to_candidate:
            completed, _ = wait(
                future_to_candidate,
                timeout=0.25,
                return_when=FIRST_COMPLETED,
            )
            for future in completed:
                candidate = future_to_candidate.pop(future)
                try:
                    status = future.result()
                except Exception:
                    status = "inconclusive"
                if status not in {"alive", "closed", "inconclusive"}:
                    status = "inconclusive"
                results.append((candidate, status))
    finally:
        executor.shutdown(wait=True)

    return results


def _mark_closed(
    session: Session,
    *,
    opportunity_ids: list[int],
    detected_at: datetime,
    expected_urls: dict[int, str] | None = None,
) -> int:
    if not opportunity_ids:
        return 0
    result = session.execute(
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
        )
        .values(closed_at=detected_at)
        .execution_options(synchronize_session=False)
    )
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
    observations: dict[str, dict],
    checked_at: datetime,
) -> None:
    candidates = [
        (candidate.id, candidate.apply_url)
        for candidate, _ in checks
        if candidate.apply_url in observations
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
            observation=observations[row.apply_url],
        )
        updates.append((row.id, facts))
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
) -> LivenessResult:
    """Check stale undated listings, rotating checks and closing proven dead URLs."""
    if limit < 1:
        raise ValueError("limit must be at least 1")
    if max_seconds < 1:
        raise ValueError("max_seconds must be at least 1")
    if concurrency < 1:
        raise ValueError("concurrency must be at least 1")
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")

    detected_at = now or datetime.now(timezone.utc)
    started_at = monotonic()
    # Freeze every value before a commit can expire ORM state supplied by a caller.
    candidates = [
        LivenessCandidate(row.id, row.apply_url, row.ats_type, row.ats_board_id)
        for row in _select_candidates(session, limit=limit)
    ]
    result = LivenessResult()
    workday_checker = WorkdayLivenessChecker()

    for batch in _chunks(candidates, batch_size):
        elapsed_seconds = monotonic() - started_at
        if elapsed_seconds >= max_seconds or (
            checker is None
            and elapsed_seconds + _estimated_batch_seconds(len(batch), concurrency) > max_seconds
        ):
            result.timed_out = True
            break

        # Gather all batch context before committing. Between commit and completion
        # of the HTTP workers, only these plain values may be read.
        observations: dict[str, dict] = {}
        observation_lock = Lock()
        boards = {
            candidate.apply_url: (candidate.ats_type, candidate.ats_board_id)
            for candidate in batch
            if candidate.ats_type and candidate.ats_board_id
        }

        # Nothing may hold a database transaction open across the network
        # checks. Selecting candidates (and the script's SET) starts a
        # transaction, and a batch of slow or dripping URLs can run past the
        # 120s idle_in_transaction_session_timeout from core/db.py. Postgres
        # then kills the connection and the stamp UPDATE after the batch dies
        # with IdleInTransactionSessionTimeout (crawls 44569209726 and
        # 44703841666). Later batches start clean because each batch commits;
        # this covers the first one. crawlers/runner.py does the same before
        # its fetch. A dry run never writes after the checks, so it is left be.
        if apply and commit_each_batch:
            session.commit()

        def observe(url: str) -> LivenessStatus:
            observation = fetch_destination_observation(
                url, client, workday_checker=workday_checker, allowed_board=boards.get(url)
            )
            with observation_lock:
                observations[url] = observation
            return observation_liveness(observation)

        if checker is None:
            with httpx.Client(
                headers={"User-Agent": USER_AGENT},
                timeout=HTTP_TIMEOUT_SECONDS,
                follow_redirects=True,
            ) as client:
                checks = _check_candidates(
                    batch,
                    checker=observe,
                    concurrency=concurrency,
                )
        else:
            checks = _check_candidates(batch, checker=checker, concurrency=concurrency)

        closed_ids: list[int] = []
        for candidate, status in checks:
            result.scanned += 1
            if status == "closed":
                closed_ids.append(candidate.id)
            elif status == "alive":
                result.alive += 1
            else:
                result.inconclusive += 1

        if apply:
            _stamp_checked(session, [candidate.id for candidate, _ in checks], detected_at)
            _store_observations(session, checks, observations, detected_at)
            result.closed += _mark_closed(
                session,
                opportunity_ids=closed_ids,
                detected_at=detected_at,
                expected_urls={candidate.id: candidate.apply_url for candidate, _ in checks},
            )
            if checks and commit_each_batch:
                session.commit()
        else:
            result.closed += len(closed_ids)

    return result
