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
