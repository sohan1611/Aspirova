"""POST/DELETE/GET /dream-companies - Pro/Pro-Lite feature (Doc 01 sec 10,
Doc 03 sec 4.2). Per-plan limits are enforced entirely through can()
(Doc 08 sec 1 hard rule) - no scattered `if plan == ...` anywhere here.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.auth import get_current_user
from api.deps import get_db
from api.schemas import DreamCompanyItem
from core import models
from core.config import get_settings
from core.gating import can
from core.ratelimit import check_rate_limit
from core.redis_client import get_redis

router = APIRouter()


async def enforce_dream_company_write_limit(
    user: models.User = Depends(get_current_user),
) -> models.User:
    """Per-user write limit (Doc handoffs/PHASE-2-HANDOFF.md sec 11.4) -
    enforced here, as a route dependency, rather than in the global ASGI
    middleware: it needs the *authenticated* user, which only exists after
    get_current_user has already run."""
    settings = get_settings()
    result = await check_rate_limit(
        get_redis(),
        bucket="dream_company_write",
        identifier=str(user.id),
        max_requests=settings.rate_limit_user_dream_company_write_per_minute,
        window_seconds=60,
    )
    if not result.allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many requests",
            headers={"Retry-After": str(result.retry_after_seconds)},
        )
    return user


def _get_company_or_404(db: Session, slug: str) -> models.Company:
    company = db.scalar(select(models.Company).where(models.Company.slug == slug))
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")
    return company


def _get_existing(db: Session, user_id, company_id) -> models.DreamCompany | None:
    # dream_companies' PK is a bare `id` (Doc 03 sec 4.2), not the
    # (user_id, company_id) composite - unlike bookmarks, session.get()
    # can't be used here; look it up via the unique constraint instead.
    return db.scalar(
        select(models.DreamCompany).where(
            models.DreamCompany.user_id == user_id,
            models.DreamCompany.company_id == company_id,
        )
    )


@router.post("/dream-companies/{company_slug}", status_code=204)
def add_dream_company(
    company_slug: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(enforce_dream_company_write_limit),
) -> None:
    company = _get_company_or_404(db, company_slug)
    existing = _get_existing(db, user.id, company.id)
    if existing is not None:
        return

    limit = can(db, user, "dream_companies_limit")
    if limit is not None:  # None = unlimited (Doc 03 sec 4.1)
        current_count = db.scalar(
            select(func.count())
            .select_from(models.DreamCompany)
            .where(models.DreamCompany.user_id == user.id)
        )
        if current_count >= limit:
            raise HTTPException(
                status_code=403,
                detail=f"Dream company limit reached for your plan ({limit}). Upgrade for more.",
            )

    db.add(models.DreamCompany(user_id=user.id, company_id=company.id))
    db.commit()


@router.delete("/dream-companies/{company_slug}", status_code=204)
def remove_dream_company(
    company_slug: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(enforce_dream_company_write_limit),
) -> None:
    company = _get_company_or_404(db, company_slug)
    existing = _get_existing(db, user.id, company.id)
    if existing is not None:
        db.delete(existing)
        db.commit()


@router.get("/dream-companies", response_model=list[DreamCompanyItem])
def list_dream_companies(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> list[DreamCompanyItem]:
    companies = db.scalars(
        select(models.Company)
        .join(models.DreamCompany, models.DreamCompany.company_id == models.Company.id)
        .where(models.DreamCompany.user_id == user.id)
        .order_by(models.DreamCompany.created_at.desc())
    ).all()
    return [DreamCompanyItem.from_company(c) for c in companies]
