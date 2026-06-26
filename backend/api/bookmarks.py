"""POST/DELETE /bookmarks + GET /bookmarks - the one authenticated surface
in Phase 1. BLOCKED ON CREDENTIALS: depends on api/auth.py, untested
against a real Supabase session as of this writing."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from api.auth import get_current_user
from api.deps import get_db
from api.schemas import OpportunityListItem
from core import models

router = APIRouter()


def _get_opportunity_or_404(db: Session, slug: str) -> models.Opportunity:
    opportunity = db.scalar(select(models.Opportunity).where(models.Opportunity.slug == slug))
    if opportunity is None:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    return opportunity


@router.post("/bookmarks/{opportunity_slug}", status_code=204)
def add_bookmark(
    opportunity_slug: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> None:
    opportunity = _get_opportunity_or_404(db, opportunity_slug)
    existing = db.get(models.Bookmark, (user.id, opportunity.id))
    if existing is None:
        db.add(models.Bookmark(user_id=user.id, opportunity_id=opportunity.id))
        db.commit()


@router.delete("/bookmarks/{opportunity_slug}", status_code=204)
def remove_bookmark(
    opportunity_slug: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> None:
    opportunity = _get_opportunity_or_404(db, opportunity_slug)
    existing = db.get(models.Bookmark, (user.id, opportunity.id))
    if existing is not None:
        db.delete(existing)
        db.commit()


@router.get("/bookmarks", response_model=list[OpportunityListItem])
def list_bookmarks(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> list[OpportunityListItem]:
    rows = db.scalars(
        select(models.Opportunity)
        .join(models.Bookmark, models.Bookmark.opportunity_id == models.Opportunity.id)
        .options(joinedload(models.Opportunity.company))
        .where(models.Bookmark.user_id == user.id)
        .order_by(models.Bookmark.created_at.desc())
    ).all()
    return [OpportunityListItem.from_model(o) for o in rows]
