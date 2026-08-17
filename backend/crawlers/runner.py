"""Crawl runner: for each enabled source at a given tier, crawl every
company it covers, with per-source isolation (Doc 04 sec 7 - one failing
board never aborts the batch) and change detection (Doc 04 sec 6) gating
the expensive parse/dedup work. Invoked by GitHub Actions cron, NEVER by
the API process (Doc 02 sec 3.3 hard rule).

Deliberate Phase-1 simplification: iterates sources/companies directly
rather than claiming work via the crawl_jobs SKIP LOCKED queue. That queue
exists to let multiple parallel matrix runners claim disjoint work once
there are enough sources/companies to need parallelism (Doc 04 sec 4) - at
12 companies and one adapter, a single sequential pass finishes in well
under a minute, so building the parallel-claim path now would be scaling
for anticipated load rather than measured load (Doc 02 sec 5, Doc 08
binding rule). crawl_jobs remains in the schema, unused, until company
count actually justifies it - a real future amendment, not silent drift.
"""

import argparse
import hashlib
import os
import signal
import threading
import time
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from core import models
from core.adapters import RawListing
from core.db import make_engine, verify_connection_guards
from crawlers import watchdog
from crawlers.amazon import AmazonAdapter
from crawlers.arbeitnow import ArbeitnowAdapter
from crawlers.ashby import AshbyAdapter
from crawlers.devpost import DevpostAdapter
from crawlers.greenhouse import GreenhouseAdapter
from crawlers.hackerearth import HackerEarthAdapter
from crawlers.himalayas import HimalayasAdapter
from crawlers.jobicy import JobicyAdapter
from crawlers.recruitee import RecruiteeAdapter
from crawlers.workable import WorkableAdapter
from crawlers.keka import KekaAdapter
from crawlers.lever import LeverAdapter
from crawlers.remoteok import RemoteOkAdapter
from crawlers.smartrecruiters import SmartRecruitersAdapter
from crawlers.unstop import UnstopAdapter
from pipeline.company_resolution import resolve_company
from pipeline.ingest import ingest_one, load_board_state
from pipeline.revalidate import notify_changed
from scripts.match_prestige import match_prestige

# adapter_key (sources.adapter_key, companies.ats_type - same string, Doc
# 04 sec 11) -> adapter class, for the per-company ATS sources. Adding a
# source is adding one entry here plus an adapter module; the crawl/ingest
# pipeline itself never changes (Doc 02 sec 3.3, Doc 04 sec 3).
ATS_ADAPTERS: dict[str, type] = {
    "amazon": AmazonAdapter,
    "greenhouse": GreenhouseAdapter,
    "recruitee": RecruiteeAdapter,
    "workable": WorkableAdapter,
    "keka": KekaAdapter,
    "lever": LeverAdapter,
    "ashby": AshbyAdapter,
    "smartrecruiters": SmartRecruitersAdapter,
}

# adapter_key -> adapter class, for aggregator sources (Doc 04 sec 1: a
# secondary, best-effort tier - never the foundation). Unlike an ATS
# source, one fetch spans many different companies (crawl_aggregator
# below), so these are dispatched separately from ATS_ADAPTERS.
AGGREGATOR_ADAPTERS: dict[str, type] = {
    "arbeitnow": ArbeitnowAdapter,
    "devpost": DevpostAdapter,
    "hackerearth": HackerEarthAdapter,
    "himalayas": HimalayasAdapter,
    "jobicy": JobicyAdapter,
    "remoteok": RemoteOkAdapter,
    "unstop": UnstopAdapter,
}

ATS_FETCH_MAX_WORKERS = 10
DEFAULT_AGGREGATOR_MAX_SECONDS = 7200.0
# Per-source aggregator budget. The group ceiling remains a separate hang
# backstop; it must not turn back into the shared pool that let Unstop consume
# every aggregator minute and starve Devpost/RemoteOK.
DEFAULT_AGGREGATOR_GROUP_MAX_SECONDS = 8700.0
# Soft wall-clock budget for the WHOLE ATS phase (prefetch + ingest), armed
# before the prefetch below. This is no longer an Actions-minute rationing
# guard; the public repo gets standard runners without the old private-repo
# included-minutes ceiling. Keep it under the workflow's ATS step cap only so a
# genuine hang exits cleanly, commits work, and lets aggregator + tail steps run
# instead of being SIGKILL'd at the hard cap. Env-tunable
# (CRAWLER_ATS_MAX_SECONDS).
#
# The gap between this soft budget and the ATS step timeout must exceed the
# SLOWEST SINGLE BOARD, because the deadline only gates whether a board may
# START; once one is in flight it runs to completion. With a 7200s soft budget
# and 150-minute step timeout, that in-flight-board gap remains 30 minutes.
DEFAULT_ATS_MAX_SECONDS = 7200.0
_STOP_REQUESTED = threading.Event()

_FULL_LIST_SOURCE_KEYS = {
    "ashby",
    "greenhouse",
    "keka",
    "lever",
    "recruitee",
    "remoteok",
    "workable",
}


@dataclass(frozen=True)
class _TruncationEvent:
    source: str
    elapsed_seconds: float
    budget_seconds: float


def _format_seconds(seconds: float) -> str:
    return f"{max(seconds, 0.0):.1f}"


def _truncation_line(event: _TruncationEvent) -> str:
    return (
        f"TRUNCATED: {event.source} stopped early after "
        f"{_format_seconds(event.elapsed_seconds)}s "
        f"(budget {_format_seconds(event.budget_seconds)}s)"
    )


def _print_truncation(event: _TruncationEvent) -> None:
    print(_truncation_line(event), flush=True)


def _print_truncation_summary(events: list[_TruncationEvent]) -> None:
    if not events:
        print("TRUNCATION SUMMARY: no sources truncated", flush=True)
        return

    print("TRUNCATION SUMMARY: truncated sources:", flush=True)
    for event in events:
        print(
            "  - "
            f"{event.source}: after {_format_seconds(event.elapsed_seconds)}s "
            f"(budget {_format_seconds(event.budget_seconds)}s)",
            flush=True,
        )


def _coerce_non_negative_int(value: object) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return max(parsed, 0)


def _coverage_record(
    *,
    fetched: int,
    mode: str,
    status: str,
    expected_total: int | None = None,
    note: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "fetched": max(int(fetched), 0),
        "expected_total": expected_total,
        "mode": mode,
        "status": status,
    }
    if note:
        record["note"] = note
    if details:
        record["details"] = details
    return record


