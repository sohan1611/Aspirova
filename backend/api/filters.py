"""Shared optional filters for opportunity query endpoints."""

from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import and_, case, false, func, literal, not_, or_, text
from sqlalchemy.dialects.postgresql import JSONB

from core import models
from core.eligibility import ELIGIBLE_EXPERIENCED_ONLY_META_KEY
from core.organisers import ORGANISER_TYPE_LABELS, organiser_type_expression

SOURCE_GROUPS = {
    "direct": ["greenhouse", "lever", "ashby", "smartrecruiters", "amazon"],
    "unstop": ["unstop"],
    "remoteok": ["remoteok"],
    "devpost": ["devpost"],
}

# Founder ruling: "10 months" means 305 days for stale-listing promotion.
STALE_AFTER_DAYS = 305
COMP_TYPE_LABELS = {
    "online_coding_challenge": "Online coding challenge",
    "general_competition": "General competition",
    "case_competition": "Case competition",
    "innovation_challenge": "Innovation challenge",
    "hiring_challenge": "Hiring challenge",
    "events": "Events",
}
REGISTRATION_LABELS = {"free": "Free", "paid": "Paid"}
DEADLINE_WITHIN_DAYS = (1, 3, 7, 30)
COMPETITION_MODE_LABELS = {
    "online": "Online",
    "offline": "Offline",
    "hybrid": "Hybrid",
}
INR_PRIZE_CURRENCY_TOKENS = ("fa-rupee", "fa-inr", "fa-rupee-sign", "INR", "inr")

SENIOR_TITLE_PATTERN = (
    r"(^|[^a-z])(senior|sr|staff|principal|director|vp|vice president|president|"
    r"chief|cto|ceo|coo|cfo|cxo|head of|lead|manager|architect|distinguished|"
    r"fellow|executive|counsel)([^a-z]|$)"
)

# False (default) -> exclude only rows whose eligibility is School Students and nothing
#                    else. A competition open to school students AND undergraduates is
#                    still relevant to Aspirova's audience.
# True            -> exclude any row whose eligibility mentions School Students at all.
SCHOOL_AUDIENCE_STRICT = False


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


def exclude_school_only_opportunities():
    eligibility = models.Opportunity.meta["eligibility"]
    eligibility_is_array = func.jsonb_typeof(eligibility) == "array"
    school_students = eligibility.op("@>")(literal(["School Students"], type_=JSONB))
    if SCHOOL_AUDIENCE_STRICT:
        school_audience = case((eligibility_is_array, school_students), else_=False)
    else:
        school_audience = case(
            (
                eligibility_is_array,
                and_(func.jsonb_array_length(eligibility) == 1, school_students),
            ),
            else_=False,
        )
    return school_audience.is_not(True)


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
        models.Opportunity.category.in_(["hackathon", "competition", "internship", "scholarship"]),
        models.Opportunity.deadline.is_not(None),
        models.Opportunity.deadline < func.now() - text("interval '14 days'"),
    )
    detected_closed = and_(
        models.Opportunity.closed_at.is_not(None),
        models.Opportunity.closed_at < func.now() - text("interval '14 days'"),
    )
    return or_(expired_deadline, detected_closed).is_not(True)


def open_opportunity_filters() -> list:
    """Return the shared definition of an open, student-facing listing."""
    return [
        models.Opportunity.status == "active",
        exclude_stale_opportunities(),
        exclude_experienced_only_opportunities(),
        exclude_school_only_opportunities(),
        exclude_closed_competitions(),
        models.Opportunity.closed_at.is_(None),
        models.Opportunity.is_hidden.is_not(True),
        or_(
            models.Opportunity.deadline.is_(None),
            models.Opportunity.deadline > func.now(),
        ),
    ]


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


