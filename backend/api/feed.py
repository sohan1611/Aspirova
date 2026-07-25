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
from sqlalchemy.orm import Session

from api.deps import get_db
from api.filters import (
    SENIOR_TITLE_PATTERN,
    SOURCE_GROUPS,
    exclude_closed_competitions,
    experience_filters,
    location_scope_filters,
    opportunity_filters,
)
from api.opportunity_loading import opportunity_list_load_options
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
    scope: str | None = Query(None, pattern="^(abroad|domestic|both)$"),
    country: str | None = Query(None, min_length=2, max_length=2),
    remote_abroad: bool = Query(False),
    source: str | None = Query(None, pattern="^(direct|unstop|remoteok|devpost)$"),
    experience: str | None = Query(None, pattern="^(early)$"),
    top: int | None = Query(None, gt=0),
    sort: str = Query("student", pattern="^(recent|deadline|student)$"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> FeedResponse:
    base_filters = [
        models.Opportunity.status == "active",
        exclude_closed_competitions(),
        *opportunity_filters(category, remote, company, location, top),
        *experience_filters(experience),
        *location_scope_filters(scope, country, remote_abroad),
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

    total_count = func.count().over().label("total_count")
    source_rank = (
        func.row_number()
        .over(
            partition_by=func.coalesce(models.Opportunity.primary_source, ""),
            order_by=[
                models.Opportunity.last_seen_at.desc(),
                models.Opportunity.id.desc(),
            ],
        )
        .label("source_rank")
    )
    selected_columns = [models.Opportunity, total_count]
    if sort != "deadline":
        selected_columns.append(source_rank)
    query = select(*selected_columns).options(*opportunity_list_load_options()).where(*base_filters)
    # id is a required tie-breaker, not cosmetic: many rows share the exact
    # same last_seen_at (same crawl batch) or deadline (often null), and
    # Postgres gives no ordering guarantee among tied rows across separate
    # paginated queries - confirmed live, page 1 and page 2 returned
    # overlapping rows without this.
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
    ordering = [is_closed.asc()]
    if kind == "roles":
        roles_first = case(
            (models.Opportunity.category.in_(["internship", "job"]), 0),
            else_=1,
        )
        ordering.append(roles_first.asc())

    student_rank = case(
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

    if sort == "deadline":
        open_deadline = case(
            (is_closed == 0, models.Opportunity.deadline),
            else_=None,
        )
        ordering.extend(
            [
                open_deadline.asc().nullslast(),
                models.Opportunity.deadline.desc().nullslast(),
                models.Opportunity.id.asc(),
            ]
        )
    elif sort == "student":
        ordering.extend(
            [
                student_rank.asc(),
                source_rank.asc(),
                models.Opportunity.last_seen_at.desc(),
                models.Opportunity.id.desc(),
            ]
        )
    else:
        ordering.extend(
            [
                source_rank.asc(),
                models.Opportunity.last_seen_at.desc(),
                models.Opportunity.id.desc(),
            ]
        )
    query = query.order_by(*ordering)

    rows = db.execute(query.offset((page - 1) * limit).limit(limit)).unique().all()

    items = [OpportunityListItem.from_model(row.Opportunity) for row in rows]
    total = rows[0].total_count if rows else 0

    return FeedResponse(items=items, total=total, page=page, limit=limit)
