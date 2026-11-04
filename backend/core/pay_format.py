"""Shared formatting for compensation explicitly stated by a listing."""

import math


def _positive_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) and value > 0 else None


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
