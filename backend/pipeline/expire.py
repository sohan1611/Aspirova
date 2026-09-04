"""Mark opportunities closed when a deadline passed or a crawl proves absence.

Absence closes a listing only when the crawl that missed it could have seen it:
ATS board crawls enumerate one company's board, while only explicitly
allowlisted aggregator crawls enumerate a complete source-wide open inventory.
The row stays status='active' during the 14-day grace window so it remains
visible as closed. Freshness and coverage guards make broken, stale, or
truncated crawls fail safe: weak source evidence closes nothing rather than
mass-retiring the catalogue.
"""

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from core import models

# A source belongs here ONLY if one crawl enumerates its complete open inventory,
# so a listing's absence is evidence it is gone. Production on 2026-09-04 proved
# remoteok/himalayas/arbeitnow/jobicy are rolling windows: found/still-open/closed
# was 100/100/1001, 73/56/772, 54/52/165, and 3/2/43. Adding a source here
# without verifying full enumeration will silently close live listings.
FULL_INVENTORY_SOURCES = frozenset({"unstop", "devpost", "devfolio"})

# Fail-safe, not a tuning knob: a crawl that saw less than half of what is
# currently open is not evidence of mass closure.
RETIRE_MIN_COVERAGE = 0.5


def expire_missing_opportunities(session: Session) -> int:
    """Mark active opportunities closed when explicitly expired or absent."""
    deadline_result = session.execute(
        update(models.Opportunity)
        .where(
            models.Opportunity.status == "active",
            models.Opportunity.closed_at.is_(None),
            models.Opportunity.deadline.is_not(None),
            models.Opportunity.deadline < func.now(),
        )
        .values(closed_at=func.now())
        .execution_options(synchronize_session=False)
    )
    missing_result = session.execute(
        update(models.Opportunity)
        .where(
            models.Opportunity.status == "active",
            models.Opportunity.closed_at.is_(None),
            models.Opportunity.company_id == models.Company.id,
            models.Source.adapter_key == models.Company.ats_type,
            models.SourceState.source_id == models.Source.id,
            models.SourceState.page_key == models.Company.ats_board_id,
            models.SourceState.last_crawled_at.is_not(None),
            models.SourceState.last_crawled_at > func.now() - text("interval '2 days'"),
            models.Opportunity.last_seen_at
            < models.SourceState.last_crawled_at - text("interval '6 hours'"),
        )
        .values(closed_at=func.now())
        .execution_options(synchronize_session=False)
    )
    # Aggregator opportunities are source-wide, not company-board scoped: measured
    # 858 of 864 active competitions/hackathons had company.ats_type NULL, so the
    # ATS join above could never see them. Only full-inventory adapters can use
    # absence as evidence; rolling-window feeds would collapse their catalogue to
    # one crawl's worth. Some aggregator SourceState rows are keyed per page_key,
    # so absence is compared to the latest crawl state for that source while
    # keeping the same 2-day/6-hour fail-safe guards.
    latest_source_crawl = (
        select(
            models.SourceState.source_id.label("source_id"),
            func.max(models.SourceState.last_crawled_at).label("last_crawled_at"),
        )
        .where(models.SourceState.last_crawled_at.is_not(None))
        .group_by(models.SourceState.source_id)
        .subquery()
    )
    latest_crawl_run = (
        select(
            models.CrawlRun.source_id.label("source_id"),
            models.CrawlRun.started_at.label("started_at"),
            models.CrawlRun.listings_found.label("listings_found"),
            func.row_number()
            .over(
                partition_by=models.CrawlRun.source_id,
                order_by=(
                    models.CrawlRun.started_at.desc(),
                    models.CrawlRun.id.desc(),
                ),
            )
            .label("run_rank"),
        )
        .where(
            models.CrawlRun.source_id.is_not(None),
            models.CrawlRun.started_at.is_not(None),
        )
        .subquery()
    )
    currently_open_by_source = (
        select(
            models.Opportunity.primary_source.label("primary_source"),
            func.count(models.Opportunity.id).label("currently_open"),
        )
        .where(
            models.Opportunity.status == "active",
            models.Opportunity.closed_at.is_(None),
            models.Opportunity.primary_source.in_(FULL_INVENTORY_SOURCES),
        )
        .group_by(models.Opportunity.primary_source)
        .subquery()
    )
    aggregator_missing_result = session.execute(
        update(models.Opportunity)
        .where(
            models.Opportunity.status == "active",
            models.Opportunity.closed_at.is_(None),
            models.Opportunity.company_id == models.Company.id,
            models.Company.ats_type.is_(None),
            models.Opportunity.primary_source.is_not(None),
            models.Opportunity.primary_source.in_(FULL_INVENTORY_SOURCES),
            models.Opportunity.primary_source == models.Source.adapter_key,
            latest_source_crawl.c.source_id == models.Source.id,
            latest_source_crawl.c.last_crawled_at.is_not(None),
            latest_source_crawl.c.last_crawled_at > func.now() - text("interval '2 days'"),
            latest_crawl_run.c.source_id == models.Source.id,
            latest_crawl_run.c.run_rank == 1,
            latest_crawl_run.c.started_at > func.now() - text("interval '2 days'"),
            latest_crawl_run.c.listings_found.is_not(None),
            currently_open_by_source.c.primary_source == models.Opportunity.primary_source,
            latest_crawl_run.c.listings_found
            >= currently_open_by_source.c.currently_open * RETIRE_MIN_COVERAGE,
            models.Opportunity.last_seen_at
            < latest_source_crawl.c.last_crawled_at - text("interval '6 hours'"),
        )
        .values(closed_at=func.now())
        .execution_options(synchronize_session=False)
    )
    return (
        int(deadline_result.rowcount or 0)
        + int(missing_result.rowcount or 0)
        + int(aggregator_missing_result.rowcount or 0)
    )
