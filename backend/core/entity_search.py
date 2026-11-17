"""Deterministic canonical-entity matching shared by public search surfaces."""

import re
import unicodedata
from typing import Literal

ProgrammeMatch = Literal["slug", "acronym", "name", "organiser", "company"]
CompanyMatch = Literal["exact", "acronym", "prefix", "substring"]
PROGRAMME_MATCH_ORDER = ("slug", "acronym", "name", "organiser", "company")
COMPANY_MATCH_ORDER = ("exact", "acronym", "prefix", "substring")
STOP_WORDS = frozenset({"of", "and", "the", "for", "in", "at", "on", "to"})


def normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    unaccented = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join("".join(char if char.isalnum() else " " for char in unaccented).split())


def acronyms(name: str) -> set[str]:
    words = normalize(name).split()
    values = {
        "".join(word[0] for word in words),
        "".join(word[0] for word in words if word not in STOP_WORDS),
    }
    values.update(normalize(token) for token in re.findall(r"\b[^\W_]+\b", name) if token.isupper())
    values.update(normalize(token) for token in re.findall(r"\(([^()]+)\)", name))
    return {value for value in values if len(value) >= 2}


def _word_prefixes(query: str, text: str) -> bool:
    words = normalize(text).split()
    return all(any(word.startswith(token) for word in words) for token in query.split())


def match_programme(
    query: str, *, slug: str, name: str, organiser: str = "", company: str = ""
) -> ProgrammeMatch | None:
    query = normalize(query)
    if not query:
        return None
    if query == normalize(slug):
        return "slug"
    if query in acronyms(name):
        return "acronym"
    for kind, text in (("name", name), ("organiser", organiser), ("company", company)):
        if _word_prefixes(query, text):
            return kind
    return None


def match_company(query: str, name: str) -> CompanyMatch | None:
    query, normalized_name = normalize(query), normalize(name)
    if not query:
        return None
    if query == normalized_name:
        return "exact"
    if query in acronyms(name):
        return "acronym"
    if normalized_name.startswith(query):
        return "prefix"
    if len(query) >= 4 and query in normalized_name:
        return "substring"
    return None
