"""Bounded liveness checks for active undated listings.

This covers the small slice of listings that cannot be refreshed by deadline
logic and have not been confirmed by a real crawl in the last four days. Only
404/410 responses mark a listing closed; every blocked or transient response is
left untouched.
"""

from collections.abc import Callable, Iterable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime, timezone
from time import monotonic
from typing import Literal

import httpx
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from core import models
from crawlers.common import USER_AGENT

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


def _classify_status_code(status_code: int) -> LivenessStatus:
    if status_code in {404, 410}:
        return "closed"
    if 200 <= status_code < 400:
        return "alive"
    return "inconclusive"


def _fetch_liveness_status(apply_url: str, client: httpx.Client) -> LivenessStatus:
    try:
        response = client.get(apply_url)
    except httpx.RequestError:
        return "inconclusive"
    return _classify_status_code(response.status_code)


def _select_candidates(session: Session, *, limit: int) -> list[LivenessCandidate]:
    rows = session.execute(
        select(models.Opportunity.id, models.Opportunity.apply_url)
        .where(
            models.Opportunity.status == "active",
            models.Opportunity.deadline.is_(None),
            models.Opportunity.closed_at.is_(None),
            models.Opportunity.last_seen_at < func.now() - text("interval '4 days'"),
        )
        .order_by(models.Opportunity.last_seen_at.asc(), models.Opportunity.id.asc())
        .limit(limit)
    ).all()
    return [LivenessCandidate(id=row.id, apply_url=row.apply_url) for row in rows]


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


def _mark_closed(session: Session, *, opportunity_ids: list[int], detected_at: datetime) -> int:
    if not opportunity_ids:
        return 0
    result = session.execute(
        update(models.Opportunity)
        .where(
            models.Opportunity.id.in_(opportunity_ids),
            models.Opportunity.status == "active",
            models.Opportunity.closed_at.is_(None),
        )
        .values(closed_at=detected_at)
        .execution_options(synchronize_session=False)
    )
    return int(result.rowcount or 0)


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
    """Check stale undated listings and optionally mark confirmed 404/410s closed."""
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
    candidates = _select_candidates(session, limit=limit)
    result = LivenessResult()

    for batch in _chunks(candidates, batch_size):
        elapsed_seconds = monotonic() - started_at
        if elapsed_seconds >= max_seconds or (
            checker is None
            and elapsed_seconds + _estimated_batch_seconds(len(batch), concurrency) > max_seconds
        ):
            result.timed_out = True
            break

        if checker is None:
            with httpx.Client(
                headers={"User-Agent": USER_AGENT},
                timeout=HTTP_TIMEOUT_SECONDS,
                follow_redirects=True,
            ) as client:
                checks = _check_candidates(
                    batch,
                    checker=lambda url: _fetch_liveness_status(url, client),
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
            result.closed += _mark_closed(
                session,
                opportunity_ids=closed_ids,
                detected_at=detected_at,
            )
            if closed_ids and commit_each_batch:
                session.commit()
        else:
            result.closed += len(closed_ids)

    return result
