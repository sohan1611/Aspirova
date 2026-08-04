"""Weekly verification report for the curated programmes registry.

The job flags records for human review. It never promotes an edition to open.
"""

from collections.abc import Callable, Iterable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import re
from time import monotonic

import httpx
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from core import models
from crawlers.common import USER_AGENT
from pipeline.liveness import (
    DEFAULT_CONCURRENCY,
    HTTP_TIMEOUT_SECONDS,
    LivenessStatus,
    fetch_url_liveness_status,
)

DEFAULT_PROGRAMME_LIMIT = 200
DEFAULT_PROGRAMME_MAX_SECONDS = 60
DEFAULT_PROGRAMME_BATCH_SIZE = 20
STALE_VERIFICATION_DAYS = 90
PROGRAMMES_PATH = Path(__file__).resolve().parents[1] / "data" / "programmes.json"
PROGRAMME_REVIEW_MONTHS_BY_SLUG: dict[str, tuple[int, ...]] = {
    programme["slug"]: tuple(review_months)
    for programme in json.loads(PROGRAMMES_PATH.read_text(encoding="utf-8"))["programmes"]
    if isinstance(review_months := programme.get("review_months"), list) and review_months
}

_MONTH_ALIASES = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}
_MONTH_RE = re.compile(
    r"\b(" + "|".join(sorted(_MONTH_ALIASES, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ProgrammeReviewItem:
    programme_id: int
    programme_slug: str
    programme_name: str
    reason: str
    programme_url: str | None = None


@dataclass(frozen=True, slots=True)
class ProgrammeEditionReviewItem:
    programme_id: int
    edition_id: int
    programme_slug: str
    programme_name: str
    year: int
    status: str
    reason: str
    programme_url: str | None = None
    source_url: str | None = None


@dataclass(frozen=True, slots=True)
class ProgrammeReviewReport:
    dead_urls: list[ProgrammeReviewItem] = field(default_factory=list)
    window_arrived: list[ProgrammeEditionReviewItem] = field(default_factory=list)
    stale_verification: list[ProgrammeEditionReviewItem] = field(default_factory=list)
    overdue_close: list[ProgrammeEditionReviewItem] = field(default_factory=list)
    missing_current_year_edition: list[ProgrammeReviewItem] = field(default_factory=list)
    liveness_scanned: int = 0
    liveness_alive: int = 0
    liveness_inconclusive: int = 0
    liveness_timed_out: bool = False
    closed_updated: int = 0

    @property
    def total_flags(self) -> int:
        return (
            len(self.dead_urls)
            + len(self.window_arrived)
            + len(self.stale_verification)
            + len(self.overdue_close)
            + len(self.missing_current_year_edition)
        )


@dataclass(frozen=True, slots=True)
class _ProgrammeUrlCandidate:
    id: int
    slug: str
    name: str
    url: str


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def extract_months_from_typical_window(typical_window: str | None) -> set[int]:
    """Extract full month names and three-letter abbreviations from free text."""
    if not typical_window:
        return set()
    return {_MONTH_ALIASES[match.group(1).lower()] for match in _MONTH_RE.finditer(typical_window)}


def typical_window_needs_review(typical_window: str | None, *, now: datetime) -> bool:
    months = extract_months_from_typical_window(typical_window)
    if not months:
        return False

    current_month = _as_utc(now).month
    previous_month = 12 if current_month == 1 else current_month - 1
    return bool(months & {current_month, previous_month})


def _month_names(months: set[int]) -> str:
    names = [
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    ]
    return ", ".join(names[month - 1] for month in sorted(months))


def _chunks(
    candidates: list[_ProgrammeUrlCandidate], batch_size: int
) -> Iterable[list[_ProgrammeUrlCandidate]]:
    for index in range(0, len(candidates), batch_size):
        yield candidates[index : index + batch_size]


def _estimated_batch_seconds(candidate_count: int, concurrency: int) -> float:
    waves = (candidate_count + concurrency - 1) // concurrency
    return waves * HTTP_TIMEOUT_SECONDS


def _select_url_candidates(session: Session, *, limit: int) -> list[_ProgrammeUrlCandidate]:
    rows = session.execute(
        select(
            models.Programme.id,
            models.Programme.slug,
            models.Programme.name,
            models.Programme.url,
        )
        .where(models.Programme.is_active.is_(True))
        .order_by(models.Programme.id.asc())
        .limit(limit)
    ).all()
    return [
        _ProgrammeUrlCandidate(id=row.id, slug=row.slug, name=row.name, url=row.url) for row in rows
    ]


def _check_url_candidates(
    candidates: list[_ProgrammeUrlCandidate],
    *,
    checker: Callable[[str], LivenessStatus],
    concurrency: int,
) -> list[tuple[_ProgrammeUrlCandidate, LivenessStatus]]:
    if not candidates:
        return []

    max_workers = min(concurrency, len(candidates))
    results: list[tuple[_ProgrammeUrlCandidate, LivenessStatus]] = []
    executor = ThreadPoolExecutor(max_workers=max_workers)
    future_to_candidate = {
        executor.submit(checker, candidate.url): candidate for candidate in candidates
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


def _programme_item(programme: models.Programme, reason: str) -> ProgrammeReviewItem:
    return ProgrammeReviewItem(
        programme_id=programme.id,
        programme_slug=programme.slug,
        programme_name=programme.name,
        programme_url=programme.url,
        reason=reason,
    )


def _edition_item(
    programme: models.Programme, edition: models.ProgrammeEdition, reason: str
) -> ProgrammeEditionReviewItem:
    return ProgrammeEditionReviewItem(
        programme_id=programme.id,
        edition_id=edition.id,
        programme_slug=programme.slug,
        programme_name=programme.name,
        programme_url=programme.url,
        year=edition.year,
        status=edition.status,
        source_url=edition.source_url,
        reason=reason,
    )


def _find_dead_urls(
    session: Session,
    *,
    limit: int,
    max_seconds: int,
    concurrency: int,
    batch_size: int,
    checker: Callable[[str], LivenessStatus] | None,
) -> tuple[list[ProgrammeReviewItem], int, int, int, bool]:
    started_at = monotonic()
    candidates = _select_url_candidates(session, limit=limit)
    dead_urls: list[ProgrammeReviewItem] = []
    scanned = 0
    alive = 0
    inconclusive = 0
    timed_out = False

    for batch in _chunks(candidates, batch_size):
        elapsed_seconds = monotonic() - started_at
        if elapsed_seconds >= max_seconds or (
            checker is None
            and elapsed_seconds + _estimated_batch_seconds(len(batch), concurrency) > max_seconds
        ):
            timed_out = True
            break

        if checker is None:
            with httpx.Client(
                headers={"User-Agent": USER_AGENT},
                timeout=HTTP_TIMEOUT_SECONDS,
                follow_redirects=True,
            ) as client:
                checks = _check_url_candidates(
                    batch,
                    checker=lambda url: fetch_url_liveness_status(url, client),
                    concurrency=concurrency,
                )
        else:
            checks = _check_url_candidates(batch, checker=checker, concurrency=concurrency)

        for candidate, status in checks:
            scanned += 1
            if status == "closed":
                dead_urls.append(
                    ProgrammeReviewItem(
                        programme_id=candidate.id,
                        programme_slug=candidate.slug,
                        programme_name=candidate.name,
                        programme_url=candidate.url,
                        reason="programme URL confirmed dead by HTTP liveness (404/410)",
                    )
                )
            elif status == "alive":
                alive += 1
            else:
                inconclusive += 1

    return dead_urls, scanned, alive, inconclusive, timed_out


def _select_overdue_close_items(
    session: Session, *, now: datetime
) -> list[ProgrammeEditionReviewItem]:
    rows = session.execute(
        select(models.Programme, models.ProgrammeEdition)
        .join(
            models.ProgrammeEdition,
            models.ProgrammeEdition.programme_id == models.Programme.id,
        )
        .where(
            models.Programme.is_active.is_(True),
            models.ProgrammeEdition.status.in_(("open", "announced")),
            models.ProgrammeEdition.closes_at.is_not(None),
            models.ProgrammeEdition.closes_at < now,
        )
        .order_by(
            models.Programme.slug.asc(),
            models.ProgrammeEdition.year.desc(),
            models.ProgrammeEdition.id.asc(),
        )
    ).all()
    return [
        _edition_item(
            programme,
            edition,
            "status is open/announced and closes_at is strictly in the past",
        )
        for programme, edition in rows
    ]


def _close_overdue_editions(session: Session, *, edition_ids: list[int], now: datetime) -> int:
    if not edition_ids:
        return 0
    result = session.execute(
        update(models.ProgrammeEdition)
        .where(
            models.ProgrammeEdition.id.in_(edition_ids),
            models.ProgrammeEdition.status.in_(("open", "announced")),
            models.ProgrammeEdition.closes_at.is_not(None),
            models.ProgrammeEdition.closes_at < now,
        )
        .values(status="closed", verified_at=now)
    )
    session.flush()
    return int(result.rowcount or 0)


def _select_window_arrived_items(
    session: Session, *, now: datetime
) -> list[ProgrammeEditionReviewItem]:
    rows = session.execute(
        select(models.Programme, models.ProgrammeEdition)
        .join(
            models.ProgrammeEdition,
            models.ProgrammeEdition.programme_id == models.Programme.id,
        )
        .where(
            models.Programme.is_active.is_(True),
            models.ProgrammeEdition.status == "expected",
        )
        .order_by(
            models.Programme.slug.asc(),
            models.ProgrammeEdition.year.desc(),
            models.ProgrammeEdition.id.asc(),
        )
    ).all()

    items: list[ProgrammeEditionReviewItem] = []
    current_month = _as_utc(now).month
    for programme, edition in rows:
        review_months = PROGRAMME_REVIEW_MONTHS_BY_SLUG.get(programme.slug)
        if review_months:
            if current_month not in review_months:
                continue
            items.append(
                _edition_item(
                    programme,
                    edition,
                    "expected edition and configured review_months are "
                    f"{_month_names(set(review_months))}; current review month is configured",
                )
            )
            continue

        months = extract_months_from_typical_window(programme.typical_window)
        if not typical_window_needs_review(programme.typical_window, now=now):
            continue
        items.append(
            _edition_item(
                programme,
                edition,
                "expected edition and typical_window mentions "
                f"{_month_names(months)} near the current review month",
            )
        )
    return items


def _select_stale_verification_items(
    session: Session, *, now: datetime
) -> list[ProgrammeEditionReviewItem]:
    stale_before = now - timedelta(days=STALE_VERIFICATION_DAYS)
    # A null verified_at is the seeded default, not decayed verification: it has
    # never claimed to be verified, so seasonal review brings it up at the right time.
    rows = session.execute(
        select(models.Programme, models.ProgrammeEdition)
        .join(
            models.ProgrammeEdition,
            models.ProgrammeEdition.programme_id == models.Programme.id,
        )
        .where(
            models.Programme.is_active.is_(True),
            models.ProgrammeEdition.verified_at.is_not(None),
            models.ProgrammeEdition.verified_at < stale_before,
        )
        .order_by(
            models.Programme.slug.asc(),
            models.ProgrammeEdition.year.desc(),
            models.ProgrammeEdition.id.asc(),
        )
    ).all()

    items: list[ProgrammeEditionReviewItem] = []
    for programme, edition in rows:
        reason = (
            f"verified_at is older than {STALE_VERIFICATION_DAYS} days: "
            f"{_as_utc(edition.verified_at).date().isoformat()}"
        )
        items.append(_edition_item(programme, edition, reason))
    return items


def _select_missing_current_year_items(
    session: Session, *, current_year: int
) -> list[ProgrammeReviewItem]:
    has_current_edition = (
        select(models.ProgrammeEdition.id)
        .where(
            models.ProgrammeEdition.programme_id == models.Programme.id,
            models.ProgrammeEdition.year == current_year,
        )
        .exists()
    )
    programmes = session.scalars(
        select(models.Programme)
        .where(
            models.Programme.is_active.is_(True),
            ~has_current_edition,
        )
        .order_by(models.Programme.slug.asc())
    ).all()
    return [
        _programme_item(programme, f"no edition row exists for {current_year}")
        for programme in programmes
    ]


def verify_programmes(
    session: Session,
    *,
    apply: bool = False,
    limit: int = DEFAULT_PROGRAMME_LIMIT,
    max_seconds: int = DEFAULT_PROGRAMME_MAX_SECONDS,
    concurrency: int = DEFAULT_CONCURRENCY,
    batch_size: int = DEFAULT_PROGRAMME_BATCH_SIZE,
    now: datetime | None = None,
    checker: Callable[[str], LivenessStatus] | None = None,
) -> ProgrammeReviewReport:
    """Build the needs-review report and optionally close overdue editions."""
    if limit < 1:
        raise ValueError("limit must be at least 1")
    if max_seconds < 1:
        raise ValueError("max_seconds must be at least 1")
    if concurrency < 1:
        raise ValueError("concurrency must be at least 1")
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")

    current = _as_utc(now or datetime.now(UTC))
    dead_urls, scanned, alive, inconclusive, timed_out = _find_dead_urls(
        session,
        limit=limit,
        max_seconds=max_seconds,
        concurrency=concurrency,
        batch_size=batch_size,
        checker=checker,
    )
    overdue_close = _select_overdue_close_items(session, now=current)
    closed_updated = 0
    if apply:
        closed_updated = _close_overdue_editions(
            session,
            edition_ids=[item.edition_id for item in overdue_close],
            now=current,
        )

    return ProgrammeReviewReport(
        dead_urls=dead_urls,
        window_arrived=_select_window_arrived_items(session, now=current),
        stale_verification=_select_stale_verification_items(session, now=current),
        overdue_close=overdue_close,
        missing_current_year_edition=_select_missing_current_year_items(
            session, current_year=current.year
        ),
        liveness_scanned=scanned,
        liveness_alive=alive,
        liveness_inconclusive=inconclusive,
        liveness_timed_out=timed_out,
        closed_updated=closed_updated,
    )
