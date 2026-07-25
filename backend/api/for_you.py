"""GET /for-you - lightweight interest-based ranking over the existing FTS index.

This is intentionally a query-time personalization layer: interest selections
remain client-side, while Postgres' existing ``search_tsv`` and ``ts_rank``
provide a fast, shared ranking primitive without adding per-user state or AI.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Text, and_, any_, bindparam, case, cast, func, or_, select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Session

from api.deps import get_db
from api.filters import exclude_closed_competitions, location_scope_filters
from api.opportunity_loading import opportunity_list_load_options
from api.schemas import FeedResponse, OpportunityListItem
from core import models

router = APIRouter()


# These legacy field keys remain supported for backwards compatibility.
# Multi-word entries are deliberately passed through websearch_to_tsquery,
# rather than assembled with to_tsquery syntax, so this stays safe if the
# curated terms evolve.
FIELD_KEYWORDS: dict[str, list[str]] = {
    "software": [
        "software",
        "engineer",
        "developer",
        "backend",
        "frontend",
        "full stack",
        "sde",
        "web development",
    ],
    "data_ai": [
        "data",
        "machine learning",
        "ml",
        "analytics",
        "data scientist",
        "deep learning",
        "artificial intelligence",
        "ai",
    ],
    "product_design": [
        "product manager",
        "product",
        "ux",
        "ui",
        "designer",
        "user experience",
        "user interface",
        "design",
    ],
    "marketing": [
        "marketing",
        "growth",
        "seo",
        "social media",
        "brand",
        "digital marketing",
        "content marketing",
    ],
    "finance": [
        "finance",
        "investment",
        "consulting",
        "analyst",
        "accounting",
        "financial",
        "valuation",
    ],
    "business_ops": [
        "operations",
        "business",
        "strategy",
        "program manager",
        "project manager",
        "business analyst",
        "partnerships",
    ],
    "research": [
        "research",
        "phd",
        "fellowship",
        "scientist",
        "lab",
        "researcher",
        "academic",
    ],
    "hardware": [
        "hardware",
        "electronics",
        "embedded",
        "vlsi",
        "mechanical",
        "electrical",
        "firmware",
    ],
    "content_media": [
        "content",
        "writer",
        "media",
        "video",
        "editor",
        "journalism",
        "creative",
    ],
    "other": [],
}

VALID_CATEGORIES = frozenset({"internship", "job", "hackathon", "competition"})
MAX_SELECTED_SKILLS = 30


def _selected_keywords(fields: str | None) -> list[str]:
    """Expand known CSV field keys into a stable, de-duplicated keyword list."""
    keywords: list[str] = []
    seen: set[str] = set()
    for field in (fields or "").split(","):
        for keyword in FIELD_KEYWORDS.get(field.strip().lower(), []):
            if keyword not in seen:
                keywords.append(keyword)
                seen.add(keyword)
    return keywords


def _selected_terms(terms: str | None) -> list[str]:
    """Parse CSV search terms supplied by the field-profile feed."""
    return [term.strip() for term in (terms or "").split(",") if term.strip()]


def _selected_skills(skills: str | None) -> list[str]:
    """Parse user skill names from CSV while preserving first-seen casing."""
    selected: list[str] = []
    seen: set[str] = set()
    for skill in (skills or "").split(","):
        normalized = skill.strip()
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        selected.append(normalized)
        seen.add(key)
        if len(selected) == MAX_SELECTED_SKILLS:
            break
    return selected


def _selected_categories(categories: str | None) -> list[str]:
    """Parse the CSV category parameter while retaining FastAPI's 422 contract."""
    selected: list[str] = []
    for category in (categories or "").split(","):
        normalized = category.strip().lower()
        if not normalized:
            continue
        if normalized not in VALID_CATEGORIES:
            raise HTTPException(status_code=422, detail="Invalid category")
        if normalized not in selected:
            selected.append(normalized)
    return selected


@router.get("/for-you", response_model=FeedResponse)
def get_for_you(
    fields: str | None = Query(None, max_length=500),
    terms: str | None = Query(None, max_length=500),
    skills: str | None = Query(None, max_length=1000),
    categories: str | None = Query(None, max_length=200),
    country: str | None = Query(None, min_length=2, max_length=2),
    scope: str | None = Query(None, pattern="^(abroad|domestic|both)$"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> FeedResponse:
    selected_categories = _selected_categories(categories)
    user_skills = _selected_skills(skills)
    base_filters = [
        models.Opportunity.status == "active",
        exclude_closed_competitions(),
        *location_scope_filters(scope, country),
    ]
    if selected_categories:
        base_filters.append(models.Opportunity.category.in_(selected_categories))
    else:
        # The landing feed defaults to roles; preserve that scope when users
        # have not selected a category for their personalized view.
        base_filters.append(
            or_(
                models.Opportunity.category.in_(["internship", "job"]),
                models.Opportunity.meta["offers_ppi"].as_boolean().is_(True),
                models.Opportunity.meta["offers_ppo"].as_boolean().is_(True),
            )
        )

    # A supplied terms parameter represents the richer field profile. Its
    # presence intentionally takes precedence over legacy fields, even when
    # CSV cleanup leaves no usable terms.
    keywords = _selected_terms(terms) if terms is not None else _selected_keywords(fields)
    total_count = func.count().over().label("total_count")
    query = (
        select(models.Opportunity, total_count)
        .options(*opportunity_list_load_options())
        .where(*base_filters)
    )

    if user_skills:
        skill_values = cast(
            bindparam("user_skills", value=user_skills, type_=ARRAY(Text())),
            ARRAY(Text()),
        )
        skill_element = (
            func.jsonb_array_elements_text(models.Opportunity.skills)
            .table_valued("skill")
            .render_derived(name="skill")
        )
        overlap_count = (
            select(func.count())
            .select_from(skill_element)
            .where(skill_element.c.skill == any_(skill_values))
            .correlate(models.Opportunity.__table__)
            .scalar_subquery()
        )
        query = query.where(models.Opportunity.skills.op("?|")(skill_values)).order_by(
            overlap_count.desc(),
            models.Opportunity.last_seen_at.desc(),
            models.Opportunity.id.desc(),
        )
    elif keywords:
        # websearch_to_tsquery is the same resilient parser used by /search:
        # it safely handles phrases such as "full stack" and never treats a
        # input as raw tsquery syntax.
        tsquery = func.websearch_to_tsquery("english", " OR ".join(keywords))
        matches_fts = models.Opportunity.search_tsv.op("@@")(tsquery)
        rank = func.ts_rank(models.Opportunity.search_tsv, tsquery)
        query = query.where(matches_fts).order_by(
            rank.desc(),
            models.Opportunity.last_seen_at.desc(),
            models.Opportunity.id.desc(),
        )
    else:
        is_closed = case(
            (
                and_(
                    models.Opportunity.deadline.is_not(None),
                    models.Opportunity.deadline < func.now(),
                ),
                1,
            ),
            else_=0,
        )
        query = query.order_by(
            is_closed.asc(),
            models.Opportunity.last_seen_at.desc(),
            models.Opportunity.id.desc(),
        )

    rows = db.execute(query.offset((page - 1) * limit).limit(limit)).unique().all()
    items = [OpportunityListItem.from_model(row.Opportunity) for row in rows]
    total = rows[0].total_count if rows else 0
    return FeedResponse(items=items, total=total, page=page, limit=limit)
