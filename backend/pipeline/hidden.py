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

    session.execute(
        update(models.Opportunity)
        .values(is_hidden=models.Opportunity.id.in_(hidden_opportunity_ids))
        .execution_options(synchronize_session=False)
    )

    count = session.scalar(
        select(func.count())
        .select_from(models.Opportunity)
        .where(models.Opportunity.is_hidden.is_(True))
    )
    return int(count or 0)
