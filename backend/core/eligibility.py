"""Shared eligibility rules for source-provided opportunity metadata."""

ELIGIBLE_EXPERIENCED_ONLY_META_KEY = "eligible_experienced_only"
EXPERIENCED_PROFESSIONALS_ELIGIBILITY = "Experienced Professionals"

STUDENT_FACING_ELIGIBILITY_TAGS = frozenset(
    {
        "Undergraduate",
        "Postgraduate",
        "Fresher",
        "School Students",
        "Engineering Students",
        "Management",
        "Medical",
        "Law",
        "Arts, Commerce, Sciences",
        "Arts, Commerce, Sciences & Others",
        "MBA Students",
        "All",
    }
)


def is_eligible_experienced_only(eligibility: list[str]) -> bool:
    eligibility_set = set(eligibility)
    return EXPERIENCED_PROFESSIONALS_ELIGIBILITY in eligibility_set and eligibility_set.isdisjoint(
        STUDENT_FACING_ELIGIBILITY_TAGS
    )
