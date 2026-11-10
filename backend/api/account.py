"""Authenticated account profile, plan state, and subscription management."""

import json
from datetime import UTC, datetime

import razorpay
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.auth import get_current_user
from api.deps import get_db
from api.payments import _razorpay_client
from api.schemas import AccountMe, AccountUpdate, DigestPreview, DigestStatus, PlanState
from core import models
from core.gating import active_subscription_filters, get_features
from core.ratelimit import check_rate_limit
from core.redis_client import get_redis
from pipeline.notifications import preview_daily_digest

router = APIRouter()

MAX_RESUME_METADATA_BYTES = 8 * 1024
MAX_RESUME_FILENAME_LENGTH = 255


def _validate_resume_metadata(resume: dict | None) -> None:
    if resume is None:
        return
    if not isinstance(resume, dict):
        raise HTTPException(status_code=400, detail="resume must be an object")

    filename = resume.get("filename")
    if filename is not None and not isinstance(filename, str):
        raise HTTPException(status_code=400, detail="resume filename must be a string")
    if isinstance(filename, str) and len(filename) > MAX_RESUME_FILENAME_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"resume filename must be at most {MAX_RESUME_FILENAME_LENGTH} characters",
        )

    try:
        metadata_size = len(
            json.dumps(resume, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail="resume metadata must be JSON serializable",
        ) from exc

    if metadata_size > MAX_RESUME_METADATA_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"resume metadata must be at most {MAX_RESUME_METADATA_BYTES} bytes",
        )


def _active_subscription_query(user: models.User):
    return (
        select(models.Subscription, models.Plan)
        .join(models.Plan, models.Plan.id == models.Subscription.plan_id)
        .where(
            models.Subscription.user_id == user.id,
            *active_subscription_filters(),
        )
        .order_by(models.Subscription.created_at.desc())
        .limit(1)
    )


def _digest_status(db: Session, user: models.User) -> DigestStatus | None:
    """The newest digest attempt and the last one that actually went out."""
    newest = db.scalar(
        select(models.Notification.status)
        .where(models.Notification.user_id == user.id, models.Notification.type == "digest")
        .order_by(models.Notification.id.desc())
        .limit(1)
    )
    if newest is None:
        return None
    last_sent = db.execute(
        select(models.Notification.sent_at, models.Notification.meta)
        .where(
            models.Notification.user_id == user.id,
            models.Notification.type == "digest",
            models.Notification.status == "sent",
        )
        .order_by(models.Notification.sent_at.desc().nullslast())
        .limit(1)
    ).first()
    count = 0
    if last_sent is not None and isinstance(last_sent.meta, dict):
        for key in ("opportunity_ids", "hackathon_ids"):
            values = last_sent.meta.get(key)
            if isinstance(values, list):
                count += len(values)
    sent_at = last_sent.sent_at if last_sent is not None else None
    if sent_at is not None and sent_at.tzinfo is None:
        sent_at = sent_at.replace(tzinfo=UTC)
    return DigestStatus(
        last_sent_at=sent_at,
        last_sent_count=count,
        last_attempt_failed=newest == "failed",
    )


def _build_account_me(db: Session, user: models.User) -> AccountMe:
    features = get_features(db, user)
    active = db.execute(_active_subscription_query(user)).first()

    if active is None:
        plan = db.scalar(select(models.Plan).where(models.Plan.key == "free"))
        if plan is None:
            raise RuntimeError(
                "the 'free' plan row is missing - run scripts/seed_plans.py before serving traffic"
            )
        status = "free"
        current_period_end = None
        cancel_at_period_end = False
    else:
        subscription, plan = active
        status = subscription.status
        current_period_end = subscription.current_period_end
        cancel_at_period_end = subscription.cancel_at_period_end

    return AccountMe(
        email=user.email,
        display_name=user.display_name,
        college=user.college,
        graduation_year=user.graduation_year,
        created_at=user.created_at,
        invite_code=user.invite_code,
        notification_prefs=user.notification_prefs or {},
        field_profile=user.field_profile,
        skills=user.skills,
        exposure=user.exposure,
        resume=user.resume,
        plan=PlanState(
            key=plan.key,
            price_paise=plan.price_paise,
            billing=plan.billing,
            features=features,
            status=status,
            current_period_end=current_period_end,
            cancel_at_period_end=cancel_at_period_end,
        ),
        digest_status=_digest_status(db, user),
    )


@router.get("/account/me", response_model=AccountMe)
def get_account_me(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> AccountMe:
    return _build_account_me(db, user)


async def enforce_account_export_limit(
    user: models.User = Depends(get_current_user),
) -> models.User:
    result = await check_rate_limit(
        get_redis(),
        bucket="account_export",
        identifier=str(user.id),
        max_requests=5,
        window_seconds=60,
    )
    if not result.allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many requests",
            headers={"Retry-After": str(result.retry_after_seconds)},
        )
    return user


