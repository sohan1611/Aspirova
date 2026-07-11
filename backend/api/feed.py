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
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session, joinedload

from api.deps import get_db
from api.filters import exclude_closed_competitions, opportunity_filters
from api.schemas import FeedResponse, OpportunityListItem
from core import models

router = APIRouter()


@router.get("/feed", response_model=FeedResponse)
def get_feed(
    category: str | None = Query(None, pattern="^(internship|job|hackathon|competition)$"),
    kind: str | None = Query(None, pattern="^(roles|competitions)$"),
    remote: bool | None = Query(None),
    company: str | None = Query(None),
    location: str | None = Query(None),
    top: int | None = Query(None, gt=0),
    sort: str = Query("recent", pattern="^(recent|deadline)$"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> FeedResponse:
    base_filters = [
        models.Opportunity.status == "active",
        exclude_closed_competitions(),
        *opportunity_filters(category, remote, company, location, top),
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
    competition_view = kind == "competitions" or category in {
        "hackathon",
        "competition",
    }
    if competition_view:
        competition_is_closed = case(
            (
                and_(
                    models.Opportunity.deadline.is_not(None),
                    models.Opportunity.deadline < func.now(),
                ),
                1,
            ),
            else_=0,
        )
        if sort == "deadline":
            competition_open_deadline = case(
                (
                    competition_is_closed == 0,
                    models.Opportunity.deadline,
                ),
                else_=None,
            )
            query = query.order_by(
                competition_is_closed.asc(),
                competition_open_deadline.asc().nullslast(),
                models.Opportunity.deadline.desc().nullslast(),
                models.Opportunity.id.asc(),
            )
        else:
            query = query.order_by(
                competition_is_closed.asc(),
                models.Opportunity.last_seen_at.desc(),
                models.Opportunity.id.desc(),
            )
    elif sort == "deadline":
        query = query.order_by(
            models.Opportunity.deadline.asc().nullslast(), models.Opportunity.id.asc()
        )
    else:
        query = query.order_by(models.Opportunity.last_seen_at.desc(), models.Opportunity.id.desc())

    rows = db.execute(query.offset((page - 1) * limit).limit(limit)).unique().all()

    items = [OpportunityListItem.from_model(row.Opportunity) for row in rows]
    total = rows[0].total_count if rows else 0

    return FeedResponse(items=items, total=total, page=page, limit=limit)
