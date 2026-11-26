"""Bounded destination checks, verification refresh and recent-closure rescue.

The scheduled worker uses source cadence, including dated and rolling feeds.
Legacy callers keep the undated-only queue. Only 404/410 and the existing
Greenhouse soft-404 rule close rows; unknown checks never reset verification.
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
from core.freshness import (
    cadence_value,
    verified_expression,
    RESCUE_WINDOW_DAYS,
    RESCUE_RECHECK_HOURS,
    RESCUE_DELAY_SECONDS,
)
from core.listing_safety import without_manual_override, without_safety_flag
from crawlers.common import USER_AGENT, request_with_retries
from crawlers.workday import REQUEST_DELAY_SECONDS, cxs_endpoints, tenant_lock
from pipeline.retirement import ROLLING_WINDOW_SOURCES, meta_without_closed_reason
from pipeline.destination_check import inspect_destination, observation_liveness
from core.destination_facts import (
    classify_destination_facts,
    destination_input_key,
    retain_alive_verification,
)

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
    title: str | None = None


@dataclass
class LivenessResult:
    scanned: int = 0
    closed: int = 0
    alive: int = 0
    inconclusive: int = 0
    timed_out: bool = False
    reopened: int = 0
    gone: int = 0


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

    def observe(self, url: str, client: httpx.Client, *, expected_title: str | None = None) -> dict:
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
            expected_title=expected_title,
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
    try:
        host = urlsplit(url).hostname or ""
    except ValueError:
        host = ""
    if host.endswith(".myworkdayjobs.com"):
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


def _select_freshness_candidates(
    session: Session, *, limit: int, rescue: bool = False, now: datetime
) -> list[LivenessCandidate]:
    """The scheduled service also checks dated listings and partial feeds.

    Legacy callers retain their undated-only queue. The public worker opts in
    to this cadence queue, with bounded recent-closure rescue as a separate run.
    """
    from datetime import timedelta
    from pipeline.expire import FULL_INVENTORY_SOURCES

    checked = cast(models.Opportunity.meta["liveness_checked_at"].astext, DateTime(timezone=True))
    retry_due = or_(
        checked.is_(None),
        checked
        < now
        - func.make_interval(
            0, 0, 0, 0, RESCUE_RECHECK_HOURS if rescue else cadence_value("check_hours")
        ),
    )
    if rescue:
        eligible = (
            (models.Opportunity.closed_at >= now - timedelta(days=RESCUE_WINDOW_DAYS))
            & (models.Opportunity.closed_at <= now)
            & or_(
                models.Opportunity.primary_source.in_(
                    ROLLING_WINDOW_SOURCES | {"workday", "amazon", "hackerearth"}
                ),
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
        ) & (
            verified_expression()
            < now - func.make_interval(0, 0, 0, 0, cadence_value("check_hours"))
        )
    rows = session.execute(
        select(
            models.Opportunity.id,
            models.Opportunity.apply_url,
            models.Company.ats_type,
            models.Company.ats_board_id,
            models.Opportunity.title,
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
        .order_by(
            cadence_value("priority"),
            checked.asc().nulls_first(),
            verified_expression().asc(),
            models.Opportunity.id,
        )
        .limit(limit)
    ).all()
    return [LivenessCandidate(*row) for row in rows]


def _reopen_verified(
    session: Session,
    checks: list[tuple[LivenessCandidate, LivenessStatus]],
    observations: dict[str, dict],
    checked_at: datetime,
    *,
    rescue: bool,
) -> int:
    expected = [
        (c.id, c.apply_url)
        for c, status in checks
        if status == "alive" and observations.get(c.apply_url, {}).get("same_posting") is True
    ]
    if not expected:
        return 0
    result = session.execute(
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
    )
    return int(result.rowcount or 0)


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
            models.Opportunity.last_seen_at <= detected_at,
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
    candidates = (
        _select_freshness_candidates(session, limit=limit, rescue=rescue, now=detected_at)
        if freshness_mode or rescue
        else _select_candidates(session, limit=limit)
    )
    result = LivenessResult()
    workday_checker = WorkdayLivenessChecker()
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
        titles = {candidate.apply_url: candidate.title for candidate in batch}

        # Nothing may hold a database transaction open across the network
        # checks. Selecting candidates (and the script's SET) starts a
        # transaction, and a batch of slow or dripping URLs can run past the
        # 120s idle_in_transaction_session_timeout from core/db.py. Postgres
        # then kills the connection and the stamp UPDATE after the batch dies
        # with IdleInTransactionSessionTimeout (crawls 44569209726 and
        # 44703841666). Later batches start clean because each batch commits;
        # this covers the first one. crawlers/runner.py does the same before
        # its fetch. A dry run never writes after the checks, so it is left be.
        if commit_each_batch:
            session.commit()

        def observe(url: str) -> LivenessStatus:
            if rescue:
                # Rescue is serial in the worker, at most one posting per second.
                sleep(RESCUE_DELAY_SECONDS)
            observation = fetch_destination_observation(
                url,
                client,
                workday_checker=workday_checker,
                allowed_board=boards.get(url),
                expected_title=titles.get(url),
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
            # Legacy injected statuses carry no HTTP evidence. Never invent a
            # 2xx observation from "alive" (old checkers can include redirects).

        closed_ids: list[int] = []
        for candidate, status in checks:
            result.scanned += 1
            if status == "closed":
                result.gone += 1
                closed_ids.append(candidate.id)
            elif status == "alive":
                result.alive += 1
            else:
                result.inconclusive += 1

        if apply:
            _stamp_checked(session, [candidate.id for candidate, _ in checks], detected_at)
            _store_observations(session, checks, observations, detected_at)
            result.reopened += _reopen_verified(
                session, checks, observations, detected_at, rescue=rescue
            )
            result.closed += _mark_closed(
                session,
                opportunity_ids=closed_ids,
                detected_at=detected_at,
                expected_urls={candidate.id: candidate.apply_url for candidate, _ in checks},
            )
            if checks and commit_each_batch:
                session.commit()
            if changed_slugs is not None:
                changed_slugs.update(slugs[c.id] for c, _ in checks if c.id in slugs)
        else:
            result.closed += len(closed_ids)
            if rescue:
                result.reopened += sum(
                    status == "alive"
                    and observations.get(c.apply_url, {}).get("same_posting") is True
                    for c, status in checks
                )

    return result