def _coverage_from_adapter(
    adapter: object,
    source_key: str,
    fetched: int,
    *,
    health: str,
    stopped_early: bool = False,
) -> dict[str, Any]:
    coverage_method = getattr(adapter, "coverage", None)
    if callable(coverage_method):
        try:
            raw_coverage = coverage_method()
        except Exception as exc:
            return _coverage_record(
                fetched=fetched,
                mode="unknown",
                status="unknown",
                note=f"coverage metadata unavailable: {type(exc).__name__}",
            )
        if isinstance(raw_coverage, dict):
            expected_total = _coerce_non_negative_int(raw_coverage.get("expected_total"))
            mode = str(
                raw_coverage.get("mode")
                or ("declared_total" if expected_total is not None else "unknown")
            )
            note = raw_coverage.get("note")
            details = raw_coverage.get("details")
            status = raw_coverage.get("status")
            if expected_total is not None:
                status = status or (
                    "complete"
                    if health == "ok" and not stopped_early and fetched >= expected_total
                    else "partial"
                )
            else:
                status = status or "unknown"
                note = note or "source declares no total"
            return _coverage_record(
                fetched=fetched,
                expected_total=expected_total,
                mode=mode,
                status=str(status),
                note=str(note) if note else None,
                details=details if isinstance(details, dict) else None,
            )

    if source_key in _FULL_LIST_SOURCE_KEYS:
        if health == "ok" and not stopped_early:
            return _coverage_record(
                fetched=fetched,
                mode="full_list",
                status="complete",
                note="full-list source returned its complete set",
            )
        return _coverage_record(
            fetched=fetched,
            mode="full_list",
            status="unknown",
            note="full-list fetch did not complete cleanly",
        )

    return _coverage_record(
        fetched=fetched,
        mode="unknown",
        status="unknown",
        note="source declares no total",
    )


def _log_with_coverage(base_log: dict[str, Any], coverage: dict[str, Any]) -> dict[str, Any]:
    log = dict(base_log)
    log["coverage"] = coverage
    log["coverage_fetched"] = coverage["fetched"]
    log["coverage_expected_total"] = coverage["expected_total"]
    log["coverage_mode"] = coverage["mode"]
    log["coverage_status"] = coverage["status"]
    if coverage.get("note"):
        log["coverage_note"] = coverage["note"]
    return log


def _record_crawl_run(
    session: Session,
    *,
    source_id: int,
    tier: int | None,
    started_at: datetime,
    status: str,
    listings_found: int,
    new_opps: int,
    errors: int,
    log: dict[str, Any],
) -> None:
    session.add(
        models.CrawlRun(
            source_id=source_id,
            tier=tier,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
            status=status,
            listings_found=listings_found,
            new_opps=new_opps,
            errors=errors,
            log=log,
        )
    )


def _merge_coverage(records: list[dict[str, Any]]) -> dict[str, Any]:
    fetched = sum(int(record.get("fetched") or 0) for record in records)
    if records and all(
        record.get("mode") == "full_list" and record.get("status") == "complete"
        for record in records
    ):
        return _coverage_record(
            fetched=fetched,
            mode="full_list",
            status="complete",
            note="full-list source returned its complete set",
        )

    expected_totals = [_coerce_non_negative_int(record.get("expected_total")) for record in records]
    if records and all(expected_total is not None for expected_total in expected_totals):
        expected_total = sum(expected_total or 0 for expected_total in expected_totals)
        status = "complete" if expected_total == 0 or fetched >= expected_total else "partial"
        return _coverage_record(
            fetched=fetched,
            expected_total=expected_total,
            mode="declared_total",
            status=status,
            note=next(
                (str(record["note"]) for record in records if record.get("note")),
                None,
            ),
        )

    note = next(
        (
            str(record["note"])
            for record in records
            if record.get("status") == "unknown" and record.get("note")
        ),
        "source declares no total",
    )
    return _coverage_record(
        fetched=fetched,
        mode="unknown",
        status="unknown",
        note=note,
    )


def _coverage_line(source_key: str, coverage: dict[str, Any]) -> str:
    fetched = int(coverage.get("fetched") or 0)
    expected_total = _coerce_non_negative_int(coverage.get("expected_total"))
    mode = coverage.get("mode")
    status = coverage.get("status")
    note = str(coverage.get("note") or "source declares no total")

    if mode == "full_list" and status == "complete":
        return f"COVERAGE: {source_key} {fetched} (full-list, complete)"

    if expected_total is not None:
        percentage = 100.0 if expected_total == 0 else (fetched / expected_total) * 100.0
        percentage_text = f"{percentage:.0f}%" if percentage.is_integer() else f"{percentage:.1f}%"
        return f"COVERAGE: {source_key} {fetched}/{expected_total} ({percentage_text})"

    return f"COVERAGE: {source_key} {fetched}/? (UNKNOWN - {note})"


def _print_coverage_summary(coverage_by_source: dict[str, list[dict[str, Any]]]) -> None:
    if not coverage_by_source:
        print("COVERAGE: none/? (UNKNOWN - no sources crawled)", flush=True)
        return

    for source_key, records in coverage_by_source.items():
        print(_coverage_line(source_key, _merge_coverage(records)), flush=True)


def _order_ats_jobs(
    jobs: list["_AtsJob"],
    last_crawled_by_board: dict[tuple[int, str], datetime],
) -> list["_AtsJob"]:
    _stalest_first = datetime.min.replace(tzinfo=timezone.utc)

    def board_sort_key(job: "_AtsJob") -> tuple[datetime, int]:
        return (
            last_crawled_by_board.get((job.source_id, job.board_token), _stalest_first),
            -job.company_id,
        )

    jobs_by_source: dict[int, list["_AtsJob"]] = {}
    for job in jobs:
        jobs_by_source.setdefault(job.source_id, []).append(job)

    for source_jobs in jobs_by_source.values():
        source_jobs.sort(key=board_sort_key)

    # Keep never-crawled boards first within each source, then crawl that
    # source's stalest boards. Interleave sources by their own stalest board so
    # one high-cardinality adapter (Greenhouse/Ashby) cannot consume the whole
    # ATS budget before a one-board source such as Amazon gets a turn.
    # source_id is the final tie-break and is NOT cosmetic: adapter_key is not
    # unique per source, so two sources sharing a stalest timestamp AND an
    # adapter_key tie completely, and a stable sort then falls back to dict
    # insertion order - i.e. the order rows came out of the database. That makes
    # the crawl order vary between runs, which is how starvation becomes
    # intermittent instead of fixed. source_id is unique, so this is total.
    source_order = sorted(
        jobs_by_source,
        key=lambda source_id: (
            board_sort_key(jobs_by_source[source_id][0])[0],
            jobs_by_source[source_id][0].adapter_key,
            source_id,
        ),
    )

    ordered: list[_AtsJob] = []
    while any(jobs_by_source[source_id] for source_id in source_order):
        for source_id in source_order:
            if jobs_by_source[source_id]:
                ordered.append(jobs_by_source[source_id].pop(0))
    return ordered


