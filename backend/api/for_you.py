"""GET /for-you - lightweight interest-based ranking over the existing FTS index.

This is intentionally a query-time personalization layer: interest selections
remain client-side, while Postgres' existing ``search_tsv`` and ``ts_rank``
provide a fast, shared ranking primitive without adding per-user state or AI.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session, joinedload

from api.deps import get_db
from api.filters import exclude_closed_competitions, location_scope_filters
from api.schemas import FeedResponse, OpportunityListItem
from core import models

router = APIRouter()


# Keep these keys in sync with frontend/lib/interests.ts. Multi-word entries
# are deliberately passed through websearch_to_tsquery, rather than assembled
# with to_tsquery syntax, so this stays safe if the curated terms evolve.
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
    categories: str | None = Query(None, max_length=200),
    country: str | None = Query(None, min_length=2, max_length=2),
    scope: str | None = Query(None, pattern="^(abroad|domestic|both)$"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> FeedResponse:
    selected_categories = _selected_categories(categories)
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

    keywords = _selected_keywords(fields)
    total_count = func.count().over().label("total_count")
    query = (
        select(models.Opportunity, total_count)
        .options(joinedload(models.Opportunity.company))
        .where(*base_filters)
    )

    if keywords:
        # websearch_to_tsquery is the same resilient parser used by /search:
        # it safely handles phrases such as "full stack" and never treats a
        # curated string as raw tsquery syntax.
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
