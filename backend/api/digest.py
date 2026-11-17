"""A real, non-personal sample using the daily digest worker's global picks."""

from collections import Counter
from datetime import date, datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.deps import get_db
from core import models
from core.email_components import _utc
from core.hiring_calendar import IST
from pipeline import notifications as worker

router = APIRouter()


class DigestItem(BaseModel):
    kind: Literal["opportunity"] = "opportunity"
    slug: str
    title: str
    company_name: str | None
    category: str
    deadline: str | None = None
    deadline_precision: str | None = None
    deadline_confidence: str | None = None


class DigestSample(BaseModel):
    date: date
    items: list[DigestItem]
    counts_by_category: dict[str, int]
    empty: bool


def _listing_item(opportunity: models.Opportunity) -> DigestItem:
    return DigestItem(
        slug=opportunity.slug,
        title=opportunity.title,
        company_name=opportunity.company.name if opportunity.company else None,
        category=opportunity.category or "uncategorized",
        deadline=_utc(opportunity.deadline).isoformat() if opportunity.deadline else None,
        deadline_precision="day" if opportunity.deadline else None,
        deadline_confidence=opportunity.deadline_confidence,
    )


@router.get("/digest/sample", response_model=DigestSample)
def get_digest_sample(db: Session = Depends(get_db)) -> DigestSample:
    now = datetime.now(timezone.utc)
    savepoint = db.begin_nested()
    try:
        # A default reader has no followed companies or history. Use exactly the
        # worker's generic fallback and shared picks; never load/create a user or
        # render personalized HTML/unsubscribe tokens for a public response.
        opportunities = worker._generic_recent_opportunities(
            db, now - worker.DIGEST_WINDOW_DEFAULT, worker.DIGEST_GENERIC_SAMPLE_SIZE, now
        )
        ids = {o.id for o in opportunities}
        listings = [
            *opportunities,
            *(o for o in worker._HackathonPicks(db, now).default if o.id not in ids),
        ]
        return DigestSample(
            date=now.astimezone(IST).date(),
            items=[_listing_item(o) for o in listings[:6]],
            counts_by_category=dict(Counter(o.category or "uncategorized" for o in listings)),
            empty=not listings,
        )
    finally:
        savepoint.rollback()
