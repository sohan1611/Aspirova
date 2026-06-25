"""Normalization helpers shared by all adapters and the ingest pipeline
(Doc 04 sec 9 references this module for category classification).
"""

import re

# Word-boundary-safe: \bintern\b alone would still need care, since "intern"
# is a prefix of "internal" and "international" with NO boundary after it in
# either word - the trailing \b after the optional suffix group enforces that
# correctly (verified against real Greenhouse titles like "Internal Audit
# Lead" and "International Strategic Finance", which must NOT match).
_INTERNSHIP_PATTERN = re.compile(
    r"\b(intern(s|ship|ships)?|co-?op|trainee|apprentice(ship)?|campus|new grad(uate)?)\b",
    re.IGNORECASE,
)


def classify_category(title: str) -> str:
    """Rules-based category classification, Phase 1 (Doc 04 sec 9.3, Doc 05 sec 2.3).
    No AI - a placeholder for richer Phase-3/5 tagging."""
    if _INTERNSHIP_PATTERN.search(title):
        return "internship"
    return "job"


def normalize_title(title: str) -> str:
    """Lowercased, whitespace-collapsed title for dedup blocking/trigram matching (Doc 03 sec 7)."""
    return re.sub(r"\s+", " ", title).strip().lower()


_COMPANY_SUFFIX_PATTERN = re.compile(
    r"\b(inc|incorporated|corp|corporation|co|company|ltd|limited|llc|llp|plc|gmbh|sa|ag)\.?$",
    re.IGNORECASE,
)


def normalize_company_name(name: str) -> str:
    """Lowercased, legal-suffix-stripped company name for dedup blocking (Doc 03 sec 7, Doc 04 sec 9.1)."""
    collapsed = re.sub(r"\s+", " ", name).strip().lower()
    stripped = _COMPANY_SUFFIX_PATTERN.sub("", collapsed).strip()
    stripped = stripped.rstrip(",.")
    return stripped or collapsed
