"""Tests for shared organiser classification.

The IIT lookalikes are production-derived traps: substring matching promotes
the wrong organiser silently, so the shared classifier guards those exact names.
"""

from core.organisers import classify_organiser


def test_classify_organiser_keeps_iit_lookalikes_out_of_iit_bucket() -> None:
    """KIIT and IITM contain the letters IIT, but neither is an IIT organiser."""
    iitm_lookalike = "Institute of Information Technology & Management (IITM), Delhi"

    assert classify_organiser("KIIT School of Management") != "iit"
    assert classify_organiser(iitm_lookalike) != "iit"


def test_classify_organiser_recognises_real_iit_and_iisc_names() -> None:
    """Real IIT/IISc names must still drive the reputed organiser filters."""
    assert classify_organiser("Indian Institute of Technology (IIT), Bhubaneswar") == "iit"
    assert classify_organiser("IISc Bangalore") == "iisc"
