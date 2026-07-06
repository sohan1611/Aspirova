"""GET /plans - public read of the seeded plan rows, for the pricing page
(Doc handoffs/PHASE-2.5-HANDOFF.md sec 3.7). Read-only; `can()` remains
the single gating seam server-side, this endpoint doesn't touch it."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps import get_db
from api.schemas import PlanPublic
from core import models

router = APIRouter()


@router.get("/plans", response_model=list[PlanPublic])
def list_plans(db: Session = Depends(get_db)) -> list[PlanPublic]:
    plans = db.scalars(select(models.Plan).order_by(models.Plan.id)).all()
    return [PlanPublic.model_validate(p) for p in plans]
