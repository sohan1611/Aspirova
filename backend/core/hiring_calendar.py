"""Deterministic calendar source parsing and recurrence rules, without DB changes."""

import calendar
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import json
from pathlib import Path
import re

IST = timezone(timedelta(hours=5, minutes=30))
DATA_DIR = Path(__file__).resolve().parents[1] / "data"
SOURCE = json.loads((DATA_DIR / "hiring_calendar_2027.json").read_text(encoding="utf-8"))
METADATA = json.loads((DATA_DIR / "hiring_calendar_metadata.json").read_text(encoding="utf-8"))
CALENDAR_META = METADATA["programmes"]
SLUG_BY_ROW_ID = {meta["row_id"]: slug for slug, meta in CALENDAR_META.items()}
ROWS = {row["id"]: row for row in SOURCE["opportunities"]}
META_BY_NAME = {
    (ROWS[meta["row_id"]]["opportunity"].casefold(), meta["organiser"].casefold()): meta
    for meta in CALENDAR_META.values()
}
META_BY_NAME.update(
    {
        (meta["name"].casefold(), meta["organiser"].casefold()): meta
        for meta in CALENDAR_META.values()
    }
)
MONTHS = {name.lower(): number for number, name in enumerate(calendar.month_abbr) if name}
MONTHS.update({name.lower(): number for number, name in enumerate(calendar.month_name) if name})
MONTH_PATTERN = "|".join(sorted(MONTHS, key=len, reverse=True))
OFFICIAL_RECURRENCE_BASES = {
    "official",
    "official annual rule",
    "official monthly rule",
    "official standing rule",
    "official standing annual recruitment pattern",
}
ROLLING_KINDS = {
    "vacancy_based",
    "lab_dependent",
    "nomination_based",
    "paused",
    "always_open",
    "annual_cycle",
}


def calendar_metadata(slug: str, name: str, organiser: str) -> dict:
    return CALENDAR_META.get(slug, META_BY_NAME.get((name.casefold(), organiser.casefold()), {}))


def recurrence_is_official(meta: dict) -> bool:
    """An explicit rule basis takes precedence over the source row's date basis."""
    basis = meta.get("recurrence", {}).get(
        "basis", meta.get("date_basis", ROWS.get(meta.get("row_id"), {}).get("date_basis", ""))
    )
    return " ".join(basis.casefold().split()) in OFFICIAL_RECURRENCE_BASES


@dataclass(frozen=True)
class ParsedDate:
    start: datetime | None = None
    end: datetime | None = None
    precision: str | None = None
    note: str | None = None


def at_day(value: date, *, end: bool = False) -> datetime:
    return datetime.combine(value, time.max if end else time.min, IST)


def month_date(year: int, month: int, *, end: bool = False) -> datetime:
    day = calendar.monthrange(year, month)[1] if end else 1
    return at_day(date(year, month, day), end=end)


def parse_calendar_date(text: str, *, year: int = 2027) -> ParsedDate:
    """Parse explicit days/months only. Unfixed wording stays undated with a note."""
    clean = re.sub(r"\([^)]*\)", "", text).strip().replace("–", "-").replace("—", "-")
    clean = re.sub(r"^(listed by|open by|live by|early|late|mid)\s+", "", clean, flags=re.I)
    day_match = re.fullmatch(rf"(\d{{1,2}})\s+({MONTH_PATTERN})\s+(\d{{4}})", clean, re.I)
    try:
        if day_match:
            value = date(int(day_match[3]), MONTHS[day_match[2].lower()], int(day_match[1]))
            return ParsedDate(at_day(value), at_day(value, end=True), "day")
        months_match = re.fullmatch(
            rf"({MONTH_PATTERN})(?:\s*-\s*({MONTH_PATTERN}))?(?:\s+(\d{{4}}))?",
            clean,
            re.I,
        )
        if months_match:
            first = MONTHS[months_match[1].lower()]
            last = MONTHS[(months_match[2] or months_match[1]).lower()]
            start_year = int(months_match[3] or year)
            end_year = start_year + (last < first)
            return ParsedDate(
                month_date(start_year, first), month_date(end_year, last, end=True), "month"
            )
    except ValueError:
        pass
    return ParsedDate(note=f"No fixed date parsed in {text}")