def _order_aggregator_jobs(
    jobs: list[tuple[int, str]],
    last_crawled_by_source: dict[int, datetime],
) -> list[tuple[int, str]]:
    _stalest_first = datetime.min.replace(tzinfo=timezone.utc)

    # Crawl aggregators stalest-first as a safety net. This used to be
    # load-bearing because the aggregator phase had one shared budget; Unstop
    # exhausted it and left Devpost/RemoteOK untouched for 11 days. Per-source
    # budgets below remove that starvation path, but stale-first remains the
    # right order when a source is behind.
    return sorted(
        jobs,
        key=lambda job: (
            last_crawled_by_source.get(job[0], _stalest_first),
            job[1] == "remoteok",
            job[1],
        ),
    )


@dataclass(frozen=True)
class _AtsJob:
    company_id: int
    source_id: int
    company_slug: str
    adapter_key: str
    board_token: str
    company_name: str


@dataclass(frozen=True)
class _PrefetchedBoard:
    listings: list[RawListing]
    health: str
    coverage: dict[str, Any] | None = None


def _board_fingerprint(raw_listings: list) -> str:
    """Cheap aggregate hash over a board's listings - if unchanged since the
    last crawl, downstream parse/dedup/enrich is skipped entirely (Doc 04
    sec 6, the core cost lever)."""
    parts = sorted(f"{r.external_id}:{r.content_hash}" for r in raw_listings)
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def _is_stop_requested(
    should_stop: Callable[[], bool] | None, deadline_monotonic: float | None = None
) -> bool:
    if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
        return True
    return should_stop() if should_stop is not None else False


def _configured_aggregator_max_seconds() -> float:
    raw_value = os.getenv("AGGREGATOR_MAX_SECONDS")
    if raw_value is None:
        return DEFAULT_AGGREGATOR_MAX_SECONDS

    try:
        max_seconds = float(raw_value)
    except ValueError:
        print(
            "WARNING: AGGREGATOR_MAX_SECONDS must be a number; "
            f"using {DEFAULT_AGGREGATOR_MAX_SECONDS:.0f} seconds",
            flush=True,
        )
        return DEFAULT_AGGREGATOR_MAX_SECONDS

    return max(0.0, max_seconds)


def _configured_aggregator_group_max_seconds() -> float:
    raw_value = os.getenv("AGGREGATOR_GROUP_MAX_SECONDS")
    if raw_value is None:
        return DEFAULT_AGGREGATOR_GROUP_MAX_SECONDS

    try:
        max_seconds = float(raw_value)
    except ValueError:
        print(
            "WARNING: AGGREGATOR_GROUP_MAX_SECONDS must be a number; "
            f"using {DEFAULT_AGGREGATOR_GROUP_MAX_SECONDS:.0f} seconds",
            flush=True,
        )
        return DEFAULT_AGGREGATOR_GROUP_MAX_SECONDS

    return max(0.0, max_seconds)


def _configured_ats_max_seconds() -> float:
    raw_value = os.getenv("CRAWLER_ATS_MAX_SECONDS")
    if raw_value is None:
        return DEFAULT_ATS_MAX_SECONDS

    try:
        max_seconds = float(raw_value)
    except ValueError:
        print(
            "WARNING: CRAWLER_ATS_MAX_SECONDS must be a number; "
            f"using {DEFAULT_ATS_MAX_SECONDS:.0f} seconds",
            flush=True,
        )
        return DEFAULT_ATS_MAX_SECONDS

    return max(0.0, max_seconds)


def _fetch_company_board(
    job: _AtsJob, should_stop: Callable[[], bool] | None = None
) -> _PrefetchedBoard | None:
    """Fetch one ATS board without opening a database session."""
    if _is_stop_requested(should_stop):
        return None

    activity = f"{job.adapter_key}:{job.board_token}"
    watchdog.beat(f"{activity}:fetch-start")
    adapter = ATS_ADAPTERS[job.adapter_key](
        board_token=job.board_token,
        company_name=job.company_name,
    )
    if _is_stop_requested(should_stop):
        return None

    listings = list(adapter.fetch())
    watchdog.beat(f"{activity}:fetched")
    health = adapter.health()
    return _PrefetchedBoard(
        listings=listings,
        health=health,
        coverage=_coverage_from_adapter(
            adapter,
            getattr(adapter, "source_slug", job.adapter_key),
            len(listings),
            health=health,
        ),
    )


def _prefetch_ats_boards(
    ats_jobs: list[_AtsJob], should_stop: Callable[[], bool] | None = None
) -> dict[str, _PrefetchedBoard]:
    """Fetch ATS boards concurrently while keeping all database work out of
    worker threads. A failed board is logged and omitted so it cannot abort
    other boards' fetches or trigger a retry during sequential ingestion.
    """
    if not ats_jobs or _is_stop_requested(should_stop):
        return {}

    prefetched: dict[str, _PrefetchedBoard] = {}
    max_workers = min(ATS_FETCH_MAX_WORKERS, len(ats_jobs))
    jobs = iter(ats_jobs)
    executor = ThreadPoolExecutor(max_workers=max_workers)
    future_to_job = {}

    def submit_next() -> bool:
        if _is_stop_requested(should_stop):
            return False
        try:
            job = next(jobs)
        except StopIteration:
            return False
        future_to_job[executor.submit(_fetch_company_board, job, should_stop)] = job
        return True

    stopped = False
    try:
        for _ in range(max_workers):
            if not submit_next():
                break

        while future_to_job:
            completed, _ = wait(
                future_to_job,
                timeout=0.25,
                return_when=FIRST_COMPLETED,
            )
            for future in completed:
                job = future_to_job.pop(future)
                try:
                    board = future.result()
                    if board is not None:
                        prefetched[job.company_slug] = board
                except Exception as exc:
                    print(
                        f"ERROR: {job.company_slug} fetch failed: {type(exc).__name__}: {exc}",
                        flush=True,
                    )

            stopped = _is_stop_requested(should_stop)
            if stopped:
                break
            while len(future_to_job) < max_workers and submit_next():
                pass
    finally:
        stopped = stopped or _is_stop_requested(should_stop)
        if stopped:
            for future in future_to_job:
                future.cancel()
            executor.shutdown(wait=False, cancel_futures=True)
        else:
            executor.shutdown(wait=True)

    return prefetched


