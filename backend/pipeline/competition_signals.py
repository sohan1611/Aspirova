"""Deterministic competition prize signals shared by ingest and backfills."""

import re
from decimal import Decimal
from typing import Any

INR_PRIZE_CURRENCY_TOKENS = ("fa-rupee", "fa-inr", "fa-rupee-sign", "INR", "inr")
# Approximate; used only to order and filter prizes across currencies, never displayed.
FX_TO_INR = {"USD": 88, "EUR": 100, "GBP": 115, "CAD": 63, "AUD": 57, "SGD": 67, "INR": 1}
CURRENCY_TOKENS = {
    **dict.fromkeys(INR_PRIZE_CURRENCY_TOKENS, "INR"),
    **dict.fromkeys(("fa-dollar", "fa-usd", "USD"), "USD"),
    **dict.fromkeys(("fa-eur", "EUR"), "EUR"),
    **dict.fromkeys(("fa-gbp", "GBP"), "GBP"),
}
PRIZE_PREFIXES = {
    "$CAD": "CAD",
    "$AUD": "AUD",
    "$SGD": "SGD",
    "$EUR": "EUR",
    "$GBP": "GBP",
    "$INR": "INR",
    "CAD": "CAD",
    "AUD": "AUD",
    "SGD": "SGD",
    "CA$": "CAD",
    "C$": "CAD",
    "A$": "AUD",
    "S$": "SGD",
    "$": "USD",
    "₹": "INR",
    "€": "EUR",
    "£": "GBP",
    "INR": "INR",
    "USD": "USD",
    "EUR": "EUR",
    "GBP": "GBP",
}
PRIZE_RE = re.compile(
    r"^("
    + "|".join(re.escape(prefix) for prefix in sorted(PRIZE_PREFIXES, key=len, reverse=True))
    + r")\s*(\d[\d,]*(?:\.\d+)?)(?![\d.])(?:\s.*)?$"
)
NON_MONEY_RE = re.compile(
    r"\b(?:credits?|domains?|goodies|vouchers?|coupons?|merchandise|merch|swag|"
    r"subscriptions?|licen[cs]es?|hampers?|gifts?|eligible|all\s+participants|"
    r"every\s+participant|participant\s+rewards?)\b",
    re.IGNORECASE,
)
STATED_POOL_RE = re.compile(
    r"\b(?:prize\s+pool|total|overall\s+prize|prize\s+bucket|prizes\s+worth)\b",
    re.IGNORECASE,
)
CURRENCY_SYMBOLS = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£"}
DISPLAY_PREFIXES = {"$CAD": "CA$", "$AUD": "A$", "$SGD": "S$", "$INR": "₹"}


def _positive_cash(value: Any) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    if isinstance(value, str) and not re.fullmatch(
        r"\s*[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\s*", value
    ):
        return None
    amount = Decimal(str(value).strip())
    return amount if amount.is_finite() and amount > 0 else None


def _format_amount(amount: Decimal, currency: str) -> str:
    whole, _, fraction = format(amount, "f").partition(".")
    fraction = fraction.rstrip("0")
    if currency == "INR" and len(whole) > 3:
        whole = re.sub(r"(\d)(?=(\d{2})+$)", r"\1,", whole[:-3]) + "," + whole[-3:]
    else:
        whole = f"{int(whole):,}"
    return CURRENCY_SYMBOLS[currency] + whole + (f".{fraction}" if fraction else "")


def _prize_pool(meta: dict[str, Any] | None) -> tuple[int, str] | None:
    meta = meta or {}
    entries: list[tuple[Decimal, str, str]] = []
    prizes = meta.get("prizes")
    for prize in prizes if isinstance(prizes, list) else []:
        if not isinstance(prize, dict):
            continue
        token = prize.get("currency")
        currency = CURRENCY_TOKENS.get(token) if isinstance(token, str) else None
        cash = _positive_cash(prize.get("cash"))
        rank = prize.get("rank") if isinstance(prize.get("rank"), str) else ""
        if currency and cash is not None and not NON_MONEY_RE.search(rank):
            entries.append((cash, currency, rank))
    stated_pools = [entry for entry in entries if STATED_POOL_RE.search(entry[2])]
    if stated_pools:
        entries = [max(stated_pools, key=lambda entry: entry[0] * FX_TO_INR[entry[1]])]
    if entries:
        pools: dict[str, Decimal] = {}
        for cash, currency, _rank in entries:
            pools[currency] = pools.get(currency, Decimal(0)) + cash
        total = sum(cash * FX_TO_INR[currency] for currency, cash in pools.items())
        display = " + ".join(_format_amount(cash, currency) for currency, cash in pools.items())
        return round(total), display
    prize = meta.get("prize")
    match = PRIZE_RE.fullmatch(prize.strip()) if isinstance(prize, str) else None
    if match:
        amount = _positive_cash(match[2].replace(",", ""))
        if amount is not None:
            display = prize.strip()
            if match[1] in DISPLAY_PREFIXES:
                display = DISPLAY_PREFIXES[match[1]] + display[len(match[1]) :]
            return round(amount * FX_TO_INR[PRIZE_PREFIXES[match[1]]]), display
    return None


def prize_pool_inr(meta: dict[str, Any] | None) -> int | None:
    pool = _prize_pool(meta)
    return pool[0] if pool is not None else None


def merge_competition_signals(meta: dict[str, Any] | None, category: str | None) -> dict[str, Any]:
    result = dict(meta or {})
    if category in {"hackathon", "competition", "scholarship"}:
        pool = _prize_pool(result)
        result.pop("prize_inr", None)
        result.pop("prize_text", None)
        if pool is not None:
            result["prize_inr"], result["prize_text"] = pool
    return result
