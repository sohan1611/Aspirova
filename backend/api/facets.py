"""Facet lists for picker-style feed filters."""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.deps import get_db
from api.schemas import FacetsResponse
from core import models

router = APIRouter()


@router.get("/facets", response_model=FacetsResponse)
def get_facets(db: Session = Depends(get_db)) -> FacetsResponse:
    company_count = func.count(models.Opportunity.id).label("active_count")
    company_rows = db.execute(
        select(models.Company.name, company_count)
        .join(
            models.Opportunity,
            models.Opportunity.company_id == models.Company.id,
        )
        .where(models.Opportunity.status == "active")
        .group_by(models.Company.name)
        .order_by(company_count.desc(), models.Company.name.asc())
    ).all()

    location_count = func.count(models.Opportunity.id).label("active_count")
    location_rows = db.execute(
        select(models.Opportunity.location, location_count)
        .where(
            models.Opportunity.status == "active",
            models.Opportunity.location.is_not(None),
            models.Opportunity.location != "",
        )
        .group_by(models.Opportunity.location)
        .order_by(location_count.desc(), models.Opportunity.location.asc())
    ).all()

    return FacetsResponse(
        companies=[name for name, _active_count in company_rows],
        locations=[location for location, _active_count in location_rows if location is not None],
    )
