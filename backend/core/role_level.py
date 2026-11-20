"""Deterministic role levels from employer titles and existing structured metadata.

No description parsing. Python and Postgres share the ordered title rules, including
word boundaries, so ranking and the evidence displayed to readers stay consistent.
"""

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Literal, TypedDict

from sqlalchemy import case, func, literal
from sqlalchemy.dialects.postgresql import JSONB

from core import models
from core.eligibility import (
    ELIGIBLE_EXPERIENCED_ONLY_META_KEY,
    EXPERIENCED_PROFESSIONALS_ELIGIBILITY,
)

RoleLevel = Literal["internship", "apprenticeship", "graduate", "experienced", "unknown"]
RoleLevelSource = Literal["title", "category", "eligibility", "override"]
ROLE_LEVELS = frozenset({"internship", "apprenticeship", "graduate", "experienced", "unknown"})


class RoleLevelResult(TypedDict):
    level: RoleLevel
    evidence: str | bool | None
    source: RoleLevelSource


class RoleLevelOverride(TypedDict):
    slug: str
    level: RoleLevel
    reason: str


def _words(terms: str) -> str:
    # The sole capturing group preserves the employer's exact matched words.
    return r"(?:^|[^a-z])(" + terms + r")(?:[^a-z]|$)"


CLEARLY_SENIOR_TITLE_PATTERN = _words(
    r"senior|sr|staff|principal|director|vp|vice president|president|"
    r"chief|cto|ceo|coo|cfo|cxo|head of|distinguished"
)
NOT_SENIOR_TITLE_PATTERN = _words(
    r"intern|interns|internship|internships|trainee|trainees|apprentice|"
    r"apprentices|apprenticeship|new grad|new grads|new graduate|new graduates|graduate|"
    r"graduates|campus|fresher|freshers|entry level|entry-level|co-op|coop|working student|"
    r"werkstudent|technical staff|staff accountant|staff auditor|staff writer|staff nurse"
)
AMBIGUOUS_TITLE_PATTERN = _words(
    r"manager|management|lead|executive|architect|fellow|counsel|specialist"
)

# Explicit early text wins even over an experienced-only eligibility flag.
# Trainee is graduate, regardless of the crawler's historical internship category.
EXPLICIT_TITLE_RULES: tuple[tuple[str, RoleLevel], ...] = (
    (_words(r"intern(?:s|ship|ships)?|co-?op|working[ -]+student|werkstudent"), "internship"),
    (_words(r"apprentice(?:s|ship|ships)?"), "apprenticeship"),
    (
        _words(
            r"new[ -]+(?:grads?|graduates?|college[ -]+grad(?:uate)?s?)|"
            r"(?:recent|university)[ -]+grad(?:uate)?s?|"
            r"graduate(?:s|[ -]+program(?:me)?s?|[ -]+schemes?)?|"
            r"trainees?|freshers?|entry[ -]+level|campus"
        ),
        "graduate",
    ),
)
# These are entry-level titles, but cannot override "Senior Associate", etc.
GRADUATE_TITLE_PATTERN = _words(
    r"junior|jr|associate|(?:analyst|engineer|developer|designer|accountant|consultant|"
    r"scientist|specialist|technician)[ -]+(?:i|1)(?![a-z0-9])"
)


def load_role_level_overrides(path: Path | None = None) -> dict[str, RoleLevelOverride]:
    """Fail fast on invalid, duplicate or unexplained manual decisions."""
    path = path or Path(__file__).resolve().parents[1] / "data" / "role_level_overrides.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError("Role-level overrides must be a list")
    result: dict[str, RoleLevelOverride] = {}
    for row in rows:
        if (
            not isinstance(row, dict)
            or set(row) != {"slug", "level", "reason"}
            or not isinstance(row["slug"], str)
            or not row["slug"]
            or re.search(r"\s", row["slug"])
            or row["slug"] in result
            or not isinstance(row["level"], str)
            or row["level"] not in ROLE_LEVELS
            or not isinstance(row["reason"], str)
            or not row["reason"].strip()
        ):
            raise ValueError("Invalid or duplicate role-level override")
        result[row["slug"]] = row
    return result


