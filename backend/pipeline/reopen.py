"""Statistical recurring-program reopen estimates with a curated fallback."""

import calendar
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from core import models

# Small seed only; longitudinal posting history takes precedence and grows over time.
CURATED_CYCLES: dict[str, str] = {
    "google step": "October-November",
    "google summer of code": "January-February",
    "major league hacking fellowship": "January, May, and September cohorts",
    "microsoft explore": "September-October",
    "outreachy": "February-March and August-September",
}


@dataclass(frozen=True)
class ReopenEstimate:
    window: str
    basis: Literal["historical", "curated"]
    note: str


def _historical_estimate(posted_dates: list[datetime]) -> ReopenEstimate:
    month_counts = Counter(posted_at.month for posted_at in posted_dates)
    typical_month = min(month_counts, key=lambda month: (-month_counts[month], month))
    year_count = len({posted_at.year for posted_at in posted_dates})
    return ReopenEstimate(
        window=f"around {calendar.month_name[typical_month]}",
        basis="historical",
        note=(
            f"Estimate based on {len(posted_dates)} distinct prior postings "
            f"across {year_count} calendar years."
        ),
    )


def _curated_estimate(opportunity: models.Opportunity) -> ReopenEstimate | None:
    title = (opportunity.title_normalized or opportunity.title).casefold()
    company = opportunity.company
    company_name = ""
    if company is not None:
        company_name = (company.name_normalized or company.name).casefold()

    for program, window in CURATED_CYCLES.items():
        if program in title or program in company_name:
            return ReopenEstimate(
                window=window,
                basis="curated",
                note=f"Estimate based on the curated seed cycle for {program}.",
            )
    return None


def reopen_estimate(session: Session, opportunity: models.Opportunity) -> ReopenEstimate | None:
    """Estimate a recurring opening window without model or embedding calls."""
    if (
        opportunity.company_id is not None
        and opportunity.title_normalized
        and opportunity.posted_at is not None
    ):
        posted_dates = list(
            session.scalars(
                select(models.Opportunity.posted_at)
                .where(
                    models.Opportunity.company_id == opportunity.company_id,
                    models.Opportunity.title_normalized == opportunity.title_normalized,
                    models.Opportunity.id != opportunity.id,
                    models.Opportunity.posted_at.is_not(None),
                    models.Opportunity.posted_at < opportunity.posted_at,
                )
                .distinct()
            ).all()
        )
        if len(posted_dates) >= 2 and len({posted_at.year for posted_at in posted_dates}) >= 2:
            return _historical_estimate(posted_dates)

    return _curated_estimate(opportunity)
