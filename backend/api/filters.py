"""Shared optional filters for opportunity query endpoints."""

from sqlalchemy import and_, func, not_, or_, text

from core import models

SOURCE_GROUPS = {
    "direct": ["greenhouse", "lever", "ashby", "smartrecruiters", "amazon"],
    "unstop": ["unstop"],
    "remoteok": ["remoteok"],
    "devpost": ["devpost"],
}

SENIOR_TITLE_PATTERN = (
    r"(^|[^a-z])(senior|sr|staff|principal|director|vp|head of|lead|manager|"
    r"architect|distinguished|fellow|executive)([^a-z]|$)"
)


def exclude_closed_competitions():
    """Exclude expiring categories whose deadline passed over 14 days ago."""
    expired_opportunity = and_(
        models.Opportunity.category.in_(["hackathon", "competition", "internship"]),
        models.Opportunity.deadline.is_not(None),
        models.Opportunity.deadline < func.now() - text("interval '14 days'"),
    )
    return expired_opportunity.is_not(True)


def experience_filters(experience: str | None) -> list:
    if experience == "early":
        return [
            not_(
                func.coalesce(models.Opportunity.title_normalized, "").op("~*")(
                    SENIOR_TITLE_PATTERN
                )
            )
        ]
    return []


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


def location_scope_filters(
    scope: str | None,
    country: str | None,
    include_remote_abroad: bool = False,
) -> list:
    """Return country-scope filters with an opt-in for foreign remote roles.

    When enabled for a domestic scope, ``include_remote_abroad`` admits remote
    roles tied to another country. Those roles usually mean remote within that
    country and may require local work authorization, so the option is opt-in.
    """
    country_upper = country.strip().upper() if country else ""
    if (
        scope not in {"domestic", "abroad"}
        or len(country_upper) != 2
        or not country_upper.isalpha()
    ):
        return []

    if scope == "domestic" and include_remote_abroad:
        return [
            or_(
                models.Opportunity.country == country_upper,
                models.Opportunity.is_remote.is_(True),
            )
        ]

    if scope == "domestic":
        return [
            or_(
                models.Opportunity.country == country_upper,
                and_(
                    models.Opportunity.is_remote.is_(True),
                    models.Opportunity.country.is_(None),
                ),
            )
        ]

    return [
        or_(
            and_(
                models.Opportunity.country.is_not(None),
                models.Opportunity.country != country_upper,
            ),
            and_(
                models.Opportunity.is_remote.is_(True),
                models.Opportunity.country.is_(None),
            ),
        )
    ]


def saved_search_base_filters(params: dict) -> list:
    """Build the feed/search filters represented by stored saved-search params.

    Saved searches persist only the shared, non-pagination filters. Full-text
    matching and the alert window are intentionally added by the caller.
    """

    category = params.get("category")
    kind = params.get("kind")
    remote = params.get("remote")
    scope = params.get("scope")
    country = params.get("country")
    source = params.get("source")
    experience = params.get("experience")

    base_filters = [
        models.Opportunity.status == "active",
        exclude_closed_competitions(),
        *opportunity_filters(category, remote, None, None, None),
        *experience_filters(experience),
        *location_scope_filters(scope, country, False),
    ]
    if kind == "competitions":
        base_filters.append(models.Opportunity.category.in_(["hackathon", "competition"]))
    elif kind == "roles":
        base_filters.append(
            or_(
                models.Opportunity.category.in_(["internship", "job"]),
                models.Opportunity.meta["offers_ppi"].as_boolean().is_(True),
                models.Opportunity.meta["offers_ppo"].as_boolean().is_(True),
            )
        )
    if source is not None:
        base_filters.append(models.Opportunity.primary_source.in_(SOURCE_GROUPS[source]))

    return base_filters
