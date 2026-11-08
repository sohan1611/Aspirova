"""Conservative retirement from repeated board death or rolling-feed age."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from core import models

DEAD_BOARD_MIN_RUNS = 3
DEAD_BOARD_MIN_SPAN_HOURS = 48
ROLLING_WINDOW_SOURCES = frozenset({"remoteok", "himalayas", "arbeitnow", "jobicy"})
ROLLING_WINDOW_TTL_DAYS = 30
"""This is NOT absence-as-evidence: rolling feeds expose only their newest
window. An unconfirmed listing is presumed expired after 30 days, just as
exclude_stale_opportunities presumes age. A source outage freezes closure.
"""


@dataclass(frozen=True)
class DeadBoard:
    source_id: int
    ats: str
    token: str
    state: str
    since: datetime


def aggregator_primary_provenance() -> ColumnElement[bool]:
    """An ATS crawl cannot prove absence from a company's aggregator listings."""
    aggregator = (
        select(models.Source.id)
        .where(
            models.Source.adapter_key == models.Opportunity.primary_source,
            models.Source.type == "aggregator",
        )
        .correlate(models.Opportunity)
        .exists()
    )
    return or_(
        func.coalesce(models.Opportunity.primary_source.in_(ROLLING_WINDOW_SOURCES), False),
        aggregator,
    )


def find_dead_boards(
    session: Session | Connection, *, now: datetime | None = None
) -> list[DeadBoard]:
    """Rank ALL board runs, including errors and legacy unclassified runs."""
    checked_at = now or datetime.now(timezone.utc)
    token = models.CrawlRun.log["board_token"].astext
    ranked = (
        select(
            models.CrawlRun.source_id.label("source_id"),
            models.Source.adapter_key.label("ats"),
            token.label("token"),
            models.CrawlRun.log["board_state"].astext.label("state"),
            models.CrawlRun.status.label("status"),
            models.CrawlRun.started_at.label("started_at"),
            func.row_number()
            .over(
                partition_by=(models.CrawlRun.source_id, token),
                order_by=(models.CrawlRun.started_at.desc(), models.CrawlRun.id.desc()),
            )
            .label("rank"),
        )
        .join(models.Source, models.Source.id == models.CrawlRun.source_id)
        .where(token.is_not(None))
        .subquery()
    )
    rows = session.execute(select(ranked).where(ranked.c.rank <= DEAD_BOARD_MIN_RUNS)).mappings()
    by_board = defaultdict(list)
    for row in rows:
        by_board[(row["source_id"], row["ats"], row["token"])].append(row)
    dead = []
    for (source_id, ats, board_token), runs in sorted(by_board.items()):
        if len(runs) != DEAD_BOARD_MIN_RUNS:
            continue
        if any(
            run["state"] not in {"not_found", "empty"} or run["status"] in {"failed", "error"}
            for run in runs
        ):
            continue
        times = [run["started_at"] for run in runs]
        if any(value is None for value in times):
            continue
        oldest, newest = min(times), max(times)
        if not checked_at - timedelta(days=2) <= newest <= checked_at:
            continue
        if newest - oldest < timedelta(hours=DEAD_BOARD_MIN_SPAN_HOURS):
            continue
        latest = min(runs, key=lambda run: run["rank"])
        dead.append(DeadBoard(source_id, ats, board_token, latest["state"], oldest))
    return dead


def _board_url_matches(column: Any, ats: str, token: str) -> ColumnElement[bool]:
    """Require a board-qualified URL; external job IDs alone are not board IDs."""
    prefixes = {
        "greenhouse": (
            f"https://boards.greenhouse.io/{token}/",
            f"https://job-boards.greenhouse.io/{token}/",
        ),
        "lever": (f"https://jobs.lever.co/{token}/", f"https://jobs.eu.lever.co/{token}/"),
        "ashby": (f"https://jobs.ashbyhq.com/{token}/",),
        "smartrecruiters": (f"https://jobs.smartrecruiters.com/{token}/",),
        "workable": (f"https://apply.workable.com/{token}/",),
        "recruitee": (f"https://{token}.recruitee.com/",),
        "keka": (f"https://{token}.keka.com/careers/",),
    }.get(ats, ())
    return or_(False, *(column.istartswith(prefix, autoescape=True) for prefix in prefixes))


