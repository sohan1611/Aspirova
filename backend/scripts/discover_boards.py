"""Discover, rank and verify student-hiring boards; dry-run unless --apply.

Network work finishes before the write session is opened. Reuse run_batch for
company attachment, slug/domain conflicts and idempotent writes.
"""

import argparse
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Iterable
from urllib.parse import parse_qs, unquote, urlsplit

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db import make_engine
from core.models import Company
from crawlers.common import USER_AGENT, build_http_timeout
from crawlers.github_lists import canonical_url, company_domain, fetch_lists
from scripts.seed_boards_batch import (
    BoardCandidate,
    BatchSummary,
    Verification,
    Verifier,
    _print_summary,
    run_batch,
    verify_candidate,
)

MAX_DISCOVERED_BOARD_JOBS = 600
logger = logging.getLogger(__name__)
_GREENHOUSE = re.compile(r"(?:job-)?boards(?:\.eu)?\.greenhouse\.io$")
_WORKDAY = re.compile(r"([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com$")
_LOCALE = re.compile(r"[a-z]{2}[-_][a-z]{2}", re.IGNORECASE)
_TOKEN = re.compile(r"[a-zA-Z0-9_-]+")


def extract_board(url: str) -> tuple[str, str] | None:
    """Parse only recognized public ATS URL shapes; keep case-sensitive site ids."""
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").casefold()
        if parts.scheme not in {"https", "http"} or parts.username or parts.password:
            return None
        path = [unquote(part) for part in parts.path.split("/") if part]
        if _GREENHOUSE.fullmatch(host):
            if path[:2] == ["embed", "job_app"]:
                token = parse_qs(parts.query).get("for", [""])[0]
            else:
                token = path[0] if path else ""
            ats_type = "greenhouse"
        elif host in {
            "jobs.lever.co",
            "jobs.ashbyhq.com",
            "apply.workable.com",
            "jobs.smartrecruiters.com",
        }:
            ats_type = {
                "jobs.lever.co": "lever",
                "jobs.ashbyhq.com": "ashby",
                "apply.workable.com": "workable",
                "jobs.smartrecruiters.com": "smartrecruiters",
            }[host]
            token = path[0] if path else ""
        elif host.endswith(".recruitee.com"):
            ats_type, token = "recruitee", host.removesuffix(".recruitee.com")
        elif match := _WORKDAY.fullmatch(host):
            if path and _LOCALE.fullmatch(path[0]):
                path = path[1:]
            if not path or not _TOKEN.fullmatch(path[0]) or path[0].lower() in {"job", "wday"}:
                return None
            return "workday", f"{match[1]}|{match[2]}|{path[0]}"
        else:
            return None
        return (ats_type, token) if _TOKEN.fullmatch(token) else None
    except (ValueError, TypeError):
        return None


@dataclass(frozen=True)
class DiscoveredBoard:
    candidate: BoardCandidate
    student_listings: int


def discover_candidates(
    records: Iterable[dict[str, Any]],
    companies: Iterable[Company],
) -> list[DiscoveredBoard]:
    known = {
        ((company.ats_type or "").casefold(), (company.ats_board_id or "").casefold())
        for company in companies
        if company.ats_type and company.ats_board_id
    }
    grouped: dict[tuple[str, str], tuple[BoardCandidate, set[str]]] = {}
    for record in records:
        if record.get("active") is not True:
            continue
        url = canonical_url(record.get("url"))
        board = extract_board(url) if url else None
        if board is None or not url:
            continue
        ats_type, token = board
        key = (ats_type.casefold(), token.casefold())
        name = record.get("company_name")
        if key in known or not isinstance(name, str) or not name.strip():
            continue
        if key not in grouped:
            grouped[key] = (
                BoardCandidate(name.strip(), ats_type, token, company_domain(record)),
                set(),
            )
        grouped[key][1].add(url)
    return sorted(
        (DiscoveredBoard(candidate, len(urls)) for candidate, urls in grouped.values()),
        key=lambda board: (
            -board.student_listings,
            board.candidate.ats_type,
            board.candidate.board_token.casefold(),
        ),
    )


