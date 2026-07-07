"""Company landing-page endpoint for SSR company opportunity pages."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from api.deps import get_db
from api.schemas import CompanyPage, CompanySummary, OpportunityListItem
from core import models

router = APIRouter()


@router.get("/company/{slug}", response_model=CompanyPage)
def get_company_page(
    slug: str,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> CompanyPage:
    company = db.scalar(select(models.Company).where(models.Company.slug == slug))
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")

    total_count = func.count().over().label("total_count")
    query = (
        select(models.Opportunity, total_count)
        .options(joinedload(models.Opportunity.company))
        .where(
            models.Opportunity.company_id == company.id,
            models.Opportunity.status == "active",
        )
        .order_by(models.Opportunity.first_seen_at.desc(), models.Opportunity.id.desc())
    )

    rows = db.execute(query.offset((page - 1) * limit).limit(limit)).unique().all()
    items = [OpportunityListItem.from_model(row.Opportunity) for row in rows]
    total = rows[0].total_count if rows else 0

    return CompanyPage(
        company=CompanySummary.model_validate(company),
        items=items,
        total=total,
        page=page,
        limit=limit,
    )
