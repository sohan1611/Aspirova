"""GET /opportunity/{slug} - the SSR-able detail endpoint (Doc 01 sec 11
HANDOFF: every opportunity needs a clean, indexable detail view)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from api.deps import get_db
from api.schemas import OpportunityDetail
from core import models

router = APIRouter()


@router.get("/opportunity/{slug}", response_model=OpportunityDetail)
def get_opportunity(slug: str, db: Session = Depends(get_db)) -> OpportunityDetail:
    opportunity = db.scalar(
        select(models.Opportunity)
        .options(joinedload(models.Opportunity.company))
        .where(models.Opportunity.slug == slug)
    )
    if opportunity is None:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    return OpportunityDetail.from_model(opportunity)
