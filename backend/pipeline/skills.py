"""Deterministic skill extraction for canonical opportunities."""

from __future__ import annotations

import json
import re
from pathlib import Path
from re import Pattern
from typing import Any

MAX_OPPORTUNITY_SKILLS = 12
OPPORTUNITY_ALIAS_STOPLIST = frozenset(
    {
        "compliance",
        "design",
        "research",
        "spring",
        "notion",
        "audit",
        "tax",
        "user experience",
        "user interface",
    }
)
REGEXP_SPECIAL_CHARACTERS = frozenset(
    {".", "*", "+", "?", "^", "$", "{", "}", "(", ")", "|", "[", "]", "\\"}
)
EXCEL_WORD_PATTERN = re.compile(r"\bexcel\b", re.ASCII)
EXCEL_VERB_CONTINUATION_PATTERN = re.compile(
    r"^\s+(?:at|in|as|when|beyond|past|here|there|within|under)\b",
    re.ASCII,
)
EXCEL_VERB_PRECEDERS = frozenset(
    {
        "and",
        "can",
        "could",
        "consistently",
        "help",
        "helping",
        "helps",
        "i",
        "must",
        "really",
        "should",
        "they",
        "to",
        "truly",
        "we",
        "who",
        "will",
        "would",
        "you",
    }
)


def _load_json(filename: str) -> dict[str, Any]:
    path = Path(__file__).with_name(filename)
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def _escape_regexp(value: str) -> str:
    return "".join(
        f"\\{character}" if character in REGEXP_SPECIAL_CHARACTERS else character
        for character in value
    )


def _compile_alias_pattern(alias: str) -> Pattern[str] | None:
    normalized_alias = alias.strip().lower()
    if not normalized_alias:
        return None

    escaped_alias = _escape_regexp(normalized_alias)
    has_punctuation = re.search(r"[^a-z0-9\s]", normalized_alias) is not None
    if has_punctuation:
        return re.compile(
            r"(?:^|[^a-z0-9])" + escaped_alias + r"(?=$|[^a-z0-9])",
            re.ASCII,
        )
    return re.compile(r"\b" + escaped_alias + r"\b", re.ASCII)


def _compile_alias_patterns(aliases: list[str]) -> tuple[Pattern[str], ...]:
    patterns: list[Pattern[str]] = []
    for alias in aliases:
        if alias.strip().lower() in OPPORTUNITY_ALIAS_STOPLIST:
            continue
        pattern = _compile_alias_pattern(alias)
        if pattern is not None:
            patterns.append(pattern)
    return tuple(patterns)


def _compile_role_phrase_pattern(phrase: str) -> Pattern[str]:
    return re.compile(
        r"(?:^|[^a-z0-9])" + _escape_regexp(phrase) + r"(?=$|[^a-z0-9])",
        re.ASCII,
    )


def _remove_company_name(haystack: str, company_name: str) -> str:
    normalized_company_name = company_name.strip().lower()
    if len(normalized_company_name) < 2:
        return haystack
    return haystack.replace(normalized_company_name, " ")


def _has_tool_excel(haystack: str) -> bool:
    for match in EXCEL_WORD_PATTERN.finditer(haystack):
        if EXCEL_VERB_CONTINUATION_PATTERN.search(haystack[match.end() :]):
            continue

        prefix = haystack[: match.start()].rstrip()
        previous_word_match = re.search(r"[a-z]+$", prefix, re.ASCII)
        if previous_word_match is not None and previous_word_match.group(0) in EXCEL_VERB_PRECEDERS:
            continue

        return True
    return False


_LEXICON = _load_json("skills_lexicon.json")
_ROLE_MAP = _load_json("role_skills.json")

_ALIAS_PATTERNS: tuple[tuple[str, str, tuple[Pattern[str], ...]], ...] = tuple(
    (
        skill["name"],
        skill.get("field", ""),
        _compile_alias_patterns(skill.get("aliases", [])),
    )
    for skill in _LEXICON["skills"]
)
_CANONICAL_NAMES = frozenset(name for name, _field, _patterns in _ALIAS_PATTERNS)
_ROLE_SKILLS: tuple[tuple[Pattern[str], tuple[str, ...]], ...] = tuple(
    (
        _compile_role_phrase_pattern(phrase.strip().lower()),
        tuple(skill_name for skill_name in skill_names if skill_name in _CANONICAL_NAMES),
    )
    for phrase, skill_names in _ROLE_MAP["roles"].items()
    if phrase.strip()
)


def _append_skill(skills: list[str], seen_names: set[str], name: str) -> bool:
    normalized_name = name.lower()
    if normalized_name in seen_names:
        return len(skills) >= MAX_OPPORTUNITY_SKILLS

    seen_names.add(normalized_name)
    skills.append(name)
    return len(skills) >= MAX_OPPORTUNITY_SKILLS


def extract_opportunity_skills(title: str, description: str, company_name: str = "") -> list[str]:
    """Extract canonical skill names from opportunity text without AI or side effects."""
    haystack = _remove_company_name(f"{title}\n{description}".lower(), company_name)
    title_l = title.lower()
    extracted: list[str] = []
    seen_names: set[str] = set()

    for name, field, patterns in _ALIAS_PATTERNS:
        if field == "other":
            continue
        if any(pattern.search(haystack) for pattern in patterns):
            if name == "Excel" and not _has_tool_excel(haystack):
                continue
            if _append_skill(extracted, seen_names, name):
                return extracted

    for phrase_pattern, skill_names in _ROLE_SKILLS:
        if phrase_pattern.search(title_l):
            for skill_name in skill_names:
                if _append_skill(extracted, seen_names, skill_name):
                    return extracted

    return extracted
