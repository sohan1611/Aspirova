"""Mark opportunities closed when an explicit deadline passed or a fresh crawl proves absence.

An opportunity is marked closed only after its company's board was crawled after
the opportunity was last seen, after its aggregator source was crawled after the
opportunity was last seen, or when the source supplied a deadline that has
passed. The row stays status='active' during the 14-day grace window so it
remains visible as closed. The two-day freshness guard makes a broken or stalled
crawl fail safe: stale source state closes nothing rather than mass-retiring the
catalogue.
"""

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from core import models


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
    # ATS join above could never see them. Some aggregator SourceState rows are
    # keyed per page_key, so absence is compared to the latest successful crawl
    # for that source while keeping the same 2-day/6-hour fail-safe guards.
    latest_source_crawl = (
        select(
            models.SourceState.source_id.label("source_id"),
            func.max(models.SourceState.last_crawled_at).label("last_crawled_at"),
        )
        .where(models.SourceState.last_crawled_at.is_not(None))
        .group_by(models.SourceState.source_id)
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
            models.Opportunity.primary_source == models.Source.adapter_key,
            latest_source_crawl.c.source_id == models.Source.id,
            latest_source_crawl.c.last_crawled_at.is_not(None),
            latest_source_crawl.c.last_crawled_at > func.now() - text("interval '2 days'"),
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
