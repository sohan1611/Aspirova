import pytest

from scripts.setup_razorpay_plans import _plan_action, _razorpay_key_mode


@pytest.mark.parametrize(
    ("existing_plan_id", "relink"),
    [
        (None, False),
        (None, True),
        ("", False),
    ],
)
def test_plan_action_creates_when_plan_id_is_missing(
    existing_plan_id: str | None,
    relink: bool,
) -> None:
    assert _plan_action(existing_plan_id, relink) == "create"


def test_plan_action_skips_existing_plan_id_without_relink() -> None:
    assert _plan_action("plan_x", False) == "skip"


def test_plan_action_relinks_existing_plan_id() -> None:
    assert _plan_action("plan_x", True) == "relink"


@pytest.mark.parametrize(
    ("key_id", "expected_mode"),
    [
        ("rzp_live_abc", "live"),
        ("rzp_test_abc", "test"),
        ("something_else", "unknown"),
    ],
)
def test_razorpay_key_mode(key_id: str, expected_mode: str) -> None:
    assert _razorpay_key_mode(key_id) == expected_mode
