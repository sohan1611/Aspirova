"""Conservative source evidence for digest eligibility, with no inferred claims."""

import re
from dataclasses import asdict, dataclass

from core import models
from core.eligibility_facts import graduation_batches as graduation_batches

UNKNOWN_ELIGIBILITY = "Eligibility not stated — check before applying"


def chosen_country(profile: dict) -> str | None:
    country = profile.get("country")
    if isinstance(country, str) and re.fullmatch(r"[A-Za-z]{2}", country.strip()):
        return country.strip().upper()
    return None


def structured_restriction(opportunity: models.Opportunity) -> tuple[str | None, str | None]:
    """Use only source-provided meta.eligibility tags and structured country.

    Unstop currently preserves eligibility filter names. No crawler currently
    emits a dedicated authorization flag. Do not mine descriptions for one or
    treat country/is_remote as evidence of citizenship or work authorization.
    """
    country = chosen_country({"country": opportunity.country})
    meta = opportunity.meta if isinstance(opportunity.meta, dict) else {}
    tags = meta.get("eligibility")
    if not country or not isinstance(tags, list):
        return None, None
    signals = {
        "citizens only",
        "residents only",
        "work authorization required",
        "work authorisation required",
    }
    allowed = signals | {f"{country.lower()} {signal}" for signal in signals}
    for tag in tags:
        if isinstance(tag, str) and " ".join(tag.lower().split()) in allowed:
            return country, " ".join(tag.split())
    return None, None


@dataclass(frozen=True)
class Eligibility:
    state: str
    text: str
    years: list[int]
    restricted_country: str | None
    excluded: bool = False

    def meta(self) -> dict:
        return asdict(self)


def eligibility_for(opportunity: models.Opportunity, user: models.User) -> Eligibility:
    meta = opportunity.meta if isinstance(opportunity.meta, dict) else {}
    tags = meta.get("eligibility")
    source_text = "\n".join(
        [
            opportunity.title or "",
            opportunity.description_raw or "",
            *([t for t in tags if isinstance(t, str)] if isinstance(tags, list) else []),
        ]
    )
    years = graduation_batches(source_text)
    restricted, restriction = structured_restriction(opportunity)
    profile = user.field_profile if isinstance(user.field_profile, dict) else {}
    country = chosen_country(profile)
    year = user.graduation_year
    if years and year is not None and year not in years:
        return Eligibility(
            "mismatch",
            "Listing states other graduation batches — check before applying",
            years,
            restricted,
            True,
        )
    if restricted and country and restricted != country:
        return Eligibility(
            "mismatch",
            f"Listing restriction: {restricted} — {restriction} — check before applying",
            years,
            restricted,
            True,
        )
    # Matching a browsing country does not prove citizenship or authorization.
    # A batch match describes only the stated batch requirement, never full eligibility.
    parts = []
    if years and year in years:
        parts.append(f"Open to {year} graduates (batch requirement)")
    elif years:
        parts.append("Listed graduation batches: " + ", ".join(map(str, years)))
    if restricted:
        parts.append(f"Listing restriction: {restricted} — {restriction} — verify at source")
    if parts:
        return Eligibility(
            "stated",
            "; ".join(parts) + " — check all requirements before applying",
            years,
            restricted,
        )
    return Eligibility("unknown", UNKNOWN_ELIGIBILITY, [], None)


def reader_skills(user: models.User) -> list[str]:
    # Account skills are [{name, level}], not the opportunity's string array.
    return [
        skill["name"]
        for skill in (user.skills or [])
        if isinstance(skill, dict) and isinstance(skill.get("name"), str) and skill["name"].strip()
    ]


def reader_profile_summary(user: models.User) -> dict:
    profile = user.field_profile if isinstance(user.field_profile, dict) else {}
    return {
        "stream": profile.get("stream"),
        "interests": profile.get("interests") or [],
        "graduation_year": user.graduation_year,
        "country": chosen_country(profile),
    }


def pick_reason(
    opportunity: models.Opportunity,
    user: models.User,
    code: str,
    text: str,
    *,
    matched_term: str | None = None,
    rank: float | None = None,
) -> dict:
    return {
        "code": code,
        "text": text,
        "matched_term": matched_term,
        "rank": rank,
        "eligibility": eligibility_for(opportunity, user).meta(),
        "opportunity": {
            "slug": opportunity.slug,
            "title": opportunity.title,
            "company": opportunity.company.name if opportunity.company else "Unknown",
            "category": opportunity.category,
        },
    }
