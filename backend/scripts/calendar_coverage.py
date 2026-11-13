"""Offline authored-registry coverage gate. Run with python -m scripts.calendar_coverage."""

from datetime import date
import json

from core.hiring_calendar import CALENDAR_META, DATA_DIR, source_window


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
            if not meta.get("rolling_reason", "").strip():
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
    raise SystemExit(bool(missing))


if __name__ == "__main__":
    main()
