"""Shared optional filters for opportunity query endpoints."""

from sqlalchemy import and_, func, or_, text

from core import models


def exclude_closed_competitions():
    """Exclude competitions whose registration deadline passed over 14 days ago."""
    expired_competition = and_(
        models.Opportunity.category.in_(["hackathon", "competition"]),
        models.Opportunity.deadline.is_not(None),
        models.Opportunity.deadline < func.now() - text("interval '14 days'"),
    )
    return expired_competition.is_not(True)


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
