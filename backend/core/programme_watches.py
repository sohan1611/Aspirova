"""Deterministic, versioned calendar-watch state. No I/O or notification delivery.

Keep every stored edition in the baseline: a newly projected tentative edition
must not hide the previous edition closing. Recurring programmes retain a state
per occurrence, using the calendar's own provenance and status rules.
"""

from datetime import datetime
import json

from core.hiring_calendar import (
    IST,
    SLUG_BY_ROW_ID,
    calendar_metadata,
    has_rolling_deadline,
    official_status,
    recurrence_is_official,
    recurrence_windows,
    source_window,
)
from core.models import Programme, ProgrammeEdition


def _boundary(value: datetime | None, precision: str | None) -> str | None:
    if value is None:
        return None
    local = value.astimezone(IST)
    # Month boundaries are storage conventions, not official days to announce.
    return local.strftime("%Y-%m" if precision == "month" else "%Y-%m-%d")


def programme_state(programme: Programme, *, now: datetime) -> dict:
    """Snapshot all calendar occurrences without verification timestamps/wording."""
    meta = calendar_metadata(programme.slug, programme.name, programme.organiser)
    source = source_window(SLUG_BY_ROW_ID[meta["row_id"]]) if meta else {}
    rule = meta.get("recurrence")
    official_rule = bool(rule and recurrence_is_official(meta))
    editions = {edition.year: edition for edition in programme.editions}
    if rule and any(edition.status != "discontinued" for edition in editions.values()):
        # The public calendar projects standing rules into unstored years too.
        # Baseline next year's occurrences now, so adding their stored edition
        # is quiet while the December -> January opening still reaches watchers.
        local_year = now.astimezone(IST).year
        for year in range(max(1, local_year - 1), min(9999, local_year + 1) + 1):
            editions.setdefault(year, ProgrammeEdition(year=year, status="expected"))
    windows = []
    for edition in sorted(editions.values(), key=lambda item: item.year):
        if edition.status == "discontinued":
            continue
        notes = edition.notes or ""
        rolling_deadline = has_rolling_deadline(meta, notes) or (
            "calendar_deadline_rolling" in notes and "calendar_exact_closes_at" not in notes
        )
        occurrences = (
            recurrence_windows(edition.year, rule)
            if rule
            else [(edition.opens_at, edition.closes_at)]
        )
        for occurrence, (opening, closing) in enumerate(occurrences):
            if rolling_deadline:
                closing = None
            status = edition.status
            if rule:
                status = "announced" if official_rule else "expected"
            status = official_status(status, opening, closing, now)
            precision = {}
            for field, boundary in (("opens_at", opening), ("closes_at", closing)):
                default = (
                    rule["precision"]
                    if rule
                    else source.get(field.replace("_at", "_precision")) or "day"
                )
                exact = f"calendar_exact_{field}" in notes
                precision[field] = (
                    (
                        "month"
                        if status == "expected"
                        else "day" if exact or official_rule else default
                    )
                    if boundary
                    else None
                )
            windows.append(
                {
                    "key": f"{edition.year}:{occurrence}",
                    "year": edition.year,
                    "stored_status": edition.status,
                    "status": status,
                    "basis": "tentative" if status == "expected" else "official",
                    "opens_at": _boundary(opening, precision["opens_at"]),
                    "closes_at": _boundary(closing, precision["closes_at"]),
                    "opens_precision": precision["opens_at"],
                    "closes_precision": precision["closes_at"],
                }
            )
    return {"version": 1, "windows": windows}


def programme_signature(programme: Programme, *, now: datetime) -> str:
    """Canonical JSON, deliberately inspectable rather than an opaque hash."""
    return json.dumps(programme_state(programme, now=now), sort_keys=True, separators=(",", ":"))


def _decode(signature: str | dict | None) -> dict:
    if isinstance(signature, dict):
        return signature
    if signature is None:
        return {}
    try:
        state = json.loads(signature)
    except (ValueError, TypeError):
        return {}
    return state if isinstance(state, dict) and state.get("version") == 1 else {}


def _changes(previous: str | dict | None, current: str | dict) -> list[tuple[str, dict]]:
    before, after = _decode(previous), _decode(current)
    if not before or not after or before == after:
        return []
    old_windows = {window["key"]: window for window in before.get("windows", [])}
    changes = []
    for window in after.get("windows", []):
        if window["basis"] != "official":
            continue
        old = old_windows.get(window["key"])
        status = window["status"]
        if old is None:
            # A projected standing rule can be officially known, without a new
            # announcement. The next-year baseline above retains real openings.
            if window.get("stored_status") == "expected":
                continue
            # Newly added historical closed editions are not newly closed calls.
            if status in {"announced", "open"}:
                changes.append((status, window))
            continue
        if status != old["status"]:
            if status in {"open", "closed"}:
                changes.append((status, window))
                continue
            if status == "announced" and old["status"] == "expected":
                changes.append(("announced", window))
                continue
        if old["basis"] != "official":
            continue
        deadline = window["closes_at"]
        old_deadline = old["closes_at"]
        if deadline and not old_deadline:
            changes.append(("deadline_set", window))
        elif old_deadline and (
            deadline != old_deadline or window["closes_precision"] != old["closes_precision"]
        ):
            changes.append(("deadline_changed", window))
    # One entry per programme per digest. Prefer an actionable open call when
    # an adjacent recurring occurrence closes at the same time.
    priority = {"open": 0, "deadline_changed": 1, "deadline_set": 2, "announced": 3, "closed": 4}
    return sorted(changes, key=lambda change: (priority[change[0]], change[1]["key"]))


def classify_change(previous: str | dict | None, current: str | dict) -> str | None:
    """Return one meaningful official change; tentative shifts/projections are quiet."""
    changes = _changes(previous, current)
    return changes[0][0] if changes else None


def programme_change(previous: str | None, programme: Programme, *, now: datetime) -> dict | None:
    """Notification-ready change details and the complete new baseline."""
    signature = programme_signature(programme, now=now)
    changes = _changes(previous, signature)
    if not changes:
        return None
    event, window = changes[0]
    return {
        **window,
        "event": event,
        "signature": signature,
        "programme_slug": programme.slug,
        "programme_name": programme.name,
        "programme_url": programme.url,
        "organiser": programme.organiser,
    }
