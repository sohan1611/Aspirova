"""Authenticated, plan-independent watches for Hiring Calendar programmes."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from api.auth import get_current_user
from api.deps import get_db
from core import models
from core.config import get_settings
from core.hiring_calendar import IST
from core.programme_watches import programme_signature
from core.ratelimit import check_rate_limit
from core.redis_client import get_redis

router = APIRouter()
MAX_WATCHES_PER_USER = 50


class ProgrammeWatchItem(BaseModel):
    id: int
    programme_slug: str
    programme_name: str
    programme_url: str
    created_at: datetime
    notified_at: datetime | None


def _item(watch: models.ProgrammeWatch, programme: models.Programme) -> ProgrammeWatchItem:
    return ProgrammeWatchItem(
        id=watch.id,
        programme_slug=programme.slug,
        programme_name=programme.name,
        programme_url=programme.url,
        created_at=watch.created_at,
        notified_at=watch.notified_at,
    )


async def enforce_programme_watch_write_limit(
    user: models.User = Depends(get_current_user),
) -> models.User:
    result = await check_rate_limit(
        get_redis(),
        bucket="programme_watch_write",
        identifier=str(user.id),
        max_requests=get_settings().rate_limit_user_programme_watch_write_per_minute,
        window_seconds=60,
    )
    if not result.allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many requests",
            headers={"Retry-After": str(result.retry_after_seconds)},
        )
    return user


@router.get("/calendar/watches", response_model=list[ProgrammeWatchItem])
def list_programme_watches(
    response: Response,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> list[ProgrammeWatchItem]:
    response.headers["Cache-Control"] = "no-store"
    rows = db.execute(
        select(models.ProgrammeWatch, models.Programme)
        .join(models.Programme, models.Programme.id == models.ProgrammeWatch.programme_id)
        .where(models.ProgrammeWatch.user_id == user.id)
        .order_by(models.ProgrammeWatch.created_at.desc(), models.ProgrammeWatch.id.desc())
    ).all()
    return [_item(watch, programme) for watch, programme in rows]


@router.put("/calendar/{programme_slug}/watch", response_model=ProgrammeWatchItem)
def watch_programme(
    programme_slug: str,
    response: Response,
    db: Session = Depends(get_db),
    user: models.User = Depends(enforce_programme_watch_write_limit),
) -> ProgrammeWatchItem:
    response.headers["Cache-Control"] = "no-store"
    # Serialize all watch writes for this user so concurrent creates cannot
    # both pass the cap, and a retried PUT cannot reset an existing baseline.
    db.scalar(select(models.User.id).where(models.User.id == user.id).with_for_update())
    programme = db.scalar(
        select(models.Programme)
        .options(selectinload(models.Programme.editions))
        .where(models.Programme.slug == programme_slug, models.Programme.is_active.is_(True))
    )
    if programme is None:
        raise HTTPException(status_code=404, detail="Programme not found")
    watch = db.scalar(
        select(models.ProgrammeWatch).where(
            models.ProgrammeWatch.user_id == user.id,
            models.ProgrammeWatch.programme_id == programme.id,
        )
    )
    if watch is None:
        count = db.scalar(
            select(func.count())
            .select_from(models.ProgrammeWatch)
            .where(models.ProgrammeWatch.user_id == user.id)
        )
        if count >= MAX_WATCHES_PER_USER:
            raise HTTPException(status_code=409, detail="Programme watch limit of 50 reached")
        watch = models.ProgrammeWatch(
            user_id=user.id,
            programme_id=programme.id,
            notified_signature=programme_signature(programme, now=datetime.now(IST)),
        )
        db.add(watch)
    db.commit()
    db.refresh(watch)
    return _item(watch, programme)


@router.delete("/calendar/{programme_slug}/watch", status_code=204)
def unwatch_programme(
    programme_slug: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(enforce_programme_watch_write_limit),
) -> Response:
    db.scalar(select(models.User.id).where(models.User.id == user.id).with_for_update())
    programme_id = db.scalar(
        select(models.Programme.id).where(models.Programme.slug == programme_slug)
    )
    if programme_id is None:
        raise HTTPException(status_code=404, detail="Programme not found")
    db.execute(
        delete(models.ProgrammeWatch).where(
            models.ProgrammeWatch.user_id == user.id,
            models.ProgrammeWatch.programme_id == programme_id,
        )
    )
    # Keep in-app history, but cancel unsent updates. Rewatching starts from
    # the new baseline rather than resurrecting an older failed-email backlog.
    for notification in db.scalars(
        select(models.Notification).where(
            models.Notification.user_id == user.id,
            models.Notification.type == "programme_watch",
            models.Notification.meta["programme_id"].as_integer() == programme_id,
            models.Notification.meta["email_pending"].as_boolean().is_(True),
        )
    ):
        notification.meta = {**notification.meta, "email_pending": False}
    db.commit()
    return Response(status_code=204, headers={"Cache-Control": "no-store"})