def crawl_company_board(
    session: Session,
    source: models.Source,
    company: models.Company,
    adapter_class: type,
    prefetched: list[RawListing] | None = None,
    prefetched_health: str | None = None,
    prefetched_coverage: dict[str, Any] | None = None,
    should_stop: Callable[[], bool] | None = None,
    changed_slugs: set[str] | None = None,
) -> dict:
    """Crawl one company's board on the given ATS. Never raises - every
    failure mode, including a dropped DB connection mid-crawl, is caught
    and reflected in the returned result, so one broken board cannot abort
    the batch (Doc 04 sec 7).

    Plain values are captured up front rather than re-read from the ORM
    objects after a rollback: a rollback expires SQLAlchemy instances, and
    touching an expired attribute triggers a lazy-reload query - which can
    itself fail if the connection is the thing that broke, raising OUTSIDE
    any try/except and aborting the whole batch. Confirmed live: a transient
    connection drop during one company's crawl took down the entire
    12-company run before this fix.
    """
    source_id = source.id
    tier = source.crawl_tier
    source_label = getattr(source, "adapter_key", getattr(adapter_class, "source_slug", "unknown"))
    board_token = company.ats_board_id
    company_name = company.name
    company_slug = company.slug
    activity = f"{source_label}:{board_token}"

    started_at = datetime.now(timezone.utc)
    result = {
        "listings_found": 0,
        "new_opps": 0,
        "errors": 0,
        "status": "success",
        "changed_slugs": 0,
        "coverage": _coverage_record(
            fetched=0,
            mode="unknown",
            status="unknown",
            note="fetch did not complete",
        ),
    }
    run_changed_slugs = changed_slugs if changed_slugs is not None else set()
    committed_changed_slugs: set[str] = set()

    try:
        adapter = adapter_class(board_token=board_token, company_name=company_name)
        if prefetched is None:
            watchdog.beat(f"{activity}:fetch-start")
            raw_listings = list(adapter.fetch())
            watchdog.beat(f"{activity}:fetched")
        else:
            raw_listings = prefetched
        result["listings_found"] = len(raw_listings)

        health = (
            adapter.health()
            if prefetched is None or prefetched_health is None
            else prefetched_health
        )
        if health == "broken":
            result["status"] = "failed"
        elif health == "degraded":
            result["status"] = "partial"

        fingerprint = _board_fingerprint(raw_listings) if raw_listings else None
        stopped_early = _is_stop_requested(should_stop)
        if stopped_early:
            result["status"] = "partial"
        coverage = prefetched_coverage or _coverage_from_adapter(
            adapter,
            str(source_label),
            result["listings_found"],
            health=health,
            stopped_early=stopped_early,
        )
        result["coverage"] = coverage
        state = session.scalar(
            select(models.SourceState).where(
                models.SourceState.source_id == source_id,
                models.SourceState.page_key == board_token,
            )
        )

        if (
            not stopped_early
            and fingerprint is not None
            and state is not None
            and state.last_content_hash == fingerprint
        ):
            # The skip must still advance both freshness signals, otherwise an
            # unchanged board looks indistinguishable from a vanished one and
            # the expiry sweep below would retire live listings.
            session.execute(
                update(models.Opportunity)
                .where(models.Opportunity.company_id == company.id)
                .values(last_seen_at=func.now())
            )
            state.last_crawled_at = datetime.now(timezone.utc)
            session.commit()
            watchdog.beat(f"{activity}:unchanged-committed")
            try:
                _record_crawl_run(
                    session,
                    source_id=source_id,
                    tier=tier,
                    started_at=started_at,
                    status=result["status"],
                    listings_found=result["listings_found"],
                    new_opps=result["new_opps"],
                    errors=result["errors"],
                    log=_log_with_coverage(
                        {
                            "company_slug": company_slug,
                            "board_token": board_token,
                            "skipped_unchanged": True,
                        },
                        result["coverage"],
                    ),
                )
                session.commit()
            except Exception as exc:
                try:
                    session.rollback()
                except Exception:
                    pass
                print(
                    f"WARNING: failed to record crawl_runs for {company_slug}: {exc}",
                    flush=True,
                )
            return result  # change-detection skip: nothing changed since last crawl

        # One bulk read of this board's existing raw_listings + this
        # company's opportunities/provenance (Doc handoffs/
        # PHASE-2-HANDOFF.md sec 2/5, "Lever 1") - replaces what used to be
        # ~4 of the ~5 per-listing round trips inside ingest_one() with
        # in-memory dict lookups. Reloaded after any rollback below, since
        # a rollback can leave it referencing pending objects (new
        # opportunities/raw_listings from earlier in the same uncommitted
        # batch) that just became invalid/detached.
        board_state = load_board_state(session, source_id, company.id)

        # Commit every BATCH_SIZE listings, not once per company (the
        # original bug) and not once per listing (the first fix). Per-
        # listing commits are correct but were measured live to be far too
        # slow on this network path: one 484-listing company alone consumed
        # most of a 25-minute job, because each commit is a full-durability
        # round-trip and round-trip count - not server processing time - is
        # what's actually slow here. last_seen_at touches are collected and
        # flushed in one bulk UPDATE per company, so per-25 commits mostly
        # flush genuinely changed rows. A failed listing now rolls back only
        # its own batch (still-uncommitted listings earlier in the SAME
        # batch are lost too, not just the failed one), not the whole
        # company - an acceptable, self-healing tradeoff: ingest is
        # idempotent, so anything lost just gets reprocessed on the next
        # 2-hour scheduled crawl, never duplicated or silently dropped.
        BATCH_SIZE = 25
        since_last_commit = 0
        # new_opps is counted as "pending" until its batch actually commits,
        # not the moment ingest_normalized_listing returns - otherwise a
        # later failure in the SAME uncommitted batch rolls back an earlier
        # listing's DB row while result["new_opps"] had already counted it,
        # silently overcounting.
        pending_new_opps = 0
        seen_opportunity_ids: set[int] = set()
        pending_changed_slugs: set[str] = set()

        for raw in raw_listings:
            if _is_stop_requested(should_stop):
                stopped_early = True
                result["status"] = "partial"
                break
            try:
                normalized = adapter.parse(raw)
                _opportunity, is_new = ingest_one(
                    session,
                    board_state,
                    source_id,
                    company.id,
                    raw,
                    normalized,
                    seen_opportunity_ids=seen_opportunity_ids,
                    changed_slugs=pending_changed_slugs,
                )
                since_last_commit += 1
                if is_new:
                    pending_new_opps += 1
                if since_last_commit >= BATCH_SIZE:
                    session.commit()
                    watchdog.beat(f"{activity}:batch-committed")
                    run_changed_slugs.update(pending_changed_slugs)
                    committed_changed_slugs.update(pending_changed_slugs)
                    pending_changed_slugs.clear()
                    result["changed_slugs"] = len(committed_changed_slugs)
                    result["new_opps"] += pending_new_opps
                    since_last_commit = 0
                    pending_new_opps = 0
            except Exception as exc:
                try:
                    session.rollback()
                except Exception:
                    pass
                # See the board_state comment above - a rollback can leave
                # it holding invalid/detached objects from this same
                # uncommitted batch. Reload fresh rather than risk a later
                # listing touching one; if the connection itself is what
                # broke, this raises too and is caught the same way,
                # exactly like every other per-listing failure here.
                try:
                    board_state = load_board_state(session, source_id, company.id)
                except Exception:
                    pass
                since_last_commit = 0
                pending_new_opps = 0
                pending_changed_slugs.clear()
                result["errors"] += 1
                print(
                    f"    listing error ({raw.external_id}): {type(exc).__name__}: {exc}",
                    flush=True,
                )

        if since_last_commit > 0:
            session.commit()
            watchdog.beat(f"{activity}:batch-committed")
            run_changed_slugs.update(pending_changed_slugs)
            committed_changed_slugs.update(pending_changed_slugs)
            pending_changed_slugs.clear()
            result["changed_slugs"] = len(committed_changed_slugs)
            result["new_opps"] += pending_new_opps

        if seen_opportunity_ids:
            ids = list(seen_opportunity_ids)
            for i in range(0, len(ids), 5000):
                session.execute(
                    update(models.Opportunity)
                    .where(models.Opportunity.id.in_(ids[i : i + 5000]))
                    .values(last_seen_at=func.now())
                )

        if _is_stop_requested(should_stop):
            stopped_early = True
            result["status"] = "partial"

        if fingerprint is not None and not stopped_early:
            if state is None:
                state = models.SourceState(source_id=source_id, page_key=board_token)
                session.add(state)
            state.last_content_hash = fingerprint
            state.last_crawled_at = datetime.now(timezone.utc)

        session.commit()
        watchdog.beat(f"{activity}:finished")

    except Exception:
        try:
            session.rollback()
        except Exception:
            pass
        result["status"] = "failed"
        result["errors"] += 1

    try:
        _record_crawl_run(
            session,
            source_id=source_id,
            tier=tier,
            started_at=started_at,
            status=result["status"],
            listings_found=result["listings_found"],
            new_opps=result["new_opps"],
            errors=result["errors"],
            log=_log_with_coverage(
                {"company_slug": company_slug, "board_token": board_token},
                result["coverage"],
            ),
        )
        session.commit()
    except Exception as exc:
        try:
            session.rollback()
        except Exception:
            pass
        print(f"WARNING: failed to record crawl_runs for {company_slug}: {exc}", flush=True)

    return result