@router.get("/account/export")
def export_account(
    response: Response,
    db: Session = Depends(get_db),
    user: models.User = Depends(enforce_account_export_limit),
) -> dict:
    response.headers["Cache-Control"] = "no-store"
    tracked = db.execute(
        select(models.Bookmark, models.Opportunity, models.Company.name)
        .select_from(models.Bookmark)
        .join(models.Opportunity, models.Opportunity.id == models.Bookmark.opportunity_id)
        .outerjoin(models.Company, models.Company.id == models.Opportunity.company_id)
        .where(models.Bookmark.user_id == user.id)
        .order_by(models.Bookmark.created_at, models.Bookmark.opportunity_id)
    ).all()
    searches = db.scalars(
        select(models.SavedSearch)
        .where(models.SavedSearch.user_id == user.id)
        .order_by(models.SavedSearch.created_at, models.SavedSearch.id)
    ).all()
    followed = db.execute(
        select(models.Company, models.DreamCompany.roles)
        .join(models.DreamCompany, models.DreamCompany.company_id == models.Company.id)
        .where(models.DreamCompany.user_id == user.id)
        .order_by(models.Company.slug)
    ).all()
    subscription = db.execute(
        select(models.Subscription, models.Plan.key)
        .join(models.Plan, models.Plan.id == models.Subscription.plan_id)
        .where(models.Subscription.user_id == user.id)
        .order_by(models.Subscription.created_at.desc(), models.Subscription.id.desc())
        .limit(1)
    ).first()
    resume = user.resume if isinstance(user.resume, dict) else None
    return {
        "exported_at": datetime.now(UTC),
        "account": {
            key: getattr(user, key)
            for key in (
                "email",
                "display_name",
                "college",
                "graduation_year",
                "field_profile",
                "skills",
                "exposure",
                "notification_prefs",
                "created_at",
            )
        },
        "resume": (
            {key: resume.get(key) for key in ("filename", "uploaded_at", "ats")}
            if resume is not None
            else None
        ),
        "tracked_opportunities": [
            {
                "slug": opportunity.slug,
                "title": opportunity.title,
                "company": company_name,
                "status": bookmark.status,
                "saved_at": bookmark.created_at,
            }
            for bookmark, opportunity, company_name in tracked
        ],
        "saved_searches": [
            {
                "name": search.name,
                "params": search.params,
                "alerts_enabled": search.alerts_enabled,
                "created_at": search.created_at,
            }
            for search in searches
        ],
        "followed_companies": [
            {"name": company.name, "slug": company.slug, "domains": roles}
            for company, roles in followed
        ],
        "subscription": {
            "plan_key": subscription[1] if subscription else "free",
            "status": subscription[0].status if subscription else "free",
            "current_period_end": subscription[0].current_period_end if subscription else None,
        },
    }


@router.patch("/account/me", response_model=AccountMe)
def update_account_me(
    request: AccountUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> AccountMe:
    for field in ("display_name", "college", "graduation_year"):
        if field in request.model_fields_set:
            setattr(user, field, getattr(request, field))

    if "notification_prefs" in request.model_fields_set and request.notification_prefs is not None:
        user.notification_prefs = {
            **(user.notification_prefs or {}),
            **request.notification_prefs,
        }

    if "resume" in request.model_fields_set:
        _validate_resume_metadata(request.resume)

    if "field_profile" in request.model_fields_set:
        profile = request.field_profile
        stored = user.field_profile if isinstance(user.field_profile, dict) else {}
        if isinstance(profile, dict) and "country" not in profile and stored.get("country"):
            # A client that does not send the country (an older tab saving
            # interests) must not erase the one the member chose.
            profile = {**profile, "country": stored["country"]}
        user.field_profile = profile

    for field in ("skills", "exposure", "resume"):
        if field in request.model_fields_set:
            setattr(user, field, getattr(request, field))

    db.commit()
    return _build_account_me(db, user)


DIGEST_PREVIEW_PER_MINUTE = 6


async def enforce_digest_preview_limit(
    user: models.User = Depends(get_current_user),
) -> models.User:
    """A preview runs the full digest selection, so cap it per reader."""
    result = await check_rate_limit(
        get_redis(),
        bucket="digest_preview",
        identifier=str(user.id),
        max_requests=DIGEST_PREVIEW_PER_MINUTE,
        window_seconds=60,
    )
    if not result.allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many requests",
            headers={"Retry-After": str(result.retry_after_seconds)},
        )
    return user


@router.get("/account/digest-preview", response_model=DigestPreview)
def digest_preview(
    response: Response,
    db: Session = Depends(get_db),
    user: models.User = Depends(enforce_digest_preview_limit),
) -> DigestPreview:
    """Render the reader's next daily digest without sending or recording it."""
    draft = preview_daily_digest(db, user)
    # The body carries this reader's own signed unsubscribe link.
    response.headers["Cache-Control"] = "no-store"
    return DigestPreview(
        subject=draft.subject,
        html=draft.html,
        listing_count=len(draft.opportunities),
        hackathon_count=len(draft.hackathons),
        window_start=draft.window_start,
    )


@router.post("/subscription/cancel")
def cancel_subscription(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> dict[str, str | datetime | None]:
    subscription = db.scalar(
        select(models.Subscription)
        .where(
            models.Subscription.user_id == user.id,
            models.Subscription.status.in_(("active", "trialing")),
            models.Subscription.razorpay_sub_id.isnot(None),
        )
        .order_by(models.Subscription.created_at.desc())
        .limit(1)
    )
    if subscription is None:
        raise HTTPException(status_code=404, detail="No active subscription")

    if subscription.cancel_at_period_end:
        return {
            "status": "cancel_scheduled",
            "current_period_end": subscription.current_period_end,
        }

    client = _razorpay_client()
    try:
        client.subscription.cancel(
            subscription.razorpay_sub_id,
            {"cancel_at_cycle_end": 1},
        )
    except razorpay.errors.BadRequestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (razorpay.errors.GatewayError, razorpay.errors.ServerError) as exc:
        raise HTTPException(status_code=502, detail="Payment provider error") from exc

    subscription.cancel_at_period_end = True
    db.commit()

    return {
        "status": "cancel_scheduled",
        "current_period_end": subscription.current_period_end,
    }
