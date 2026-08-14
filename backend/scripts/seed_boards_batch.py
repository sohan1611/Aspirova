"""Verify candidate ATS boards, then safely attach or seed their companies.

This is intentionally dry-run by default. A board is accepted solely when
its adapter reports health ``ok``; a well-formed empty board is still valid.
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db import make_engine
from core.models import Company
from crawlers.runner import ATS_ADAPTERS
from pipeline.normalize import normalize_company_name

CANDIDATES_PATH = Path(__file__).resolve().parents[1] / "data" / "company_boards.json"
SUPPORTED_BOARD_ATS_TYPES = frozenset(ATS_ADAPTERS) - {"amazon"}
VERIFY_MAX_WORKERS = 3
VERIFY_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class BoardCandidate:
    company_name: str
    ats_type: str
    board_token: str
    domain: str | None


@dataclass(frozen=True)
class Verification:
    candidate: BoardCandidate
    accepted: bool
    health: str | None
    listings_count: int | None
    reason: str | None = None


@dataclass(frozen=True)
class Conflict:
    candidate: BoardCandidate
    reason: str


@dataclass
class BatchSummary:
    verified: list[Verification] = field(default_factory=list)
    rejected: list[Verification] = field(default_factory=list)
    would_insert: list[BoardCandidate] = field(default_factory=list)
    would_attach: list[BoardCandidate] = field(default_factory=list)
    inserted: list[BoardCandidate] = field(default_factory=list)
    attached: list[BoardCandidate] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)
    unchanged: list[BoardCandidate] = field(default_factory=list)


Verifier = Callable[[BoardCandidate], Verification]


def _required_string(record: dict[object, object], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"candidate {key!r} must be a non-empty string")
    return value.strip()


def load_candidates(path: Path = CANDIDATES_PATH) -> list[BoardCandidate]:
    """Load and validate the board registry before any HTTP or DB work."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not load board candidates from {path}: {exc}") from exc

    if not isinstance(payload, list):
        raise ValueError("board candidates must be a JSON list")

    candidates: list[BoardCandidate] = []
    seen_pairs: set[tuple[str, str]] = set()
    for index, record in enumerate(payload):
        if not isinstance(record, dict):
            raise ValueError(f"candidate {index} must be an object")

        company_name = _required_string(record, "company_name")
        ats_type = _required_string(record, "ats_type")
        board_token = _required_string(record, "board_token")
        domain_value = record.get("domain")
        if domain_value is not None and (
            not isinstance(domain_value, str) or not domain_value.strip()
        ):
            raise ValueError(f"candidate {index} domain must be a non-empty string or null")
        domain = domain_value.strip() if isinstance(domain_value, str) else None

        if ats_type not in SUPPORTED_BOARD_ATS_TYPES:
            supported = ", ".join(sorted(SUPPORTED_BOARD_ATS_TYPES))
            raise ValueError(
                f"candidate {index} has unsupported ats_type {ats_type!r}; use {supported}"
            )

        pair = (ats_type, board_token)
        if pair in seen_pairs:
            raise ValueError(f"duplicate candidate board pair: {ats_type}/{board_token}")
        seen_pairs.add(pair)
        candidates.append(
            BoardCandidate(
                company_name=company_name,
                ats_type=ats_type,
                board_token=board_token,
                domain=domain,
            )
        )

    return candidates


def verify_candidate(
    candidate: BoardCandidate,
    *,
    timeout: float = VERIFY_TIMEOUT_SECONDS,
) -> Verification:
    """Ask the adapter whether a candidate is a valid board, not whether it has jobs."""
    try:
        adapter_class = ATS_ADAPTERS[candidate.ats_type]
        adapter = adapter_class(
            board_token=candidate.board_token,
            company_name=candidate.company_name,
            timeout=timeout,
        )
        listings = list(adapter.fetch())
        health = adapter.health()
    except Exception as exc:
        return Verification(
            candidate=candidate,
            accepted=False,
            health=None,
            listings_count=None,
            reason=f"raised {type(exc).__name__}: {exc}",
        )

    if health != "ok":
        return Verification(
            candidate=candidate,
            accepted=False,
            health=health,
            listings_count=len(listings),
            reason=f"health={health}",
        )
    return Verification(
        candidate=candidate,
        accepted=True,
        health=health,
        listings_count=len(listings),
    )


def _safe_verify(candidate: BoardCandidate, verifier: Verifier) -> Verification:
    try:
        return verifier(candidate)
    except Exception as exc:
        return Verification(
            candidate=candidate,
            accepted=False,
            health=None,
            listings_count=None,
            reason=f"raised {type(exc).__name__}: {exc}",
        )


