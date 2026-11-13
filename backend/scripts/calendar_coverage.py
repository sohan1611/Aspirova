"""Offline authored-registry coverage gate. Run with python -m scripts.calendar_coverage."""

import calendar
from datetime import date, timedelta
import json

from core.hiring_calendar import (
    CALENDAR_META,
    DATA_DIR,
    ROWS,
    ROLLING_KINDS,
    at_day,
    projected_boundaries,
    projection_needed,
    source_window,
)

FROZEN_DATES = (date(2026, 11, 13), date(2027, 3, 1), date(2027, 7, 1), date(2027, 10, 15))


def next_year(today: date) -> date:
    return today.replace(
        year=today.year + 1,
        day=min(today.day, calendar.monthrange(today.year + 1, today.month)[1]),
    )


def authored_programmes(*, today: date) -> list:
    """Offline equivalent of importing the source and catching up its editions."""
    from core.models import Programme, ProgrammeEdition
    from scripts.import_calendar import category_for

    result = []
    for slug, meta in CALENDAR_META.items():
        window = source_window(slug)
        year, status = meta["cycle_year"], window["status"]
        opening, closing = window["opens_at"], window["closes_at"]
        editions = []
        while True:
            editions.append(
                ProgrammeEdition(
                    year=year,
                    status=status,
                    opens_at=opening,
                    closes_at=closing,
                    notes=window["notes"],
                )
            )
            if year >= 9999 or not projection_needed(year, status, opening, closing, at_day(today)):
                break
            year, status = year + 1, "expected"
            opening, closing = projected_boundaries(opening, closing)
        row = ROWS[meta["row_id"]]
        result.append(
            Programme(
                slug=slug,
                name=meta["name"],
                organiser=meta["organiser"],
                category=category_for(row),
                url=row["official_portal"],
                tags=[],
                is_active=True,
                editions=editions,
            )
        )
    return result


def uncovered_next_12_months(programmes: list | None = None, *, today: date) -> list[str]:
    """Check actual API visibility over the half-open next-12-month interval."""
    from api.calendar import build_calendar

    if programmes is None:
        programmes = authored_programmes(today=today)
        registry = json.loads((DATA_DIR / "programmes.json").read_text(encoding="utf-8"))
        absent = {
            item["slug"]
            for item in registry["programmes"]
            if item.get("is_active", True) and item["slug"] not in CALENDAR_META
        }
    else:
        absent = set()
    active = [item for item in programmes if item.is_active]
    response = build_calendar(
        active,
        today,
        next_year(today) - timedelta(days=1),
        categories=[],
        statuses=[],
        q="",
        now=at_day(today),
    )
    covered = {item.programme.slug for item in response.items}
    covered.update(
        item.programme.slug
        for item in response.rolling
        if item.metadata.rolling_kind in ROLLING_KINDS - {"annual_cycle"}
        and item.metadata.rolling_reason
    )
    return sorted(absent | {item.slug for item in active if item.slug not in covered})


def uncovered_programmes(*, today: date | None = None) -> list[str]:
    today = today or date.today()
    registry = json.loads((DATA_DIR / "programmes.json").read_text(encoding="utf-8"))
    active = {row["slug"] for row in registry["programmes"] if row.get("is_active", True)} | set(
        CALENDAR_META
    )
    missing = []
    for slug in sorted(active):
        meta = CALENDAR_META.get(slug)
        if not meta:
            missing.append(slug)
            continue
        window = source_window(slug)
        if window["rolling"]:
            if not meta.get("rolling_reason", "").strip() or meta.get(
                "rolling_kind"
            ) not in ROLLING_KINDS - {"annual_cycle"}:
                missing.append(slug)
            continue
        years = {today.year, today.year + 1}
        application_years = {
            value.year for value in (window["opens_at"], window["closes_at"]) if value
        }
        # A next-year intake can register in the preceding year. Company
        # recruiting can also target the following intake from next year's call.
        if meta["cycle_year"] not in years and not application_years & years:
            missing.append(slug)
    return missing


def main() -> None:
    missing = uncovered_programmes()
    for slug in missing:
        print(slug)
    print(f"Uncovered active programmes: {len(missing)}")
    for today in FROZEN_DATES:
        gaps = uncovered_next_12_months(today=today)
        print(f"Next 12 months from {today}: {len(gaps)} uncovered")
        for slug in gaps:
            print(f"  {slug}")
        missing.extend(gaps)
    raise SystemExit(bool(missing))


if __name__ == "__main__":
    main()
