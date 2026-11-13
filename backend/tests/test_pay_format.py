"""Display guards share captured and synthetic fixtures with the frontend."""

import json
from pathlib import Path

import pytest

from core.pay_format import (
    INR_PER_UNIT,
    MAX_PLAUSIBLE_HOURLY_INR,
    MAX_PLAUSIBLE_MONTHLY_INR,
    PERIOD_TO_MONTH,
    format_pay,
    monthly_inr_equivalent,
)

FIXTURES = Path(__file__).parent / "fixtures" / "pay"
DISPLAY_CASES = json.loads((FIXTURES / "display_cases.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", DISPLAY_CASES, ids=lambda case: case["name"])
def test_display_guard(case):
    assert format_pay({"compensation": case["pay"]}) == case["display"]


@pytest.mark.parametrize("path", sorted(FIXTURES.glob("*-*.json")), ids=lambda path: path.stem)
def test_existing_production_amount_is_hidden_before_backfill(path):
    fixture = json.loads(path.read_text(encoding="utf-8"))
    old = fixture["previous_compensation"]
    assert monthly_inr_equivalent({"compensation": old}) is None
    assert format_pay({"compensation": old}) is None
    assert format_pay({"compensation": {**old, "paid": True}}) == "Paid"


@pytest.mark.parametrize("currency,fx", INR_PER_UNIT.items())
@pytest.mark.parametrize("period,factor", PERIOD_TO_MONTH.items())
def test_display_and_sort_share_plausibility_at_each_ceiling(currency, fx, period, factor):
    ceiling = MAX_PLAUSIBLE_MONTHLY_INR / factor / fx
    if period == "hour":
        ceiling = min(ceiling, MAX_PLAUSIBLE_HOURLY_INR / fx)
    for amount in (ceiling * 0.999999, ceiling * 1.000001):
        pay = {"min": amount, "max": amount, "currency": currency, "period": period}
        accepted = monthly_inr_equivalent({"compensation": pay}) is not None
        assert (format_pay({"compensation": pay}) is not None) == accepted


@pytest.mark.parametrize("value", [float("inf"), float("nan"), 10**400, True, [], {}])
def test_malformed_display_amounts_fall_back_to_paid(value):
    pay = {"min": value, "max": value, "currency": "USD", "period": "hour", "paid": True}
    assert format_pay({"compensation": pay}) == "Paid"