def source_status(row: dict, override: dict) -> str:
    if "status" in override:
        return override["status"]
    status = row["status_as_of_2026_11_13"]
    if status == "Confirmed Open":
        return "open"
    if status == "Closed — Next Cycle Watch":
        return "closed"
    if status in {"Announced — Upcoming", "Confirmed Annual Window"}:
        return "announced"
    if row["date_basis"] == "Official 2027 Published":
        return "announced"
    return "expected"


def source_window(slug: str) -> dict:
    meta = CALENDAR_META[slug]
    row = ROWS[meta["row_id"]]
    override = METADATA["overrides"].get(row["id"], {})
    status = source_status(row, override)
    opening = parse_calendar_date(row["application_open"])
    closing = parse_calendar_date(row["registration_deadline"])
    opens_precision, closes_precision = opening.precision, closing.precision
    opens_at, closes_at = opening.start, closing.end
    notes = [value.note for value in (opening, closing) if value.note]
    if status == "expected":
        opens_at = month_date(opens_at.year, opens_at.month) if opens_at else None
        closes_at = month_date(closes_at.year, closes_at.month, end=True) if closes_at else None
    if "opens_at" in override:
        opens_at = override["opens_at"]
    deadline_rolling = bool(opens_at and (meta.get("deadline_rolling") or closes_at is None))
    if deadline_rolling:
        closes_at = month_date(opening.end.year, opening.end.month, end=True)
        notes.append("calendar_deadline_rolling")
    recurrence = meta.get("recurrence")
    if recurrence:
        occurrences = recurrence_windows(meta["cycle_year"], recurrence)
        opens_at = min(item[0] for item in occurrences)
        closes_at = max(item[1] for item in occurrences)
        status = "announced" if recurrence_is_official(meta) else "expected"
        opens_precision = closes_precision = "day" if status == "announced" else "month"
    rolling = opens_at is None and closes_at is None
    if override.get("reason"):
        notes.append(override["reason"])
    return {
        "status": status,
        "opens_at": opens_at,
        "closes_at": closes_at,
        "opens_precision": "month" if status == "expected" and opens_at else opens_precision,
        "closes_precision": (
            "month"
            if closes_at and (status == "expected" or deadline_rolling)
            else closes_precision
        ),
        "rolling": rolling,
        "deadline_rolling": deadline_rolling,
        "notes": "\n".join([row["verification_note"], *notes]).strip(),
    }


def has_rolling_deadline(meta: dict, notes: str | None) -> bool:
    return bool(meta.get("deadline_rolling") and "calendar_exact_closes_at" not in (notes or ""))


def recurrence_windows(year: int, rule: dict) -> list[tuple[datetime, datetime]]:
    result = []
    for window in rule["windows"]:
        open_year = year + window.get("open_year_offset", 0)
        close_year = year + window.get("close_year_offset", 0)
        if not 1 <= open_year <= 9999 or not 1 <= close_year <= 9999:
            continue
        opening = at_day(date(open_year, window["open_month"], window.get("open_day", 1)))
        closing = at_day(
            date(
                close_year,
                window["close_month"],
                window.get("close_day", calendar.monthrange(close_year, window["close_month"])[1]),
            ),
            end=True,
        )
        result.append((opening, closing))
    return result


def official_status(
    status: str, opens_at: datetime | None, closes_at: datetime | None, now: datetime
) -> str:
    if status not in {"announced", "open"}:
        return status
    if closes_at is not None and now > closes_at:
        return "closed"
    if opens_at is not None and now < opens_at:
        return "announced"
    if opens_at is not None and opens_at <= now:
        return "open"
    return status


def projection_needed(
    year: int, status: str, opening: datetime | None, closing: datetime | None, now: datetime
) -> bool:
    """Include expired tentative windows and preceding-year intake applications."""
    boundary = closing or opening
    return status == "closed" or year < now.year or bool(boundary and boundary < now)


def projected_boundaries(
    opening: datetime | None, closing: datetime | None
) -> tuple[datetime | None, datetime | None]:
    opening = shift_year(opening.astimezone(IST)) if opening else None
    closing = shift_year(closing.astimezone(IST)) if closing else None
    return (
        month_date(opening.year, opening.month) if opening else None,
        month_date(closing.year, closing.month, end=True) if closing else None,
    )


def shift_year(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(
        year=value.year + 1, day=min(value.day, calendar.monthrange(value.year + 1, value.month)[1])
    )
