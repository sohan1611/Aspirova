"""Expand the backend copy of frontend/lib/taxonomy.json, byte-checked in CI."""

import json
from pathlib import Path

TAXONOMY_PATH = Path(__file__).resolve().parents[1] / "data" / "taxonomy.json"
STREAMS = json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))["streams"]


def selected_interests(profile: dict) -> list[dict]:
    """Same division order, interest de-duplication and key selection as TS."""
    stream = next((s for s in STREAMS if s["key"] == profile.get("stream")), None)
    if stream is None:
        return []
    divisions = set(profile.get("divisions") or [])
    interests = set(profile.get("interests") or [])
    seen: set[str] = set()
    selected = []
    for division in stream["divisions"]:
        if division["key"] not in divisions:
            continue
        for interest in division["interests"]:
            key = interest["key"]
            if key in seen:
                continue
            seen.add(key)
            if key in interests:
                selected.append(interest)
    return selected


def interest_terms(interest: dict) -> list[str]:
    return [term.strip().lower() for term in interest.get("keywords", [interest["label"]])]


def expand_to_search_terms(profile: dict) -> list[str]:
    return list(
        dict.fromkeys(t for i in selected_interests(profile) for t in interest_terms(i) if t)
    )


def build_feed_terms(profile: dict, skill_names: list[str], max_chars: int = 480) -> list[str]:
    """Byte-for-byte CSV cap semantics of buildFeedTerms, including stop-on-overflow."""
    terms = list(
        dict.fromkeys(
            t.strip().lower()
            for t in [*expand_to_search_terms(profile), *skill_names]
            if isinstance(t, str) and t.strip()
        )
    )
    capped: list[str] = []
    length = 0
    for term in terms:
        next_length = length + bool(capped) + len(term.encode("utf-16-le")) // 2
        if next_length > max_chars:
            break
        capped.append(term)
        length = next_length
    return capped
