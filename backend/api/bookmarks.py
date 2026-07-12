"""POST/PATCH/DELETE /bookmarks + GET /bookmarks - the authenticated surface
in Phase 1."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from api.auth import get_current_user
from api.deps import get_db
from api.schemas import BookmarkStatusUpdate, SavedOpportunityItem
from core import models
from core.config import get_settings
from core.ratelimit import check_rate_limit
from core.redis_client import get_redis

router = APIRouter()


async def enforce_bookmark_write_limit(
    user: models.User = Depends(get_current_user),
) -> models.User:
    """Per-user write limit (Doc handoffs/PHASE-2-HANDOFF.md sec 11.4) -
    enforced here, as a route dependency, rather than in the global ASGI
    middleware: it needs the *authenticated* user, which only exists after
    get_current_user has already run."""
    settings = get_settings()
    result = await check_rate_limit(
        get_redis(),
        bucket="bookmark_write",
        identifier=str(user.id),
        max_requests=settings.rate_limit_user_bookmark_write_per_minute,
        window_seconds=60,
    )
    if not result.allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many requests",
            headers={"Retry-After": str(result.retry_after_seconds)},
        )
    return user


def _get_opportunity_or_404(db: Session, slug: str) -> models.Opportunity:
    opportunity = db.scalar(select(models.Opportunity).where(models.Opportunity.slug == slug))
    if opportunity is None:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    return opportunity


@router.post("/bookmarks/{opportunity_slug}", status_code=204)
def add_bookmark(
    opportunity_slug: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(enforce_bookmark_write_limit),
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
    user: models.User = Depends(enforce_bookmark_write_limit),
) -> None:
    opportunity = _get_opportunity_or_404(db, opportunity_slug)
    existing = db.get(models.Bookmark, (user.id, opportunity.id))
    if existing is not None:
        db.delete(existing)
        db.commit()


@router.patch("/bookmarks/{opportunity_slug}", status_code=204)
def update_bookmark_status(
    opportunity_slug: str,
    update: BookmarkStatusUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(enforce_bookmark_write_limit),
) -> None:
    opportunity = _get_opportunity_or_404(db, opportunity_slug)
    bookmark = db.get(models.Bookmark, (user.id, opportunity.id))
    if bookmark is None:
        raise HTTPException(status_code=404, detail="Bookmark not found")

    bookmark.status = update.status
    db.commit()


@router.get("/bookmarks", response_model=list[SavedOpportunityItem])
def list_bookmarks(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> list[SavedOpportunityItem]:
    rows = db.execute(
        select(models.Opportunity, models.Bookmark.status)
        .join(models.Bookmark, models.Bookmark.opportunity_id == models.Opportunity.id)
        .options(joinedload(models.Opportunity.company))
        .where(models.Bookmark.user_id == user.id)
        .order_by(models.Bookmark.created_at.desc())
    ).all()
    return [SavedOpportunityItem.from_models(opportunity, status) for opportunity, status in rows]