ROLE_LEVEL_OVERRIDES = load_role_level_overrides()


def classify_role_level(
    title: str | None,
    category: str | None = None,
    meta: dict | None = None,
    slug: str | None = None,
    *,
    overrides: Mapping[str, RoleLevelOverride] | None = None,
) -> RoleLevelResult:
    overrides = ROLE_LEVEL_OVERRIDES if overrides is None else overrides
    override = overrides.get(slug) if slug is not None else None
    if override is not None:
        return {"level": override["level"], "evidence": override["reason"], "source": "override"}
    title = title or ""
    for pattern, level in EXPLICIT_TITLE_RULES:
        match = re.search(pattern, title, re.IGNORECASE)
        if match:
            return {"level": level, "evidence": match[1], "source": "title"}
    if category == "internship":
        return {"level": "internship", "evidence": category, "source": "category"}
    meta = meta if isinstance(meta, dict) else {}
    if meta.get(ELIGIBLE_EXPERIENCED_ONLY_META_KEY) is True:
        tags = meta.get("eligibility")
        evidence = (
            EXPERIENCED_PROFESSIONALS_ELIGIBILITY
            if isinstance(tags, list) and EXPERIENCED_PROFESSIONALS_ELIGIBILITY in tags
            else True
        )
        return {"level": "experienced", "evidence": evidence, "source": "eligibility"}
    # Exemptions such as Staff Accountant and Member of Technical Staff do not
    # themselves assert graduate eligibility; leave them unknown.
    senior_title = re.sub(NOT_SENIOR_TITLE_PATTERN, " ", title, flags=re.IGNORECASE)
    match = re.search(CLEARLY_SENIOR_TITLE_PATTERN, senior_title, re.IGNORECASE)
    if match:
        return {"level": "experienced", "evidence": match[1], "source": "title"}
    match = re.search(GRADUATE_TITLE_PATTERN, title, re.IGNORECASE)
    if match:
        return {"level": "graduate", "evidence": match[1], "source": "title"}
    match = re.search(AMBIGUOUS_TITLE_PATTERN, title, re.IGNORECASE)
    # No crawler currently stores a structured years-of-experience requirement.
    return {"level": "unknown", "evidence": match[1] if match else None, "source": "title"}


def role_level_expression(
    opportunity=models.Opportunity,
    *,
    overrides: Mapping[str, RoleLevelOverride] | None = None,
):
    """SQL CASE mirror of classify_role_level, using original employer titles.

    ``opportunity`` can also be a VALUES alias for parity tests. JSONB equality
    accepts only a real boolean true, exactly like Python's ``is True``.
    """
    overrides = ROLE_LEVEL_OVERRIDES if overrides is None else overrides
    title = func.coalesce(opportunity.title, "")
    senior_title = func.regexp_replace(title, NOT_SENIOR_TITLE_PATTERN, " ", "gi")
    clauses = [
        (
            opportunity.slug.in_(
                [slug for slug, row in overrides.items() if row["level"] == level]
            ),
            level,
        )
        for level in sorted(ROLE_LEVELS)
        if any(row["level"] == level for row in overrides.values())
    ]
    clauses.extend((title.op("~*")(pattern), level) for pattern, level in EXPLICIT_TITLE_RULES)
    clauses.extend(
        [
            (opportunity.category == "internship", "internship"),
            (
                opportunity.meta[ELIGIBLE_EXPERIENCED_ONLY_META_KEY] == literal(True, type_=JSONB),
                "experienced",
            ),
            (
                senior_title.op("~*")(CLEARLY_SENIOR_TITLE_PATTERN),
                "experienced",
            ),
            (title.op("~*")(GRADUATE_TITLE_PATTERN), "graduate"),
        ]
    )
    return case(*clauses, else_="unknown")