def verify_discovered(candidate: BoardCandidate) -> Verification:
    return verify_candidate(candidate, max_jobs=MAX_DISCOVERED_BOARD_JOBS, bogus_control=True)


@dataclass
class DiscoveryPlan:
    selected: list[BoardCandidate] = field(default_factory=list)
    verifications: dict[BoardCandidate, Verification] = field(default_factory=dict)
    rows: list[tuple[DiscoveredBoard, str, int | None]] = field(default_factory=list)


def plan_discovery(
    boards: Iterable[DiscoveredBoard],
    *,
    max_new: int = 40,
    max_verify: int = 150,
    verifier: Verifier = verify_discovered,
) -> DiscoveryPlan:
    if max_new < 0:
        raise ValueError("max_new must be zero or greater")
    if max_verify < 0:
        raise ValueError("max_verify must be zero or greater")
    plan = DiscoveryPlan()
    for board in sorted(
        boards,
        key=lambda item: (
            -item.student_listings,
            item.candidate.ats_type,
            item.candidate.board_token.casefold(),
        ),
    ):
        if len(plan.selected) >= max_new or len(plan.rows) >= max_verify:
            break
        candidate = board.candidate
        try:
            verification = verifier(candidate)
        except Exception as exc:
            verification = Verification(
                candidate, False, "degraded", None, f"raised {type(exc).__name__}: {exc}"
            )
        plan.verifications[candidate] = verification
        count = verification.listings_count
        if (
            candidate.ats_type != "workday"
            and count is not None
            and count > MAX_DISCOVERED_BOARD_JOBS
        ):
            status = "too_large"
            logger.warning(
                "too_large: %s/%s live=%s student_listings=%s",
                candidate.ats_type,
                candidate.board_token,
                count,
                board.student_listings,
            )
        elif (
            verification.accepted
            and verification.health == "ok"
            and count is not None
            and (candidate.ats_type != "workday" or count >= 1)
        ):
            plan.selected.append(candidate)
            status = "verified"
        else:
            status = verification.reason or "rejected"
        plan.rows.append((board, status, count))
    return plan


def apply_plan(session: Session, plan: DiscoveryPlan, *, apply: bool = False) -> BatchSummary:
    return run_batch(
        session,
        plan.selected,
        apply=apply,
        verifier=plan.verifications.__getitem__,
        verify_workers=1,
    )


def main(argv: list[str] | None = None) -> BatchSummary:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--dry-run", action="store_true", help="preview only (default)")
    parser.add_argument("--max-new", type=int, default=40)
    parser.add_argument("--max-verify", type=int, default=150)
    args = parser.parse_args(argv)
    if args.max_new < 0:
        parser.error("--max-new must be zero or greater")
    if args.max_verify < 0:
        parser.error("--max-verify must be zero or greater")
    with httpx.Client(timeout=build_http_timeout(), headers={"User-Agent": USER_AGENT}) as client:
        fetched = fetch_lists(client)
    if fetched.failures:
        print(f"Partial list fetch: {fetched.failures}")
    engine = make_engine()
    try:
        with Session(engine) as session:
            boards = discover_candidates(fetched.records, session.scalars(select(Company)).all())
        plan = plan_discovery(boards, max_new=args.max_new, max_verify=args.max_verify)
        print(f"Verification attempts: {len(plan.rows)}/{args.max_verify}")
        print(f"{'ATS':18} {'BOARD':55} {'STUDENT':>7} {'LIVE':>7} RESULT")
        for board, status, count in plan.rows:
            print(
                f"{board.candidate.ats_type:18} {board.candidate.board_token:55} {board.student_listings:7} {str(count):>7} {status}"
            )
        with Session(engine) as session:
            summary = apply_plan(session, plan, apply=args.apply)
    finally:
        engine.dispose()
    _print_summary(summary, apply=args.apply)
    return summary


if __name__ == "__main__":
    main()
