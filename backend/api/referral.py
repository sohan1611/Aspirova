"""Authenticated referral invite endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from api.auth import get_current_user
from api.deps import get_db
from api.schemas import ReferralClaimRequest, ReferralClaimResponse, ReferralMeResponse
from core import models
from core.referral import get_or_create_invite_code, record_referral

router = APIRouter()


@router.get("/referral/me", response_model=ReferralMeResponse)
def get_referral_me(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> ReferralMeResponse:
    code = get_or_create_invite_code(db, user)
    referral_count = db.scalar(
        select(func.count()).select_from(models.User).where(models.User.referred_by == user.id)
    )
    reward_active_until = db.scalar(
        select(func.max(models.Subscription.current_period_end)).where(
            models.Subscription.user_id == user.id,
            models.Subscription.status == "active",
            models.Subscription.razorpay_sub_id.is_(None),
            or_(
                models.Subscription.current_period_end.is_(None),
                models.Subscription.current_period_end > func.now(),
            ),
        )
    )
    return ReferralMeResponse(
        invite_code=code,
        referral_count=referral_count or 0,
        reward_active_until=reward_active_until,
    )


@router.post("/referral/claim", response_model=ReferralClaimResponse)
def claim_referral(
    request: ReferralClaimRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> ReferralClaimResponse:
    result = record_referral(db, user, request.code)
    return ReferralClaimResponse(referred=result.referred, reason=result.reason)
