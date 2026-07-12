"""Shared optional filters for opportunity query endpoints."""

from sqlalchemy import and_, func, or_, text

from core import models

SOURCE_GROUPS = {
    "direct": ["greenhouse", "lever", "ashby", "smartrecruiters", "amazon"],
    "unstop": ["unstop"],
    "remoteok": ["remoteok"],
    "devpost": ["devpost"],
}


def exclude_closed_competitions():
    """Exclude expiring categories whose deadline passed over 14 days ago."""
    expired_opportunity = and_(
        models.Opportunity.category.in_(["hackathon", "competition", "internship"]),
        models.Opportunity.deadline.is_not(None),
        models.Opportunity.deadline < func.now() - text("interval '14 days'"),
    )
    return expired_opportunity.is_not(True)


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


def location_scope_filters(scope: str | None, country: str | None) -> list:
    """Return country-scope filters while preserving remote opportunities."""
    country_upper = country.strip().upper() if country else ""
    if (
        scope not in {"domestic", "abroad"}
        or len(country_upper) != 2
        or not country_upper.isalpha()
    ):
        return []

    if scope == "domestic":
        return [
            or_(
                models.Opportunity.country == country_upper,
                models.Opportunity.is_remote.is_(True),
            )
        ]

    return [
        or_(
            and_(
                models.Opportunity.country.is_not(None),
                models.Opportunity.country != country_upper,
            ),
            models.Opportunity.is_remote.is_(True),
        )
    ]
