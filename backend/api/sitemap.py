"""GET /sitemap-opportunities - lean active slug list for frontend sitemap.xml."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps import get_db
from api.schemas import SitemapOpportunity
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
