"""Shared formatting for compensation explicitly stated by a listing."""

import math

# Approximate rates used only to order listings across currencies, never shown to users.
INR_PER_UNIT = {
    "INR": 1.0,
    "USD": 88.0,
    "EUR": 102.0,
    "GBP": 117.0,
    "CAD": 63.0,
    "AUD": 58.0,
    "SGD": 68.0,
}
HOURS_PER_MONTH = 173.0  # 40 h x 52 weeks / 12.
PERIOD_TO_MONTH = {"month": 1.0, "year": 1 / 12, "hour": HOURS_PER_MONTH}
# About $114/hour. Higher student-listing hourly rates are parse errors.
MAX_PLAUSIBLE_HOURLY_INR = 10_000.0
# ₹1 crore/month, about ₹12 crore or $1.36M a year;
# above that a figure is a parse or period error.
MAX_PLAUSIBLE_MONTHLY_INR = 10_000_000.0


def _positive_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) and number > 0 else None


def monthly_inr_equivalent(meta: dict | None) -> float | None:
    """Normalize disclosed pay for ordering, dropping implausible parsed amounts."""
    compensation = meta.get("compensation") if isinstance(meta, dict) else None
    if not isinstance(compensation, dict) or compensation.get("unpaid") is True:
        return None
    amount = _positive_number(compensation.get("max"))
    if amount is None:
        amount = _positive_number(compensation.get("min"))
    currency = compensation.get("currency")
    period = compensation.get("period")
    if (
        amount is None
        or not isinstance(currency, str)
        or currency not in INR_PER_UNIT
        or not isinstance(period, str)
        or period not in PERIOD_TO_MONTH
    ):
        return None
    fx = INR_PER_UNIT[currency]
    if period == "hour" and amount * fx > MAX_PLAUSIBLE_HOURLY_INR:
        return None
    monthly = amount * PERIOD_TO_MONTH[period] * fx
    return monthly if monthly <= MAX_PLAUSIBLE_MONTHLY_INR else None


def _indian_amount(value: float) -> str:
    whole, _, decimal = f"{value:.2f}".rstrip("0").rstrip(".").partition(".")
    tail = whole[-3:]
    head = whole[:-3]
    groups = []
    while head:
        groups.insert(0, head[-2:])
        head = head[:-2]
    amount = ",".join([*groups, tail])
    return f"{amount}.{decimal}" if decimal else amount


def format_pay(meta: dict | None) -> str | None:
    pay = (meta or {}).get("compensation")
    if not isinstance(pay, dict) or pay.get("unpaid") is True:
        return None
    low = _positive_number(pay.get("min"))
    high = _positive_number(pay.get("max"))
    currency = pay.get("currency")
    period = pay.get("period")
    symbols = {
        "INR": "₹",
        "USD": "$",
        "CAD": "C$",
        "AUD": "A$",
        "SGD": "S$",
        "GBP": "£",
        "EUR": "€",
    }
    if (
        not low
        or not high
        or high < low
        or not isinstance(currency, str)
        or currency not in symbols
        or period not in ("month", "year", "hour")
    ):
        return "Paid" if pay.get("paid") is True else None
    divisor = 1
    suffix = f"/{period}"
    if currency == "INR" and period == "year":
        divisor = 10000000 if high >= 10000000 else 100000
        suffix = " Cr/year" if divisor == 10000000 else " LPA"
    elif currency != "INR" and period == "year" and low >= 1000:
        divisor = 1000

    def amount(value: float) -> str:
        if currency == "INR" and divisor == 1:
            return _indian_amount(value)
        number = f"{value / divisor:,.2f}".rstrip("0").rstrip(".")
        return f"{number}K" if currency != "INR" and divisor == 1000 else number

    amounts = amount(low) if low == high else f"{amount(low)}–{amount(high)}"
    return f"{symbols[currency]}{amounts}{suffix}"
