"""Authenticated, Pro-gated, daily-limited Career Copilot endpoint."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.auth import get_current_user
from api.deps import get_db
from api.schemas import CopilotRequest, CopilotResponse
from core import models
from core.config import get_settings
from core.gating import can
from core.ratelimit import check_rate_limit
from core.redis_client import get_redis
from pipeline.copilot import answer_copilot

router = APIRouter()

PRO_FEATURE_DETAIL = "Career Copilot is a Pro feature. Upgrade to use it."


async def enforce_copilot_daily_limit(
    user: models.User = Depends(get_current_user),
) -> models.User:
    """Enforce the configured daily limit against the authenticated user ID."""
    settings = get_settings()
    result = await check_rate_limit(
        get_redis(),
        bucket="copilot_daily",
        identifier=str(user.id),
        max_requests=settings.rate_limit_user_copilot_per_day,
        window_seconds=86_400,
    )
    if not result.allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many requests",
            headers={"Retry-After": str(result.retry_after_seconds)},
        )
    return user


@router.post("/copilot", response_model=CopilotResponse)
async def run_copilot(
    request: CopilotRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(enforce_copilot_daily_limit),
) -> CopilotResponse:
    if not can(db, user, "copilot"):
        raise HTTPException(status_code=403, detail=PRO_FEATURE_DETAIL)

    result = await answer_copilot(db, message=request.message)
    return CopilotResponse.model_validate(result)
