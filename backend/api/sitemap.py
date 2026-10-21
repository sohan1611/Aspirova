"""Lean active slug lists for frontend sitemaps."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.deps import get_db
from api.filters import exclude_stale_opportunities
from api.schemas import SitemapCompany, SitemapOpportunity
from core import models

router = APIRouter()

SITEMAP_PAGE_SIZE = 5000


def _eligible_sitemap_opportunity_filters() -> tuple:
    return (
        models.Opportunity.status == "active",
        exclude_stale_opportunities(),
        models.Opportunity.closed_at.is_(None),
        models.Opportunity.is_hidden.is_not(True),
    )


@router.get("/sitemap-opportunities", response_model=list[SitemapOpportunity])
def get_sitemap_opportunities(
    page: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[SitemapOpportunity]:
    rows = db.execute(
        select(models.Opportunity.slug, models.Opportunity.last_seen_at)
        .where(*_eligible_sitemap_opportunity_filters())
        .order_by(models.Opportunity.id.asc())
        .offset(page * SITEMAP_PAGE_SIZE)
        .limit(SITEMAP_PAGE_SIZE)
    ).all()
    return [SitemapOpportunity(slug=slug, last_seen_at=last_seen_at) for slug, last_seen_at in rows]


@router.get("/sitemap-opportunities/count", response_model=dict[str, int])
def get_sitemap_opportunity_count(db: Session = Depends(get_db)) -> dict[str, int]:
    total = db.scalar(
        select(func.count(models.Opportunity.id)).where(*_eligible_sitemap_opportunity_filters())
    )
    return {"total": total or 0, "page_size": SITEMAP_PAGE_SIZE}


@router.get("/sitemap-companies", response_model=list[SitemapCompany])
def get_sitemap_companies(db: Session = Depends(get_db)) -> list[SitemapCompany]:
    rows = db.execute(
        select(models.Company.slug)
        .join(models.Opportunity, models.Opportunity.company_id == models.Company.id)
        .where(
            models.Opportunity.status == "active",
            exclude_stale_opportunities(),
        )
        .distinct()
        .order_by(models.Company.slug.asc())
    ).all()
    return [SitemapCompany(slug=slug) for (slug,) in rows]
