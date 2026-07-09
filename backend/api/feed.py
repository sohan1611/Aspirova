"""GET /feed - the main browse surface. No AI/heavy work on this hot path
(Doc 02 sec 3 hard rule) - just indexed Postgres queries.

total_count is fetched via a count(*) OVER() window function in the SAME
query as the page of results, not a separate count query - each query is a
real network round-trip to the Supabase pooler (measured ~44ms baseline per
round-trip), so halving the round-trips roughly halves latency. This is
what brought p95 back under the Phase-1 budget; the naive two-query version
measured p50 248-272ms / p95 up to 1254ms against the same real data.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, joinedload

from api.deps import get_db
from api.schemas import FeedResponse, OpportunityListItem
from core import models

router = APIRouter()


@router.get("/feed", response_model=FeedResponse)
def get_feed(
    category: str | None = Query(None, pattern="^(internship|job)$"),
    remote: bool | None = Query(None),
    company: str | None = Query(None),
    location: str | None = Query(None),
    top: int | None = Query(None, gt=0),
    sort: str = Query("recent", pattern="^(recent|deadline)$"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> FeedResponse:
    base_filters = [models.Opportunity.status == "active"]
    if category:
        base_filters.append(models.Opportunity.category == category)
    if remote is not None:
        base_filters.append(models.Opportunity.is_remote == remote)
    company_filter = company.strip() if company else ""
    if company_filter:
        base_filters.append(
            models.Opportunity.company.has(
                or_(
                    models.Company.slug == company_filter,
                    models.Company.name.ilike(f"%{company_filter}%"),
                )
            )
        )
    location_filter = location.strip() if location else ""
    if location_filter:
        base_filters.append(models.Opportunity.location.ilike(f"%{location_filter}%"))
    if top is not None:
        base_filters.append(
            models.Opportunity.company.has(
                and_(
                    models.Company.global_rank.is_not(None),
                    models.Company.global_rank <= top,
                )
            )
        )

    total_count = func.count().over().label("total_count")
    query = (
        select(models.Opportunity, total_count)
        .options(joinedload(models.Opportunity.company))
        .where(*base_filters)
    )
    # id is a required tie-breaker, not cosmetic: many rows share the exact
    # same last_seen_at (same crawl batch) or deadline (often null), and
    # Postgres gives no ordering guarantee among tied rows across separate
    # paginated queries - confirmed live, page 1 and page 2 returned
    # overlapping rows without this.
    if sort == "deadline":
        query = query.order_by(
            models.Opportunity.deadline.asc().nullslast(), models.Opportunity.id.asc()
        )
    else:
        query = query.order_by(models.Opportunity.last_seen_at.desc(), models.Opportunity.id.desc())

    rows = db.execute(query.offset((page - 1) * limit).limit(limit)).unique().all()

    items = [OpportunityListItem.from_model(row.Opportunity) for row in rows]
    total = rows[0].total_count if rows else 0

    return FeedResponse(items=items, total=total, page=page, limit=limit)