def verify_candidates(
    candidates: Iterable[BoardCandidate],
    *,
    verifier: Verifier = verify_candidate,
    max_workers: int = VERIFY_MAX_WORKERS,
) -> list[Verification]:
    """Verify boards concurrently, with a deliberately small request cap."""
    candidate_list = list(candidates)
    if not candidate_list:
        return []

    worker_count = max(1, min(max_workers, len(candidate_list)))
    if worker_count == 1:
        return [_safe_verify(candidate, verifier) for candidate in candidate_list]

    results: list[Verification | None] = [None] * len(candidate_list)
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {
            executor.submit(_safe_verify, candidate, verifier): index
            for index, candidate in enumerate(candidate_list)
        }
        for future in as_completed(futures):
            results[futures[future]] = future.result()
    return [result for result in results if result is not None]


def _matching_companies(
    candidate: BoardCandidate,
    companies: Iterable[Company],
) -> list[Company]:
    """Apply every duplicate guard before creating or changing a company."""
    expected_slug = candidate.board_token.lower()
    expected_name = normalize_company_name(candidate.company_name)
    matches: list[Company] = []
    for company in companies:
        if company.slug == expected_slug or company.name_normalized == expected_name:
            matches.append(company)
        elif candidate.domain is not None and company.domain == candidate.domain:
            matches.append(company)
    return matches


def run_batch(
    session: Session,
    candidates: Iterable[BoardCandidate],
    *,
    apply: bool = False,
    limit: int | None = None,
    verifier: Verifier = verify_candidate,
    verify_workers: int = VERIFY_MAX_WORKERS,
) -> BatchSummary:
    """Verify candidates and apply only unambiguous, approved board changes."""
    candidate_list = list(candidates)
    if limit is not None:
        if limit < 0:
            raise ValueError("limit must be zero or greater")
        candidate_list = candidate_list[:limit]

    summary = BatchSummary()
    verifications = verify_candidates(
        candidate_list,
        verifier=verifier,
        max_workers=verify_workers,
    )
    for verification in verifications:
        # Health is the adapter's board-validity contract; listing count is irrelevant.
        if verification.health == "ok":
            summary.verified.append(verification)
        else:
            summary.rejected.append(verification)

    # One read makes duplicate matching consistent for the whole small batch.
    companies = list(session.scalars(select(Company)).all())
    wrote = False
    for verification in summary.verified:
        candidate = verification.candidate
        matches = _matching_companies(candidate, companies)
        if len(matches) > 1:
            summary.conflicts.append(
                Conflict(candidate, "multiple existing companies matched the duplicate guard")
            )
            continue

        if not matches:
            if apply:
                company = Company(
                    slug=candidate.board_token.lower(),
                    name=candidate.company_name,
                    name_normalized=normalize_company_name(candidate.company_name),
                    domain=candidate.domain,
                    ats_type=candidate.ats_type,
                    ats_board_id=candidate.board_token,
                )
                session.add(company)
                companies.append(company)
                summary.inserted.append(candidate)
                wrote = True
            else:
                summary.would_insert.append(candidate)
            continue

        company = matches[0]
        if company.ats_type is None and company.ats_board_id is None:
            if apply:
                company.ats_type = candidate.ats_type
                company.ats_board_id = candidate.board_token
                if company.domain is None:
                    company.domain = candidate.domain
                summary.attached.append(candidate)
                wrote = True
            else:
                summary.would_attach.append(candidate)
        elif (
            company.ats_type == candidate.ats_type and company.ats_board_id == candidate.board_token
        ):
            summary.unchanged.append(candidate)
        else:
            summary.conflicts.append(
                Conflict(
                    candidate,
                    "existing board is "
                    f"{company.ats_type}/{company.ats_board_id}; refusing to overwrite it",
                )
            )

    if apply and wrote:
        session.commit()
    return summary


def _print_summary(summary: BatchSummary, *, apply: bool) -> None:
    for rejected in summary.rejected:
        print(f"rejected {rejected.candidate.company_name}: {rejected.reason}")
    for conflict in summary.conflicts:
        print(f"conflict {conflict.candidate.company_name}: {conflict.reason}")

    insert_label = "inserted" if apply else "would-insert"
    attach_label = "attached" if apply else "would-attach"
    insert_count = len(summary.inserted) if apply else len(summary.would_insert)
    attach_count = len(summary.attached) if apply else len(summary.would_attach)
    print("Batch summary:")
    print(f"  verified: {len(summary.verified)}")
    print(f"  rejected: {len(summary.rejected)}")
    print(f"  {insert_label}: {insert_count}")
    print(f"  {attach_label}: {attach_count}")
    print(f"  conflicts: {len(summary.conflicts)}")
    print(f"  unchanged: {len(summary.unchanged)}")


def main(argv: list[str] | None = None) -> BatchSummary:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="write verified, unambiguous changes")
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="preview changes without writing (default)",
    )
    parser.add_argument("--limit", type=int, metavar="N", help="verify at most N candidates")
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 0:
        parser.error("--limit must be zero or greater")

    candidates = load_candidates()
    engine = make_engine()
    try:
        with Session(engine) as session:
            summary = run_batch(session, candidates, apply=args.apply, limit=args.limit)
    finally:
        engine.dispose()
    _print_summary(summary, apply=args.apply)
    return summary


if __name__ == "__main__":
    main()
