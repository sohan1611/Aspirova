"""Lightweight cumulative opportunity view tracking and discovery."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from api.deps import get_db
from api.filters import exclude_closed_competitions, exclude_stale_opportunities
from api.middleware import client_ip
from api.opportunity_loading import opportunity_list_load_options
from api.schemas import OpportunityListItem, TrendingResponse
from core import models
from core.config import get_settings
from core.ratelimit import check_rate_limit
from core.redis_client import get_redis

TRENDING_MIN_VIEWS = 3
TRENDING_DEFAULT_LIMIT = 8
TRENDING_MAX_LIMIT = 24

router = APIRouter()


async def enforce_view_rate_limit(request: Request) -> None:
    settings = get_settings()
    result = await check_rate_limit(
        get_redis(),
        bucket="opportunity_view",
        identifier=client_ip(request),
        max_requests=settings.rate_limit_ip_view_per_minute,
        window_seconds=60,
    )
    if not result.allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many requests",
            headers={"Retry-After": str(result.retry_after_seconds)},
        )


@router.post(
    "/opportunities/{slug}/view",
    dependencies=[Depends(enforce_view_rate_limit)],
)
def record_opportunity_view(slug: str, db: Session = Depends(get_db)) -> dict[str, bool]:
    try:
        opportunity_id = db.scalar(
            select(models.Opportunity.id).where(models.Opportunity.slug == slug)
        )
        if opportunity_id is None:
            raise HTTPException(status_code=404, detail="Opportunity not found")

        statement = insert(models.OpportunityViewCount).values(
            opportunity_id=opportunity_id,
            views=1,
            updated_at=func.now(),
        )
        statement = statement.on_conflict_do_update(
            index_elements=[models.OpportunityViewCount.opportunity_id],
            set_={
                "views": models.OpportunityViewCount.views + 1,
                "updated_at": func.now(),
            },
        )
        db.execute(statement)
        db.commit()
    except HTTPException:
        raise
    except SQLAlchemyError:
        # A counter outage must not affect a visitor opening an opportunity.
        db.rollback()

    return {"ok": True}


@router.get("/trending", response_model=TrendingResponse)
def get_trending(
    limit: int = Query(TRENDING_DEFAULT_LIMIT),
    db: Session = Depends(get_db),
) -> TrendingResponse:
    bounded_limit = max(1, min(limit, TRENDING_MAX_LIMIT))
    roles_filter = or_(
        models.Opportunity.category.in_(["internship", "job"]),
        models.Opportunity.meta["offers_ppi"].as_boolean().is_(True),
        models.Opportunity.meta["offers_ppo"].as_boolean().is_(True),
    )
    query = (
        select(models.Opportunity)
        .join(
            models.OpportunityViewCount,
            models.OpportunityViewCount.opportunity_id == models.Opportunity.id,
        )
        .options(*opportunity_list_load_options())
        .where(
            models.Opportunity.status == "active",
            exclude_stale_opportunities(),
            exclude_closed_competitions(),
            roles_filter,
            models.OpportunityViewCount.views >= TRENDING_MIN_VIEWS,
        )
        .order_by(models.OpportunityViewCount.views.desc(), models.Opportunity.id.desc())
        .limit(bounded_limit)
    )
    rows = db.execute(query).unique().scalars().all()
    return TrendingResponse(items=[OpportunityListItem.from_model(row) for row in rows])
