"""Pre-incident landing query shape (00f6f24), retained only for parity/perf checks."""

from sqlalchemy import and_, case, func, select
from sqlalchemy.sql import visitors

from api.filters import listing_closed
from api.landing import famous_company_filter, landing_rows
from api.opportunity_loading import opportunity_list_load_options
from core import models


def legacy_landing_feed_rows(db, filters, ordering, limit):
    source_rank = next(
        clause.element
        for clause in ordering
        if getattr(clause.element, "name", None) == "source_rank"
    )
    has_logo = models.Opportunity.company.has(models.Company.logo_url.is_not(None))
    source_ranks = (
        select(
            models.Opportunity.id,
            source_rank,
            func.count().filter(has_logo).over().label("total_count"),
            func.count()
            .filter(and_(has_logo, case((listing_closed(), 1), else_=0) == 0))
            .over()
            .label("open_count"),
        )
        .where(*filters)
        .subquery()
    )
    legacy_order = [
        visitors.replacement_traverse(
            clause, {}, lambda node: source_ranks.c.source_rank if node is source_rank else None
        )
        for clause in ordering
    ]
    query = (
        select(
            models.Opportunity,
            source_ranks.c.total_count,
            source_ranks.c.open_count,
            source_ranks.c.source_rank,
        )
        .options(*opportunity_list_load_options())
        .join_from(models.Opportunity, source_ranks, source_ranks.c.id == models.Opportunity.id)
        .where(*filters, has_logo)
        .order_by(*legacy_order)
    )
    return landing_rows(
        db,
        query,
        models.Opportunity.company.has(famous_company_filter()),
        limit,
        listing_order=legacy_order,
    )
