"""Shared organiser reputation and type classification helpers."""

import re
from collections.abc import Sequence

from sqlalchemy import case, func

# Deterministic reputation signal - string matching, no AI, no per-user work.
# Every acronym is word-boundary anchored on BOTH sides because the naive
# substring test is wrong in ways that matter here, verified against real rows:
#   "KIIT School of Management"                 must NOT match IIT
#   "Institute of Information Technology (IITM)" must NOT match IIT
#   "IGNITE"                                     must NOT match NIT
#   "IIT Delhi", "Indian Institute of Technology Bhubaneswar"  MUST match
REPUTED_ORGANISER_REGEX = (
    r"(^|[^A-Za-z])(IIT|IIM|IISc|IISER|IIIT|NIT|BITS)([^A-Za-z]|$)"
    r"|indian institute of (technology|management|science)"
    r"|birla institute of technology"
    r"|national institute of technology"
    r"|(^|[^a-z])national([^a-z]|$)"
    r"|smart india hackathon"
)

ORGANISER_TYPE_LABELS = {
    "iit": "IIT",
    "iisc": "IISc",
    "iiser": "IISER",
    "nit": "NIT",
    "iiit": "IIIT",
    "tifr": "TIFR",
    "csir": "CSIR",
    "government": "Government",
    "university": "University",
    "company": "Company",
    "other": "Other",
}

_ORGANISER_TYPE_PATTERNS: Sequence[tuple[str, str]] = (
    ("iit", r"(^|[^A-Za-z])IIT([^A-Za-z]|$)|indian institute of technology"),
    (
        "iiser",
        r"(^|[^A-Za-z])IISER([^A-Za-z]|$)" r"|indian institute of science education and research",
    ),
    (
        "iisc",
        r"(^|[^A-Za-z])IISc([^A-Za-z]|$)|indian institute of science",
    ),
    ("nit", r"(^|[^A-Za-z])NIT([^A-Za-z]|$)|national institute of technology"),
    (
        "iiit",
        r"(^|[^A-Za-z])IIIT([^A-Za-z]|$)|indian institute of information technology",
    ),
    (
        "tifr",
        r"(^|[^A-Za-z])TIFR([^A-Za-z]|$)|tata institute of fundamental research",
    ),
    (
        "csir",
        r"(^|[^A-Za-z])CSIR([^A-Za-z]|$)" r"|council of scientific and industrial research",
    ),
    (
        "government",
        r"(^|[^a-z])(government|govt|ministry|department|authority|bureau)([^a-z]|$)"
        r"|smart india hackathon",
    ),
    (
        "university",
        r"(^|[^A-Za-z])(IIM|BITS)([^A-Za-z]|$)"
        r"|university|institute|college|school|academy|polytechnic|vidyapeeth",
    ),
    (
        "company",
        r"(^|[^a-z])(company|corp|corporation|inc|llc|llp|ltd|limited|pvt)([^a-z]|$)"
        r"|technologies|technology|tech|solutions|labs|systems|software",
    ),
)

_REPUTED_ORGANISER = re.compile(REPUTED_ORGANISER_REGEX, re.IGNORECASE)
_COMPILED_TYPE_PATTERNS = [
    (organiser_type, re.compile(pattern, re.IGNORECASE))
    for organiser_type, pattern in _ORGANISER_TYPE_PATTERNS
]


def is_reputed_organiser(name: str | None) -> bool:
    """Return whether a name matches the digest's deterministic reputation signal."""
    return bool(name and _REPUTED_ORGANISER.search(name))


def classify_organiser(name: str | None) -> str:
    """Classify an organiser name into a stable broad type for competition filters."""
    if not name or not name.strip():
        return "other"

    for organiser_type, pattern in _COMPILED_TYPE_PATTERNS:
        if pattern.search(name):
            return organiser_type
    return "other"


def organiser_type_expression(name_expression):
    """SQL expression equivalent of classify_organiser() for feed filtering/facets."""
    haystack = func.coalesce(name_expression, "")
    return case(
        *[
            (haystack.op("~*")(pattern), organiser_type)
            for organiser_type, pattern in _ORGANISER_TYPE_PATTERNS
        ],
        else_="other",
    )
