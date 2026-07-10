"""Shared optional filters for opportunity query endpoints."""

from sqlalchemy import and_, or_

from core import models


def opportunity_filters(
    category: str | None,
    remote: bool | None,
    company: str | None,
    location: str | None,
    top: int | None,
) -> list:
    filters = []
    if category:
        filters.append(models.Opportunity.category == category)
    if remote is not None:
        filters.append(models.Opportunity.is_remote == remote)
    company_filter = company.strip() if company else ""
    if company_filter:
        filters.append(
            models.Opportunity.company.has(
                or_(
                    models.Company.slug == company_filter,
                    models.Company.name.ilike(f"%{company_filter}%"),
                )
            )
        )
    location_filter = location.strip() if location else ""
    if location_filter:
        filters.append(models.Opportunity.location.ilike(f"%{location_filter}%"))
    if top is not None:
        filters.append(
            models.Opportunity.company.has(
                or_(
                    and_(
                        models.Company.prestige_rank.is_not(None),
                        models.Company.prestige_rank <= top,
                    ),
                    and_(
                        models.Company.global_rank.is_not(None),
                        models.Company.global_rank <= top,
                    ),
                )
            )
        )

    return filters
