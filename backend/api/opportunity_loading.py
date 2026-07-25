"""Shared ORM load profiles for opportunity read endpoints."""

from sqlalchemy.orm import Load, joinedload, load_only

from core import models

OPPORTUNITY_LIST_COLUMNS = (
    models.Opportunity.id,
    models.Opportunity.company_id,
    models.Opportunity.slug,
    models.Opportunity.title,
    models.Opportunity.category,
    models.Opportunity.primary_source,
    models.Opportunity.location,
    models.Opportunity.country,
    models.Opportunity.is_remote,
    models.Opportunity.posted_at,
    models.Opportunity.deadline,
    models.Opportunity.meta,
    models.Opportunity.deadline_confidence,
    models.Opportunity.is_hidden,
    models.Opportunity.last_seen_at,
)


def opportunity_list_load_options() -> tuple[Load, ...]:
    return (
        joinedload(models.Opportunity.company),
        load_only(*OPPORTUNITY_LIST_COLUMNS),
    )
