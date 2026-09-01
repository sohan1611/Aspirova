"""Authenticated CRUD endpoints for reusable feed searches."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.auth import get_current_user
from api.deps import get_db
from api.schemas import (
    SavedSearchAlertsUpdate,
    SavedSearchCreate,
    SavedSearchItem,
    SavedSearchParams,
)
from core import models
from core.config import get_settings
from core.ratelimit import check_rate_limit
from core.redis_client import get_redis

router = APIRouter()

_ALLOWED_CATEGORIES = {"internship", "job", "hackathon", "competition", "scholarship"}
_ALLOWED_KINDS = {"roles", "competitions"}
_ALLOWED_SCOPES = {"abroad", "domestic", "both"}
_ALLOWED_SOURCES = {"direct", "unstop", "remoteok", "devpost"}
_ALLOWED_EXPERIENCE = {"early"}
_MAX_SAVED_SEARCHES_PER_USER = 25


async def enforce_saved_search_write_limit(
    user: models.User = Depends(get_current_user),
) -> models.User:
    """Apply the configured authenticated-user limit to saved-search writes."""
    settings = get_settings()
    result = await check_rate_limit(
        get_redis(),
        bucket="saved_search",
        identifier=str(user.id),
        max_requests=settings.rate_limit_user_saved_search_write_per_minute,
        window_seconds=60,
    )
    if not result.allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many requests",
            headers={"Retry-After": str(result.retry_after_seconds)},
        )
    return user


def _validated_params(params: SavedSearchParams) -> dict:
    values = params.model_dump(exclude_none=True)

    if params.q is not None and len(params.q) > 200:
        raise HTTPException(status_code=422, detail="q must be at most 200 characters")
    if params.category is not None and params.category not in _ALLOWED_CATEGORIES:
        raise HTTPException(status_code=422, detail="Invalid category")
    if params.kind is not None and params.kind not in _ALLOWED_KINDS:
        raise HTTPException(status_code=422, detail="Invalid kind")
    if params.scope is not None and params.scope not in _ALLOWED_SCOPES:
        raise HTTPException(status_code=422, detail="Invalid scope")
    if params.country is not None and (len(params.country) != 2 or not params.country.isalpha()):
        raise HTTPException(status_code=422, detail="country must be a two-letter code")
    if params.source is not None and params.source not in _ALLOWED_SOURCES:
        raise HTTPException(status_code=422, detail="Invalid source")
    if params.experience is not None and params.experience not in _ALLOWED_EXPERIENCE:
        raise HTTPException(status_code=422, detail="Invalid experience")

    return values


def _item(saved_search: models.SavedSearch) -> SavedSearchItem:
    return SavedSearchItem(
        id=saved_search.id,
        name=saved_search.name,
        params=SavedSearchParams.model_validate(saved_search.params),
        alerts_enabled=saved_search.alerts_enabled,
        last_alerted_at=saved_search.last_alerted_at,
        created_at=saved_search.created_at,
    )


def _get_owned_saved_search_or_404(
    db: Session,
    user: models.User,
    saved_search_id: int,
) -> models.SavedSearch:
    saved_search = db.scalar(
        select(models.SavedSearch).where(
            models.SavedSearch.id == saved_search_id,
            models.SavedSearch.user_id == user.id,
        )
    )
    if saved_search is None:
        raise HTTPException(status_code=404, detail="Saved search not found")
    return saved_search


@router.post("/saved-searches", response_model=SavedSearchItem)
def create_saved_search(
    payload: SavedSearchCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(enforce_saved_search_write_limit),
) -> SavedSearchItem:
    params = _validated_params(payload.params)
    # Serialize creates for one user so two concurrent requests cannot both
    # observe 24 saved searches and exceed the cap.
    db.scalar(select(models.User.id).where(models.User.id == user.id).with_for_update())
    count = db.scalar(
        select(func.count())
        .select_from(models.SavedSearch)
        .where(models.SavedSearch.user_id == user.id)
    )
    if count >= _MAX_SAVED_SEARCHES_PER_USER:
        raise HTTPException(status_code=409, detail="Saved search limit of 25 reached")

    saved_search = models.SavedSearch(
        user_id=user.id,
        name=payload.name,
        params=params,
        alerts_enabled=payload.alerts_enabled,
    )
    db.add(saved_search)
    db.commit()
    db.refresh(saved_search)
    return _item(saved_search)


@router.get("/saved-searches", response_model=list[SavedSearchItem])
def list_saved_searches(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> list[SavedSearchItem]:
    saved_searches = db.scalars(
        select(models.SavedSearch)
        .where(models.SavedSearch.user_id == user.id)
        .order_by(models.SavedSearch.created_at.desc(), models.SavedSearch.id.desc())
    ).all()
    return [_item(saved_search) for saved_search in saved_searches]


@router.delete("/saved-searches/{saved_search_id}", status_code=204)
def delete_saved_search(
    saved_search_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(enforce_saved_search_write_limit),
) -> None:
    saved_search = _get_owned_saved_search_or_404(db, user, saved_search_id)
    db.delete(saved_search)
    db.commit()


@router.patch("/saved-searches/{saved_search_id}", response_model=SavedSearchItem)
def update_saved_search_alerts(
    saved_search_id: int,
    payload: SavedSearchAlertsUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(enforce_saved_search_write_limit),
) -> SavedSearchItem:
    saved_search = _get_owned_saved_search_or_404(db, user, saved_search_id)
    saved_search.alerts_enabled = payload.alerts_enabled
    db.commit()
    db.refresh(saved_search)
    return _item(saved_search)
