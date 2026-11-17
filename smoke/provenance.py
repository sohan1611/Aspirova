"""Pure checks for honest listing labels, used by the production canary.

Audit TRUST-06 (no "verified employer" inflation) and DISC-08 (posted versus seen) were
already met when checked on 2026-11-17; these checks keep them met.
"""

import re

# A card line that is itself a verification badge. Whole-line matches only, so titles
# such as "Partner Manager" or "Certified Nursing Assistant" can never trip it.
CLAIM_BADGE = re.compile(
    r"^(?:✓\s*)?(?:"
    r"verified(?: employer| company| listing| job| source)?"
    r"|official(?: listing| employer| partner| job| source)?"
    r"|trusted(?: employer| company| source)?"
    r"|vetted"
    r"|authori[sz]ed(?: employer| partner)?"
    r"|certified(?: employer| company)"
    r")$",
    re.IGNORECASE,
)
APPLICATION_NOTE = "Aspirova never handles your application."
DISCLOSURE = re.compile(r"Opens [^\n]+?" + re.escape(APPLICATION_NOTE))
# "(amazon.jobs)" for company/ATS/job-board copy; "on example.com." for unclassified.
DISCLOSED_HOST = re.compile(
    r"\(([a-z0-9-]+(?:\.[a-z0-9-]+)+)\)|\bon ([a-z0-9-]+(?:\.[a-z0-9-]+)+)\.",
    re.IGNORECASE,
)


def card_label_problems(card_texts: list[str]) -> list[str]:
    """Verification badges, or a "New" badge without a source posting date."""
    problems = []
    for text in card_texts:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        claims = [line for line in lines if CLAIM_BADGE.match(line)]
        if claims:
            problems.append(f"verification claim {claims!r} on card {lines[:3]!r}")
        # "New" means a recent date published by the source, never a crawler sighting.
        if "New" in lines and not any(line.startswith("Posted") for line in lines):
            problems.append(
                f"'New' without a source posting date on card {lines[:3]!r}"
            )
    return problems


def _bare(host: str) -> str:
    host = host.lower().rstrip(".")
    return host[4:] if host.startswith("www.") else host


def disclosure_problem(main_text: str, apply_host: str) -> str | None:
    """The detail page says where Apply goes, and Apply really goes there."""
    match = DISCLOSURE.search(main_text)
    if match is None:
        return "no 'Opens … Aspirova never handles your application.' disclosure"
    disclosed = DISCLOSED_HOST.search(match.group(0))
    if disclosed is None:
        return None  # A destination without a host has nothing to compare.
    host = _bare(disclosed.group(1) or disclosed.group(2))
    actual = _bare(apply_host)
    if actual != host and not actual.endswith("." + host):
        return f"disclosure names {host} but Apply goes to {actual}"
    return None