def kind_filters(kind: str | None) -> list:
    if kind == "competitions":
        return [models.Opportunity.category.in_(["hackathon", "competition"])]
    if kind == "roles":
        return [
            or_(
                models.Opportunity.category.in_(["internship", "job"]),
                models.Opportunity.meta["offers_ppi"].as_boolean().is_(True),
                models.Opportunity.meta["offers_ppo"].as_boolean().is_(True),
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


def normalize_competition_mode(value: str | None) -> str:
    """Collapse Unstop's dirty mode field to the three UI-safe buckets."""
    if value is None:
        return "unknown"

    normalized = value.strip().casefold()
    if normalized in COMPETITION_MODE_LABELS:
        return normalized
    return "unknown"


def competition_mode_expression():
    mode_value = func.lower(
        func.trim(func.coalesce(models.Opportunity.meta["mode"].as_string(), ""))
    )
    return case(
        (mode_value == "online", "online"),
        (mode_value == "offline", "offline"),
        (mode_value == "hybrid", "hybrid"),
        else_="unknown",
    )


def _clean_values(values: list[str] | None) -> list[str]:
    return [value.strip() for value in (values or []) if value and value.strip()]


def _comp_type_values(values: list[str] | None) -> list[str]:
    selected = []
    label_to_key = {
        label.casefold().replace("-", "_").replace(" ", "_"): key
        for key, label in COMP_TYPE_LABELS.items()
    }
    for value in _clean_values(values):
        normalized = value.casefold().replace("-", "_").replace(" ", "_")
        mapped = normalized if normalized in COMP_TYPE_LABELS else label_to_key.get(normalized)
        if mapped and mapped not in selected:
            selected.append(mapped)
    return selected


def _organiser_type_values(values: list[str] | None) -> list[str]:
    selected = []
    for value in _clean_values(values):
        normalized = value.casefold()
        if normalized in ORGANISER_TYPE_LABELS and normalized not in selected:
            selected.append(normalized)
    return selected


def _mode_values(values: list[str] | None) -> list[str]:
    selected = []
    for value in _clean_values(values):
        normalized = normalize_competition_mode(value)
        if normalized != "unknown" and normalized not in selected:
            selected.append(normalized)
    return selected


def _prize_min_filter(prize_min: int):
    # Unstop stores currency as font-awesome tokens, not ISO 4217. Until there
    # is a real FX normalisation layer, compare only INR-token prize entries.
    currency_values = ", ".join(f"'{token}'" for token in INR_PRIZE_CURRENCY_TOKENS)
    return text(f"""
        exists (
            select 1
            from jsonb_array_elements(
                case
                    when jsonb_typeof(opportunities.meta->'prizes') = 'array'
                    then opportunities.meta->'prizes'
                    else '[]'::jsonb
                end
            ) as prize
            where prize->>'currency' in ({currency_values})
            and prize->>'cash' ~ '^[0-9]+(\\.[0-9]+)?$'
            and (prize->>'cash')::numeric >= :prize_min
        )
        """).bindparams(prize_min=prize_min)


def competition_filters(
    comp_type: list[str] | None,
    registration: str | None,
    deadline_within: int | None,
    organiser_type: list[str] | None,
    mode: list[str] | None,
    prize_min: int | None,
) -> list:
    filters = []

    requested_comp_types = _clean_values(comp_type)
    if requested_comp_types:
        selected = _comp_type_values(comp_type)
        filters.append(
            models.Opportunity.meta["subtype"].as_string().in_(selected) if selected else false()
        )

    if registration is not None and registration.strip():
        normalized_registration = registration.strip().casefold()
        if normalized_registration == "free":
            filters.append(models.Opportunity.meta["is_paid"].as_boolean().is_(False))
        elif normalized_registration == "paid":
            filters.append(models.Opportunity.meta["is_paid"].as_boolean().is_(True))
        else:
            filters.append(false())

    if deadline_within is not None:
        if deadline_within in DEADLINE_WITHIN_DAYS:
            filters.append(
                and_(
                    models.Opportunity.deadline.is_not(None),
                    models.Opportunity.deadline >= func.now(),
                    models.Opportunity.deadline
                    <= func.now() + text(f"interval '{deadline_within} days'"),
                )
            )
        else:
            filters.append(false())

    requested_organiser_types = _clean_values(organiser_type)
    if requested_organiser_types:
        selected = _organiser_type_values(organiser_type)
        if selected:
            organiser_match = models.Opportunity.company.has(
                organiser_type_expression(models.Company.name).in_(selected)
            )
            if "other" in selected:
                organiser_match = or_(models.Opportunity.company_id.is_(None), organiser_match)
            filters.append(organiser_match)
        else:
            filters.append(false())

    requested_modes = _clean_values(mode)
    if requested_modes:
        selected = _mode_values(mode)
        filters.append(competition_mode_expression().in_(selected) if selected else false())

    if prize_min is not None:
        filters.append(_prize_min_filter(prize_min))

    return filters


# Matched against the title as exact words (the "simple" config): English stemming
# makes "developer" match "Business Development", and search_tsv also weights the
# company name as A, so neither can decide this alone. search_tsv stays as the
# indexed first pass. "engineer" is left out so a mechanical role stays out of Software.
ROLE_TERMS = {
    "software": (
        "software | developer | developers | programmer | programming | coding | backend | "
        "frontend | fullstack | android | ios | sde | devops | web | cloud"
    ),
    "data": "data | analytics | analyst | analysts | scientist | ml | ai | machine <-> learning",
    "design": "design | designer | designers | designing | ux | ui | graphic",
    "marketing": "marketing | growth | seo | brand | branding | social <-> media",
    "finance": "finance | financial | accounting | accountant | accounts | investment | audit",
    "hr": "hr | recruitment | recruiter | recruiting | talent | human <-> resources",
    "sales": "sales | business <-> development | bd | bde | account <-> executive",
    "product": "product",
    "operations": "operations | ops | logistics | supply <-> chain",
    "content": "content | copywriter | copywriting | writer | writing | editorial | editor",
}


def role_signal_filters(
    paid: bool | None = None,
    min_stipend: int | None = None,
    part_time: bool | None = None,
    max_duration: int | None = None,
    job_offer: bool | None = None,
    posted_within: int | None = None,
    role: str | None = None,
) -> list:
    filters = []
    meta = models.Opportunity.meta
    compensation = meta["compensation"]
    # CASE must return a non-null boolean: NOT(NULL) would otherwise discard
    # listings with missing metadata when paid=false. Guard numeric casts too.
    is_paid = case(
        (
            func.jsonb_typeof(compensation) == "object",
            compensation["unpaid"].as_boolean().is_not(True),
        ),
        else_=False,
    )
    if paid is not None:
        filters.append(is_paid if paid else not_(is_paid))
    if min_stipend is not None:
        maximum = case(
            (
                func.jsonb_typeof(compensation["max"]) == "number",
                compensation["max"].as_float(),
            ),
            else_=None,
        )
        filters.append(
            and_(
                compensation["currency"].as_string() == "INR",
                or_(
                    and_(compensation["period"].as_string() == "month", maximum >= min_stipend),
                    and_(compensation["period"].as_string() == "year", maximum / 12 >= min_stipend),
                ),
            )
        )
    if part_time is True:
        filters.append(
            or_(
                meta["part_time"].as_boolean().is_(True),
                meta["timing"].as_string() == "part_time",
            )
        )
    if max_duration is not None:
        duration = case(
            (
                func.jsonb_typeof(meta["duration_months"]) == "number",
                meta["duration_months"].as_float(),
            ),
            else_=None,
        )
        filters.append(duration <= max_duration)
    if job_offer is True:
        filters.append(
            or_(
                meta["job_offer"].as_boolean().is_(True),
                meta["offers_ppo"].as_boolean().is_(True),
            )
        )
    if posted_within is not None:
        if posted_within not in (1, 3, 7, 30):
            raise HTTPException(status_code=422, detail="posted_within must be 1, 3, 7 or 30")
        filters.append(
            func.coalesce(models.Opportunity.posted_at, models.Opportunity.first_seen_at)
            >= func.now() - timedelta(days=posted_within)
        )
    if role is not None:
        terms = ROLE_TERMS.get(role)
        if terms:
            filters.append(
                models.Opportunity.search_tsv.op("@@")(func.to_tsquery("english", terms))
            )
            filters.append(
                func.to_tsvector("simple", models.Opportunity.title).op("@@")(
                    func.to_tsquery("simple", terms)
                )
            )
        else:
            filters.append(false())
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
        exclude_school_only_opportunities(),
        exclude_closed_competitions(),
        *opportunity_filters(category, remote, None, None, None),
        *experience_filters(experience),
        *location_scope_filters(scope, country, False),
    ]
    base_filters.extend(kind_filters(kind))
    if source is not None:
        base_filters.append(models.Opportunity.primary_source.in_(SOURCE_GROUPS[source]))

    return base_filters