def retire_dead_board_listings(session: Session, *, now: datetime | None = None) -> dict[str, int]:
    """Close only rows attributable to the dead board, never other provenance."""
    counts = {}
    for board in find_dead_boards(session, now=now):
        board_link = (
            select(models.OpportunitySource.id)
            .where(
                models.OpportunitySource.opportunity_id == models.Opportunity.id,
                models.OpportunitySource.source_id == board.source_id,
                _board_url_matches(models.OpportunitySource.source_url, board.ats, board.token),
            )
            .exists()
        )
        other_link = (
            select(models.OpportunitySource.id)
            .where(
                models.OpportunitySource.opportunity_id == models.Opportunity.id,
                or_(
                    models.OpportunitySource.source_id != board.source_id,
                    # Unknown/missing URLs also fail safe.
                    ~func.coalesce(
                        _board_url_matches(
                            models.OpportunitySource.source_url, board.ats, board.token
                        ),
                        False,
                    ),
                ),
            )
            .exists()
        )
        result = session.execute(
            update(models.Opportunity)
            .where(
                models.Opportunity.status == "active",
                models.Opportunity.closed_at.is_(None),
                models.Opportunity.company_id == models.Company.id,
                models.Company.ats_type == board.ats,
                models.Company.ats_board_id == board.token,
                or_(
                    models.Opportunity.primary_source == board.ats,
                    and_(models.Opportunity.primary_source.is_(None), board_link),
                ),
                or_(
                    _board_url_matches(models.Opportunity.apply_url, board.ats, board.token),
                    board_link,
                ),
                ~other_link,
            )
            .values(closed_at=func.now())
            .execution_options(synchronize_session=False)
        )
        counts[f"{board.ats}/{board.token}"] = int(result.rowcount or 0)
    return counts


def retire_rolling_window_listings(session: Session) -> dict[str, int]:
    """Apply the age presumption only while the corresponding feed is running."""
    counts = {}
    cutoff = func.now() - text(f"interval '{ROLLING_WINDOW_TTL_DAYS} days'")
    for source in sorted(ROLLING_WINDOW_SOURCES):
        recent_contact = (
            select(models.CrawlRun.id)
            .join(models.Source, models.Source.id == models.CrawlRun.source_id)
            .where(
                models.Source.adapter_key == source,
                models.CrawlRun.status.in_(("success", "partial")),
                models.CrawlRun.finished_at >= func.now() - text("interval '2 days'"),
            )
            .exists()
        )
        # seen_at is initial provenance creation in the current ingest path;
        # canonical last_seen_at also advances on every source confirmation.
        # Both signals protect a newer confirmation from another source.
        fresher_link = (
            select(models.OpportunitySource.id)
            .join(models.Source, models.Source.id == models.OpportunitySource.source_id)
            .where(
                models.OpportunitySource.opportunity_id == models.Opportunity.id,
                models.Source.adapter_key != source,
                or_(
                    models.OpportunitySource.seen_at >= cutoff,
                    models.OpportunitySource.seen_at > models.Opportunity.last_seen_at,
                ),
            )
            .exists()
        )
        result = session.execute(
            update(models.Opportunity)
            .where(
                models.Opportunity.status == "active",
                models.Opportunity.closed_at.is_(None),
                models.Opportunity.primary_source == source,
                models.Opportunity.last_seen_at < cutoff,
                recent_contact,
                ~fresher_link,
            )
            .values(closed_at=func.now())
            .execution_options(synchronize_session=False)
        )
        counts[source] = int(result.rowcount or 0)
    return counts
