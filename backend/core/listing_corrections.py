"""Public correction copy is derived from known fields, never report text."""

from datetime import datetime

# Rendered after "Corrected <date>: ", so each summary starts lower-case.
SUMMARIES = {
    "deadline": "deadline changed after a reader report.",
    "closed_at": "marked closed after a reader report.",
    "company_id": "company corrected after a reader report.",
    "safety": "listing withdrawn after a reader report.",
    "duplicate_of": "duplicate identified after a reader report.",
}


def public_corrections(meta: dict | None) -> list[dict]:
    if not isinstance(meta, dict):
        return []
    values = meta.get("corrections")
    if not isinstance(values, list):
        return []
    result = []
    for value in values:
        if (
            not isinstance(value, dict)
            or not isinstance(value.get("field"), str)
            or value["field"] not in SUMMARIES
        ):
            continue
        try:
            at = datetime.fromisoformat(value["at"])
            if at.tzinfo is None:
                continue
        except (KeyError, TypeError, ValueError):
            continue
        result.append({"at": at, "field": value["field"], "summary": SUMMARIES[value["field"]]})
    return result


def public_listing_meta(meta: dict | None) -> dict | None:
    if not isinstance(meta, dict):
        return None
    return {
        key: value
        for key, value in meta.items()
        if key not in {"corrections", "deadline_override", "company_override"}
    } or None
