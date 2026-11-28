"""Fail-safe absence retirement, independent of contact/coverage reporting."""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median

from sqlalchemy import select
from sqlalchemy.orm import Session

from core import models

BASELINE_RUNS = 7
MIN_BASELINE_FRACTION = 0.5
BOARD_INVENTORY_SOURCES = frozenset(
    {
        "greenhouse",
        "lever",
        "ashby",
        "smartrecruiters",
        "recruitee",
        "workable",
        "keka",
    }
)


def permits_absence(latest: dict, history: list[dict]) -> bool:
    if (
        latest.get("status") != "success"
        or latest.get("finished_at") is None
        or latest.get("errors")
    ):
        return False
    coverage = (latest.get("log") or {}).get("coverage")
    if coverage is not None and coverage.get("status") != "complete":
        return False
    found = latest.get("listings_found")
    if found is None or found <= 0:
        return False
    baseline = [
        run["listings_found"]
        for run in history
        if run.get("status") == "success"
        and not run.get("errors")
        and run.get("finished_at") is not None
        and run.get("listings_found")
        and ((run.get("log") or {}).get("coverage") or {}).get("status", "complete") == "complete"
    ][:BASELINE_RUNS]
    return not baseline or found >= median(baseline) * MIN_BASELINE_FRACTION


def blocked_absence_scopes(
    session: Session, *, inventory_sources: frozenset[str]
) -> tuple[set[int], list[tuple[int, str]]]:
    # Batch maintenance only: narrow crawl history, never opportunity row locks.
    rows = session.execute(
        select(
            models.CrawlRun.source_id,
            models.CrawlRun.status,
            models.CrawlRun.finished_at,
            models.CrawlRun.errors,
            models.CrawlRun.listings_found,
            models.CrawlRun.log,
        )
        .join(models.Source, models.Source.id == models.CrawlRun.source_id)
        .where(models.Source.adapter_key.in_(inventory_sources | BOARD_INVENTORY_SOURCES))
        .where(models.CrawlRun.started_at >= datetime.now(timezone.utc) - timedelta(days=30))
        .order_by(models.CrawlRun.started_at.desc(), models.CrawlRun.id.desc())
    ).mappings()
    scopes = defaultdict(list)
    batches = {}
    for row in rows:
        log = row["log"] or {}
        if log.get("freshness_batch"):
            batches.setdefault(row["source_id"], row)
        else:
            scopes[(row["source_id"], log.get("board_token"))].append(dict(row))
    sources = {key for key, row in batches.items() if row["status"] != "success"}
    boards = []
    for (source_id, token), runs in scopes.items():
        if not permits_absence(runs[0], runs[1:]):
            if token is None:
                sources.add(source_id)
            else:
                boards.append((source_id, token))
    print(
        f"ABSENCE BREAKER: scopes={len(scopes)} blocked_sources={len(sources)} blocked_boards={len(boards)}",
        flush=True,
    )
    if sources or boards:
        print(
            f"::warning::Absence retirement held: source_scopes={len(sources)} board_scopes={len(boards)}",
            flush=True,
        )
    return sources, boards
