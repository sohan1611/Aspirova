"""Company landing-page endpoint for SSR company opportunity pages."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from api.deps import get_db
from api.filters import exclude_experienced_only_opportunities, exclude_stale_opportunities
from api.opportunity_loading import opportunity_list_load_options
from api.schemas import (
    CompanyListItem,
    CompanyPage,
    CompanySummary,
    OpportunityListItem,
)
from core import models

router = APIRouter()


@router.get("/companies/top", response_model=list[CompanyListItem])
def list_top_companies(
    limit: int = Query(12, ge=1, le=24),
    db: Session = Depends(get_db),
) -> list[CompanyListItem]:
    rows = db.execute(
        select(
            models.Company.slug,
            models.Company.name,
            models.Company.domain,
            models.Company.logo_url,
            func.count(models.Opportunity.id).label("active_count"),
        )
        .join(
            models.Opportunity,
            (models.Opportunity.company_id == models.Company.id)
            & (models.Opportunity.status == "active")
            & exclude_stale_opportunities()
            & exclude_experienced_only_opportunities(),
        )
        .where(models.Company.prestige_rank.is_not(None))
        .group_by(
            models.Company.id,
            models.Company.slug,
            models.Company.name,
            models.Company.domain,
            models.Company.logo_url,
            models.Company.prestige_rank,
        )
        .order_by(models.Company.prestige_rank.asc(), models.Company.name.asc())
        .limit(limit)
    ).all()

    return [
        CompanyListItem(
            slug=slug,
            name=name,
            domain=domain,
            logo_url=logo_url,
            active_count=active_count,
        )
        for slug, name, domain, logo_url, active_count in rows
    ]


@router.get("/companies", response_model=list[CompanyListItem])
def list_companies(db: Session = Depends(get_db)) -> list[CompanyListItem]:
    rows = db.execute(
        select(
            models.Company.slug,
            models.Company.name,
            models.Company.domain,
            models.Company.logo_url,
            func.count(models.Opportunity.id).label("active_count"),
        )
        .join(
            models.Opportunity,
            (models.Opportunity.company_id == models.Company.id)
            & (models.Opportunity.status == "active")
            & exclude_stale_opportunities()
            & exclude_experienced_only_opportunities(),
        )
        .group_by(
            models.Company.id,
            models.Company.slug,
            models.Company.name,
            models.Company.domain,
            models.Company.logo_url,
        )
        .order_by(desc("active_count"), models.Company.name.asc())
    ).all()

    return [
        CompanyListItem(
            slug=slug,
            name=name,
            domain=domain,
            logo_url=logo_url,
            active_count=active_count,
        )
        for slug, name, domain, logo_url, active_count in rows
    ]


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
        .options(*opportunity_list_load_options())
        .where(
            models.Opportunity.company_id == company.id,
            models.Opportunity.status == "active",
            exclude_stale_opportunities(),
            exclude_experienced_only_opportunities(),
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
