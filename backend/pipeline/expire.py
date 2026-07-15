"""Retire opportunities only when a fresh crawl positively proves they are gone.

An opportunity is expired only after its company's board was crawled after the
opportunity was last seen. The two-day freshness guard makes a broken or stalled
crawl fail safe: stale source state expires nothing rather than mass-retiring the
catalogue.
"""

from sqlalchemy import func, text, update
from sqlalchemy.orm import Session

from core import models


def expire_missing_opportunities(session: Session) -> int:
    """Expire active opportunities absent from recently crawled company boards."""
    result = session.execute(
        update(models.Opportunity)
        .where(
            models.Opportunity.status == "active",
            models.Opportunity.company_id == models.Company.id,
            models.Source.adapter_key == models.Company.ats_type,
            models.SourceState.source_id == models.Source.id,
            models.SourceState.page_key == models.Company.ats_board_id,
            models.SourceState.last_crawled_at.is_not(None),
            models.SourceState.last_crawled_at > func.now() - text("interval '2 days'"),
            models.Opportunity.last_seen_at
            < models.SourceState.last_crawled_at - text("interval '6 hours'"),
        )
        .values(status="expired")
        .execution_options(synchronize_session=False)
    )
    return int(result.rowcount or 0)
