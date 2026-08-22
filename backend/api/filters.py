"""Shared optional filters for opportunity query endpoints."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, case, func, not_, or_, text

from core import models
from core.eligibility import ELIGIBLE_EXPERIENCED_ONLY_META_KEY

SOURCE_GROUPS = {
    "direct": ["greenhouse", "lever", "ashby", "smartrecruiters", "amazon"],
    "unstop": ["unstop"],
    "remoteok": ["remoteok"],
    "devpost": ["devpost"],
}

# Founder ruling: "10 months" means 305 days for stale-listing promotion.
STALE_AFTER_DAYS = 305

SENIOR_TITLE_PATTERN = (
    r"(^|[^a-z])(senior|sr|staff|principal|director|vp|vice president|president|"
    r"chief|cto|ceo|coo|cfo|cxo|head of|lead|manager|architect|distinguished|"
    r"fellow|executive|counsel)([^a-z]|$)"
)


def student_rank_expression():
    return case(
        (models.Opportunity.category == "internship", 0),
        (
            and_(
                models.Opportunity.category == "job",
                func.coalesce(models.Opportunity.title_normalized, "").op("~*")(
                    SENIOR_TITLE_PATTERN
                ),
            ),
            2,
        ),
        else_=1,
    )


def exclude_stale_opportunities(now: datetime | None = None):
    """Exclude old promoted listings unless a future deadline keeps them current.

    A listing with no ``posted_at`` falls back to ``first_seen_at`` (never
    null) so a missing source date can't bypass the age check entirely.
    """
    current = now or func.now()
    stale_cutoff = (
        now - timedelta(days=STALE_AFTER_DAYS)
        if now
        else current - text(f"interval '{STALE_AFTER_DAYS} days'")
    )
    effective_posted_at = func.coalesce(
        models.Opportunity.posted_at, models.Opportunity.first_seen_at
    )
    stale = and_(
        effective_posted_at < stale_cutoff,
        or_(
            models.Opportunity.deadline.is_(None),
            models.Opportunity.deadline <= current,
        ),
    )
    return stale.is_not(True)


def exclude_experienced_only_opportunities():
    experienced_only = models.Opportunity.meta[ELIGIBLE_EXPERIENCED_ONLY_META_KEY].as_boolean()
    return experienced_only.is_not(True)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def is_stale_opportunity(opportunity: models.Opportunity, now: datetime | None = None) -> bool:
    """Return the Python equivalent of exclude_stale_opportunities for detail metadata."""
    effective_posted_at = opportunity.posted_at or opportunity.first_seen_at
    if effective_posted_at is None:
        return False

    current = _as_utc(now or datetime.now(UTC))
    effective_posted_at = _as_utc(effective_posted_at)
    if effective_posted_at >= current - timedelta(days=STALE_AFTER_DAYS):
        return False

    if opportunity.deadline is None:
        return True
    return _as_utc(opportunity.deadline) <= current


def exclude_closed_competitions():
    """Exclude listings whose closed grace window has elapsed."""
    expired_deadline = and_(
        models.Opportunity.category.in_(["hackathon", "competition", "internship"]),
        models.Opportunity.deadline.is_not(None),
        models.Opportunity.deadline < func.now() - text("interval '14 days'"),
    )
    detected_closed = and_(
        models.Opportunity.closed_at.is_not(None),
        models.Opportunity.closed_at < func.now() - text("interval '14 days'"),
    )
    return or_(expired_deadline, detected_closed).is_not(True)


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
    company: list[str] | None,
    location: list[str] | None,
    top: int | None,
) -> list:
    filters = []
    if category:
        filters.append(models.Opportunity.category == category)
    if remote is not None:
        filters.append(models.Opportunity.is_remote == remote)
    company_values = [value.strip() for value in (company or []) if value and value.strip()]
    if company_values:
        filters.append(
            models.Opportunity.company.has(
                or_(
                    *[
                        or_(
                            models.Company.slug == value,
                            models.Company.name.ilike(f"%{value}%"),
                        )
                        for value in company_values
                    ]
                )
            )
        )
    location_values = [value.strip() for value in (location or []) if value and value.strip()]
    if location_values:
        filters.append(
            or_(*[models.Opportunity.location.ilike(f"%{value}%") for value in location_values])
        )
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
        exclude_stale_opportunities(),
        exclude_experienced_only_opportunities(),
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
