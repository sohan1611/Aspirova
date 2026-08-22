"""Facet lists for picker-style feed filters."""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.deps import get_db
from api.filters import exclude_experienced_only_opportunities, exclude_stale_opportunities
from api.schemas import FacetsResponse
from core import models

router = APIRouter()


@router.get("/facets", response_model=FacetsResponse)
def get_facets(db: Session = Depends(get_db)) -> FacetsResponse:
    company_rows = db.execute(
        select(models.Company.name)
        .join(
            models.Opportunity,
            models.Opportunity.company_id == models.Company.id,
        )
        .where(
            models.Opportunity.status == "active",
            exclude_stale_opportunities(),
            exclude_experienced_only_opportunities(),
        )
        .group_by(models.Company.name)
        .order_by(func.lower(models.Company.name).asc(), models.Company.name.asc())
    ).all()

    location_rows = db.execute(
        select(models.Opportunity.location)
        .where(
            models.Opportunity.status == "active",
            exclude_stale_opportunities(),
            exclude_experienced_only_opportunities(),
            models.Opportunity.location.is_not(None),
            models.Opportunity.location != "",
        )
        .group_by(models.Opportunity.location)
        .order_by(
            func.lower(models.Opportunity.location).asc(),
            models.Opportunity.location.asc(),
        )
    ).all()

    return FacetsResponse(
        companies=[name for (name,) in company_rows],
        locations=[location for (location,) in location_rows if location is not None],
    )