def crawl_aggregator(
    session: Session,
    source: models.Source,
    adapter_class: type,
    max_seconds: float | None = None,
    should_stop: Callable[[], bool] | None = None,
    deadline_monotonic: float | None = None,
    changed_slugs: set[str] | None = None,
) -> dict:
    """Crawl a multi-company aggregator source (Doc 04 sec 1: best-effort
    tier; Doc handoffs/PHASE-2-HANDOFF.md sec 2/5, Part 2.5). Structurally
    parallel to crawl_company_board (same fingerprint skip, batch-commit,
    per-listing error isolation, and board_state bulk-read strategy), but
    one fetch spans many different companies, each resolved (matched or
    created, pipeline/company_resolution.py) per listing rather than fixed
    for the whole batch - so board_state is cached per resolved company_id
    instead of loaded once. The two functions are kept separate rather
    than merged into one parameterized version: forcing the fixed-company
    and resolved-per-listing cases through a single control flow would
    obscure the one real difference between them for no benefit given how
    carefully the round-trip/rollback behavior in both was already tuned.

    legal_status is not re-checked here - callers (run_tier) only ever
    pass sources already filtered to legal_status == "ok"; that filter is
    the actual kill switch and lives in exactly one place, not duplicated.
    """
    crawl_started_monotonic = time.monotonic()
    source_label = getattr(
        source,
        "adapter_key",
        getattr(adapter_class, "source_slug", adapter_class.__name__),
    )
    activity = str(source_label)
    source_id = source.id
    tier = source.crawl_tier
    started_at = datetime.now(timezone.utc)
    result = {
        "listings_found": 0,
        "new_opps": 0,
        "errors": 0,
        "status": "success",
        "changed_slugs": 0,
        "stopped_early": False,
        "coverage": _coverage_record(
            fetched=0,
            mode="unknown",
            status="unknown",
            note="fetch did not complete",
        ),
    }
    run_changed_slugs = changed_slugs if changed_slugs is not None else set()
    committed_changed_slugs: set[str] = set()
    stopped_early = False
    budget_seconds = (
        max_seconds
        if max_seconds is not None
        else max((deadline_monotonic or crawl_started_monotonic) - crawl_started_monotonic, 0.0)
    )
    if deadline_monotonic is None and max_seconds is not None:
        deadline_monotonic = crawl_started_monotonic + max_seconds

    def stop_now() -> bool:
        return _is_stop_requested(should_stop, deadline_monotonic)

    try:
        adapter = adapter_class()
        watchdog.beat(f"{activity}:fetch-start")
        stopped_early = stop_now()
        if stopped_early:
            raw_listings: list[RawListing] = []
        elif isinstance(adapter, UnstopAdapter):
            raw_listings = adapter.fetch(
                deadline_monotonic=deadline_monotonic,
                should_stop=stop_now,
            )
        else:
            raw_listings = list(adapter.fetch())
        watchdog.beat(f"{activity}:fetched")

        stopped_early = (
            stopped_early or bool(getattr(adapter, "stopped_early", False)) or stop_now()
        )
        result["listings_found"] = len(raw_listings)

        health = adapter.health()
        if health == "broken":
            result["status"] = "failed"
        elif health == "degraded":
            result["status"] = "partial"
        if stopped_early:
            result["status"] = "partial"
        result["coverage"] = _coverage_from_adapter(
            adapter,
            str(source_label),
            result["listings_found"],
            health=health,
            stopped_early=stopped_early,
        )

        fingerprint = _board_fingerprint(raw_listings) if raw_listings else None
        state = None
        if not stopped_early:
            state = session.scalar(
                select(models.SourceState).where(
                    models.SourceState.source_id == source_id,
                    models.SourceState.page_key == "aggregator",
                )
            )

        if (
            not stopped_early
            and fingerprint is not None
            and state is not None
            and state.last_content_hash == fingerprint
        ):
            state.last_crawled_at = datetime.now(timezone.utc)
            session.commit()
            watchdog.beat(f"{activity}:unchanged-committed")
            try:
                _record_crawl_run(
                    session,
                    source_id=source_id,
                    tier=tier,
                    started_at=started_at,
                    status=result["status"],
                    listings_found=result["listings_found"],
                    new_opps=result["new_opps"],
                    errors=result["errors"],
                    log=_log_with_coverage(
                        {"aggregator": True, "skipped_unchanged": True},
                        result["coverage"],
                    ),
                )
                session.commit()
            except Exception as exc:
                try:
                    session.rollback()
                except Exception:
                    pass
                print(f"WARNING: failed to record crawl_runs for aggregator: {exc}", flush=True)
            return result  # change-detection skip: nothing changed since last crawl

        board_states: dict[int, object] = {}
        BATCH_SIZE = 25
        since_last_commit = 0
        pending_new_opps = 0
        pending_changed_slugs: set[str] = set()

        for raw in raw_listings:
            if stop_now():
                stopped_early = True
                result["status"] = "partial"
                break
            try:
                normalized = adapter.parse(raw)
                company = resolve_company(
                    session, normalized.company_name, normalized.company_domain
                )
                if company.id not in board_states:
                    board_states[company.id] = load_board_state(session, source_id, company.id)
                board_state = board_states[company.id]

                _opportunity, is_new = ingest_one(
                    session,
                    board_state,
                    source_id,
                    company.id,
                    raw,
                    normalized,
                    changed_slugs=pending_changed_slugs,
                )
                since_last_commit += 1
                if is_new:
                    pending_new_opps += 1
                if since_last_commit >= BATCH_SIZE:
                    session.commit()
                    watchdog.beat(f"{activity}:batch-committed")
                    run_changed_slugs.update(pending_changed_slugs)
                    committed_changed_slugs.update(pending_changed_slugs)
                    pending_changed_slugs.clear()
                    result["changed_slugs"] = len(committed_changed_slugs)
                    result["new_opps"] += pending_new_opps
                    since_last_commit = 0
                    pending_new_opps = 0
            except Exception as exc:
                try:
                    session.rollback()
                except Exception:
                    pass
                # Same reasoning as crawl_company_board: a rollback can
                # leave board_states referencing objects (including newly
                # resolved companies) that were pending in this same
                # uncommitted batch and are now invalid/detached. Clear
                # the whole cache rather than risk a later listing
                # touching one.
                board_states = {}
                since_last_commit = 0
                pending_new_opps = 0
                pending_changed_slugs.clear()
                result["errors"] += 1
                print(
                    f"    listing error ({raw.external_id}): {type(exc).__name__}: {exc}",
                    flush=True,
                )

        if since_last_commit > 0:
            session.commit()
            watchdog.beat(f"{activity}:batch-committed")
            run_changed_slugs.update(pending_changed_slugs)
            committed_changed_slugs.update(pending_changed_slugs)
            pending_changed_slugs.clear()
            result["changed_slugs"] = len(committed_changed_slugs)
            result["new_opps"] += pending_new_opps

        if stop_now():
            stopped_early = True
            result["status"] = "partial"
        result["stopped_early"] = stopped_early
        if stopped_early:
            truncation_elapsed_seconds = time.monotonic() - crawl_started_monotonic
            result["truncation_elapsed_seconds"] = truncation_elapsed_seconds
            result["truncation_budget_seconds"] = budget_seconds
            _print_truncation(
                _TruncationEvent(
                    source=str(source_label),
                    elapsed_seconds=truncation_elapsed_seconds,
                    budget_seconds=budget_seconds,
                )
            )

        # An incomplete page set must never become the change-detection
        # fingerprint. Otherwise a later run with the same truncated prefix
        # could skip ingestion forever and leave the remaining pages unseen.
        if fingerprint is not None and not stopped_early:
            if state is None:
                state = models.SourceState(source_id=source_id, page_key="aggregator")
                session.add(state)
            state.last_content_hash = fingerprint
            state.last_crawled_at = datetime.now(timezone.utc)

        session.commit()
        watchdog.beat(f"{activity}:finished")

    except Exception:
        try:
            session.rollback()
        except Exception:
            pass
        result["status"] = "failed"
        result["errors"] += 1

    try:
        _record_crawl_run(
            session,
            source_id=source_id,
            tier=tier,
            started_at=started_at,
            status=result["status"],
            listings_found=result["listings_found"],
            new_opps=result["new_opps"],
            errors=result["errors"],
            log=_log_with_coverage({"aggregator": True}, result["coverage"]),
        )
        session.commit()
    except Exception as exc:
        try:
            session.rollback()
        except Exception:
            pass
        print(f"WARNING: failed to record crawl_runs for aggregator: {exc}", flush=True)

    return result


