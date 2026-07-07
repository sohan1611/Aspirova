"""Lean active slug lists for frontend sitemap.xml."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps import get_db
from api.schemas import SitemapCompany, SitemapOpportunity
from core import models

router = APIRouter()


@router.get("/sitemap-opportunities", response_model=list[SitemapOpportunity])
def get_sitemap_opportunities(db: Session = Depends(get_db)) -> list[SitemapOpportunity]:
    rows = db.execute(
        select(models.Opportunity.slug, models.Opportunity.last_seen_at)
        .where(models.Opportunity.status == "active")
        .order_by(models.Opportunity.slug.asc())
    ).all()
    return [SitemapOpportunity(slug=slug, last_seen_at=last_seen_at) for slug, last_seen_at in rows]


@router.get("/sitemap-companies", response_model=list[SitemapCompany])
def get_sitemap_companies(db: Session = Depends(get_db)) -> list[SitemapCompany]:
    rows = db.execute(
        select(models.Company.slug)
        .join(models.Opportunity, models.Opportunity.company_id == models.Company.id)
        .where(models.Opportunity.status == "active")
        .distinct()
        .order_by(models.Company.slug.asc())
    ).all()
    return [SitemapCompany(slug=slug) for (slug,) in rows]
