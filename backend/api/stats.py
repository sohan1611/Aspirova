"""Public aggregate statistics for the homepage trust bar."""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.deps import get_db
from api.filters import exclude_stale_opportunities
from api.schemas import StatsResponse
from core import models

router = APIRouter()


@router.get("/stats", response_model=StatsResponse)
def get_stats(db: Session = Depends(get_db)) -> StatsResponse:
    stats = db.execute(
        select(
            func.count(models.Opportunity.id).label("opportunities"),
            func.count(func.distinct(models.Opportunity.company_id)).label("companies"),
            func.count(func.distinct(models.Opportunity.primary_source)).label("sources"),
            func.max(models.Opportunity.last_seen_at).label("updated_at"),
        ).where(
            models.Opportunity.status == "active",
            exclude_stale_opportunities(),
        )
    ).one()

    return StatsResponse(
        opportunities=stats.opportunities,
        companies=stats.companies,
        sources=stats.sources,
        updated_at=stats.updated_at,
    )