def _refresh_prestige_matches(engine) -> dict[str, object] | None:
    try:
        with Session(engine) as session:
            result = match_prestige(session)
    except Exception as exc:
        print(
            "WARNING: prestige match after crawl failed: " f"{type(exc).__name__}: {exc}",
            flush=True,
        )
        return None

    print(
        "prestige match after crawl: "
        f"scanned {result['scanned']}, ranked {result['ranked']}, "
        f"unranked {result['unranked']}",
        flush=True,
    )
    return result


def run_tier(
    tier: int,
    group: str = "all",
    *,
    aggregator_max_seconds: float | None = None,
    aggregator_group_max_seconds: float | None = None,
    ats_max_seconds: float | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> None:
    if aggregator_max_seconds is None:
        aggregator_max_seconds = _configured_aggregator_max_seconds()
    if aggregator_group_max_seconds is None:
        aggregator_group_max_seconds = _configured_aggregator_group_max_seconds()
    if ats_max_seconds is None:
        ats_max_seconds = _configured_ats_max_seconds()
    if should_stop is None:
        should_stop = _STOP_REQUESTED.is_set

    changed_slugs: set[str] = set()
    truncations: list[_TruncationEvent] = []
    coverage_by_source: dict[str, list[dict[str, Any]]] = {}

    engine = make_engine()
    # Fail fast if the query-timeout guard is missing; a pooler mismatch must never silently hang.
    verify_connection_guards(engine)
    watchdog.beat(f"{group}:db-guards-verified")

    # Gather the (source_id, company_id) work list with one short-lived
    # session, then process each company with its OWN fresh session below -
    # not one session shared across all 12 companies. A connection that goes
    # bad partway through company N would otherwise carry its damaged state
    # into every company after it, not just N; a fresh session per company
    # means a bad connection costs at most one company; the next gets a
    # clean slate (Doc 04 sec 7 - per-source isolation, extended to cover
    # connection health, not just exceptions).
    with Session(engine) as session:
        # legal_status == "ok" is the kill switch (Doc handoffs/
        # PHASE-2-HANDOFF.md sec 5): flipping any source's legal_status
        # away from "ok" stops it being crawled immediately, no code
        # change or deploy needed - the actual point of a kill switch.
        sources = session.scalars(
            select(models.Source).where(
                models.Source.crawl_tier == tier,
                models.Source.enabled.is_(True),
                models.Source.legal_status == "ok",
            )
        ).all()

        ats_jobs: list[_AtsJob] = []
        aggregator_jobs: list[tuple[int, str]] = []
        for source in sources:
            if group in ("ats", "all") and source.adapter_key in ATS_ADAPTERS:
                companies = session.scalars(
                    select(models.Company).where(models.Company.ats_type == source.adapter_key)
                ).all()
                ats_jobs.extend(
                    _AtsJob(
                        company_id=company.id,
                        source_id=source.id,
                        company_slug=company.slug,
                        adapter_key=source.adapter_key,
                        board_token=company.ats_board_id,
                        company_name=company.name,
                    )
                    for company in companies
                )
            elif group in ("aggregator", "all") and source.adapter_key in AGGREGATOR_ADAPTERS:
                aggregator_jobs.append((source.id, source.adapter_key))
            # else: adapter_key not registered in either dict - skip

        # Crawl the STALEST boards first so the time-boxed ATS loop (below)
        # rotates coverage fairly: a run that runs out of budget leaves the
        # boards it did not reach as the most-stale, so the NEXT run does them
        # first. Without this the fixed order meant the back half of the boards
        # was never crawled at all. One set-based read (not per board): map
        # (source_id, page_key) -> last_crawled_at; never-crawled boards (no
        # SourceState row, last_crawled_at NULL) sort first via datetime.min.
        # Initialised OUTSIDE the `if` on purpose: an aggregator-only run
        # (--group aggregator, which the daily workflow's RemoteOK step uses)
        # produces zero ats_jobs, and binding this only inside the branch made
        # the _order_ats_jobs call below raise UnboundLocalError and kill that
        # whole step. Caught by CI on e75202d.
        last_crawled_by_board: dict[tuple[int, str], datetime] = {}
        if ats_jobs:
            source_ids = {job.source_id for job in ats_jobs}
            for state in session.scalars(
                select(models.SourceState).where(models.SourceState.source_id.in_(source_ids))
            ).all():
                if state.last_crawled_at is not None:
                    last_crawled_by_board[(state.source_id, state.page_key)] = state.last_crawled_at
        # Among equal staleness timestamps, prefer the newest-seeded company
        # so an arbitrary tie cannot leave new boards unreached for days.
        ats_jobs = _order_ats_jobs(ats_jobs, last_crawled_by_board)

        # Read every SourceState row for these sources once, then retain each
        # source's latest crawl time without assuming a particular page_key.
        last_crawled_by_source: dict[int, datetime] = {}
        if aggregator_jobs:
            aggregator_source_ids = {source_id for source_id, _ in aggregator_jobs}
            for state in session.scalars(
                select(models.SourceState).where(
                    models.SourceState.source_id.in_(aggregator_source_ids)
                )
            ).all():
                if state.last_crawled_at is not None:
                    previous_crawl = last_crawled_by_source.get(state.source_id)
                    if previous_crawl is None or state.last_crawled_at > previous_crawl:
                        last_crawled_by_source[state.source_id] = state.last_crawled_at
        aggregator_jobs = _order_aggregator_jobs(aggregator_jobs, last_crawled_by_source)
        watchdog.beat(f"{group}:worklist-loaded")

    # Fetches are pure HTTP and may safely overlap. The gather session above
    # is already closed here; worker threads never receive a Session or ORM
    # object. Ingest remains below in the original one-session-per-board
    # sequence, so the Supabase session-mode pool sees no extra connections.
    # Soft wall-clock budget: stop the ATS loop cleanly before the workflow's
    # hard step cap, so committed boards persist and the aggregator + tail
    # steps still run (a completed, GREEN run) instead of a SIGKILL at the cap.
    # Stalest-first ordering above means the boards skipped here are done first
    # next run. Only armed when there is ATS work (aggregator-only runs skip it).
    #
    # Armed BEFORE the prefetch, not after: the prefetch fetches every board's
    # HTTP up front and took ~3.5min in run 29800767109, so arming it afterward
    # silently pushed the real deadline ~3.5min past where the budget said it
    # was - the run then started a fresh board at ~23min and was SIGKILL'd
    # mid-ingest at the ATS step hard cap. The budget has to cover the phase it
    # bounds.
    ats_started_monotonic = time.monotonic() if ats_jobs else 0.0
    ats_deadline_monotonic = ats_started_monotonic + ats_max_seconds if ats_jobs else 0.0

    prefetched_boards = _prefetch_ats_boards(ats_jobs, should_stop=should_stop)

    for job in ats_jobs:
        if _is_stop_requested(should_stop):
            event = _TruncationEvent(
                source="ATS",
                elapsed_seconds=time.monotonic() - ats_started_monotonic,
                budget_seconds=ats_max_seconds,
            )
            truncations.append(event)
            _print_truncation(event)
            print("Stop requested; ending ATS ingestion after committed work", flush=True)
            break
        now_monotonic = time.monotonic()
        if now_monotonic >= ats_deadline_monotonic:
            event = _TruncationEvent(
                source="ATS",
                elapsed_seconds=now_monotonic - ats_started_monotonic,
                budget_seconds=ats_max_seconds,
            )
            truncations.append(event)
            _print_truncation(event)
            print("ATS time budget reached; ending after committed work", flush=True)
            break

        prefetched = prefetched_boards.get(job.company_slug)
        if prefetched is None:
            # _prefetch_ats_boards already logged the isolated fetch error.
            continue

        # expire_on_commit=False: board_state (loaded once per company in
        # crawl_company_board) holds ORM objects across several batch
        # commits within this same company's crawl - without this, each
        # commit would expire them, and the next listing that touches one
        # would pay a lazy-reload round trip, quietly clawing back the
        # round trips this refactor exists to eliminate.
        with Session(engine, expire_on_commit=False) as session:
            source = session.get(models.Source, job.source_id)
            company = session.scalar(
                select(models.Company).where(models.Company.slug == job.company_slug)
            )
            try:
                result = crawl_company_board(
                    session,
                    source,
                    company,
                    ATS_ADAPTERS[job.adapter_key],
                    prefetched=prefetched.listings,
                    prefetched_health=prefetched.health,
                    prefetched_coverage=prefetched.coverage,
                    should_stop=should_stop,
                    changed_slugs=changed_slugs,
                )
            except Exception as exc:
                # Last-resort safety net: crawl_company_board already
                # catches its own failures, but per-source isolation (Doc
                # 04 sec 7) must hold even against a bug in that handling
                # itself - one company can never take down the batch.
                try:
                    session.rollback()
                except Exception:
                    pass
                print(f"ERROR: {job.company_slug} crawl raised unexpectedly: {exc}", flush=True)
                continue
            print(f"{job.company_slug}: {result}", flush=True)
            watchdog.beat(f"{job.adapter_key}:{job.board_token}:source-finished")
            coverage = result.get("coverage")
            if isinstance(coverage, dict):
                coverage_by_source.setdefault(job.adapter_key, []).append(coverage)

    aggregator_started_monotonic = time.monotonic()
    aggregator_group_deadline_monotonic = (
        aggregator_started_monotonic + aggregator_group_max_seconds
    )

    for job_index, (source_id, adapter_key) in enumerate(aggregator_jobs):
        if _is_stop_requested(should_stop):
            event = _TruncationEvent(
                source="aggregator group",
                elapsed_seconds=time.monotonic() - aggregator_started_monotonic,
                budget_seconds=aggregator_group_max_seconds,
            )
            truncations.append(event)
            _print_truncation(event)
            print("Stop requested; ending aggregator crawl after committed work", flush=True)
            break

        now_monotonic = time.monotonic()
        if now_monotonic >= aggregator_group_deadline_monotonic:
            event = _TruncationEvent(
                source="aggregator group",
                elapsed_seconds=now_monotonic - aggregator_started_monotonic,
                budget_seconds=aggregator_group_max_seconds,
            )
            truncations.append(event)
            _print_truncation(event)
            print("Aggregator time budget reached; ending after committed work", flush=True)
            break

        # A per-source budget alone does NOT guarantee every source runs: with
        # a 7200s per-source budget under an 8700s group ceiling, one slow
        # source can consume 83% of the group and the sources behind it are
        # skipped by the `break` above - the exact starvation that left devpost
        # and remoteok 11 days stale while unstop ate the shared budget.
        #
        # So each source may take at most its FAIR SHARE of the time still
        # remaining, computed fresh each iteration. A source that finishes early
        # hands its unused time to the ones behind it, and no source can spend
        # time that a later source still needs.
        sources_remaining = len(aggregator_jobs) - job_index
        group_time_remaining = aggregator_group_deadline_monotonic - now_monotonic
        fair_share_seconds = group_time_remaining / sources_remaining
        source_budget_seconds = min(aggregator_max_seconds, fair_share_seconds)
        source_deadline_monotonic = now_monotonic + source_budget_seconds
        with Session(engine, expire_on_commit=False) as session:
            source = session.get(models.Source, source_id)
            try:
                result = crawl_aggregator(
                    session,
                    source,
                    AGGREGATOR_ADAPTERS[adapter_key],
                    # The fair share, not the nominal per-source budget, so a
                    # truncation is reported against the budget actually applied.
                    max_seconds=source_budget_seconds,
                    should_stop=should_stop,
                    deadline_monotonic=source_deadline_monotonic,
                    changed_slugs=changed_slugs,
                )
            except Exception as exc:
                try:
                    session.rollback()
                except Exception:
                    pass
                print(
                    f"ERROR: {adapter_key} aggregator crawl raised unexpectedly: {exc}", flush=True
                )
                continue
            print(f"{adapter_key} (aggregator): {result}", flush=True)
            watchdog.beat(f"{adapter_key}:source-finished")
            coverage = result.get("coverage")
            if isinstance(coverage, dict):
                coverage_by_source.setdefault(adapter_key, []).append(coverage)
            if result.get("stopped_early"):
                truncations.append(
                    _TruncationEvent(
                        source=adapter_key,
                        elapsed_seconds=float(result.get("truncation_elapsed_seconds", 0.0)),
                        budget_seconds=float(result.get("truncation_budget_seconds", 0.0)),
                    )
                )

    _refresh_prestige_matches(engine)
    notify_changed(changed_slugs)
    watchdog.beat(f"{group}:revalidation-notified")
    _print_coverage_summary(coverage_by_source)
    _print_truncation_summary(truncations)


def _handle_stop_signal(_signum: int, _frame: object) -> None:
    """Let the active crawl reach its next safe commit/close boundary."""
    _STOP_REQUESTED.set()


def _install_stop_handlers() -> dict[int, object]:
    previous_handlers: dict[int, object] = {}
    for signal_number in (signal.SIGTERM, signal.SIGINT):
        try:
            previous_handlers[signal_number] = signal.getsignal(signal_number)
            signal.signal(signal_number, _handle_stop_signal)
        except ValueError:
            # Signal handlers can only be changed on the main thread. CLI
            # execution is on that thread; this makes direct/test callers
            # harmless if they are not.
            pass
    return previous_handlers


def _restore_stop_handlers(previous_handlers: dict[int, object]) -> None:
    for signal_number, previous_handler in previous_handlers.items():
        signal.signal(signal_number, previous_handler)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tier", type=int, required=True)
    parser.add_argument("--group", choices=("ats", "aggregator", "all"), default="all")
    args = parser.parse_args()
    _STOP_REQUESTED.clear()
    previous_handlers = _install_stop_handlers()
    try:
        with watchdog.watch(on_soft_hang=_STOP_REQUESTED.set):
            watchdog.beat(f"tier-{args.tier}:{args.group}:start")
            run_tier(args.tier, args.group)
    finally:
        _restore_stop_handlers(previous_handlers)


if __name__ == "__main__":
    main()
