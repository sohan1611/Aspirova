"""Deterministic hidden-opportunity classification (Doc 05 Shape A)."""

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from core import models


def recompute_hidden(session: Session) -> int:
    """Recompute every opportunity's hidden flag with one set-based update."""
    hidden_opportunity_ids = (
        select(models.OpportunitySource.opportunity_id)
        .join(models.Source, models.Source.id == models.OpportunitySource.source_id)
        .group_by(models.OpportunitySource.opportunity_id)
        .having(
            func.count(func.distinct(models.OpportunitySource.source_id)) == 1,
            func.min(models.Source.crawl_tier) > 1,
        )
    )
    should_be_hidden = models.Opportunity.id.in_(hidden_opportunity_ids)

    # Only write the rows whose flag actually flips. Without the WHERE this
    # rewrote EVERY opportunity row on every crawl - a full-table rewrite
    # (row versions + index maintenance) that exceeded statement_timeout and
    # failed the crawl's compute-hidden step outright. In the steady state
    # almost nothing changes, so the update touches a handful of rows.
    session.execute(
        update(models.Opportunity)
        .values(is_hidden=should_be_hidden)
        .where(models.Opportunity.is_hidden.is_distinct_from(should_be_hidden))
        .execution_options(synchronize_session=False)
    )

    count = session.scalar(
        select(func.count())
        .select_from(models.Opportunity)
        .where(models.Opportunity.is_hidden.is_(True))
    )
    return int(count or 0)
