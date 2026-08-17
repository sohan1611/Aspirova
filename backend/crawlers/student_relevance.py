"""Student relevance helpers for broad aggregator feeds.

These adapters fetch sources that are mostly senior roles. The exclusion
boundary must stay aligned with the API/feed ranking boundary, so this module
imports the canonical pattern instead of redefining what "senior" means.
"""

import re
from typing import Any

from api.filters import SENIOR_TITLE_PATTERN
from pipeline.normalize import classify_category

_SENIOR_SIGNAL_RE = re.compile(SENIOR_TITLE_PATTERN, re.IGNORECASE)
_STUDENT_CATEGORY_RE = re.compile(
    r"\b(intern(s|ship|ships)?|co-?op|trainee|apprentice(ship)?|campus|"
    r"graduate|new grad(uate)?)\b",
    re.IGNORECASE,
)


def is_student_relevant_role(title: Any, *level_fields: Any) -> bool:
    """Return False only when title or source level clearly says senior."""

    signals = [_signal_text(title), *[_signal_text(field) for field in level_fields]]
    return not any(signal and _SENIOR_SIGNAL_RE.search(signal) for signal in signals)


def classify_student_role(title: Any, *level_fields: Any) -> str:
    """Map jobs to internship only when title/level clearly says student role."""

    title_text = _signal_text(title)
    combined = " ".join(
        signal
        for signal in [title_text, *[_signal_text(field) for field in level_fields]]
        if signal
    )
    if _STUDENT_CATEGORY_RE.search(combined):
        return "internship"
    return classify_category(title_text)


def _signal_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return " ".join(_signal_text(item) for item in value if _signal_text(item)).strip()
    if isinstance(value, dict):
        preferred = [
            _signal_text(value.get(key))
            for key in ("name", "label", "title", "value")
            if value.get(key) is not None
        ]
        return " ".join(part for part in preferred if part).strip()
    try:
        return str(value).strip()
    except (TypeError, ValueError):
        return ""
