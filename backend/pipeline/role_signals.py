"""Conservative role metadata from explicit listing text; no I/O or AI."""

import re

from core.pay_format import monthly_inr_equivalent

_SENTENCES = re.compile(r"[\n\r]+|(?<=[.!?])\s+")
_PAY_WORD = re.compile(
    r"\b(?:salary|pay\s+(?:range|band)|(?:base|fixed)\s+pay|compensation|wage|OTE|"
    r"on[- ]target\s+earnings|(?:incentive|bonus|commission)(?:[- ]based)?\s+earnings|"
    r"(?:hourly|weekly)\s+(?:rate|pay)|paid|stipend|remuneration|CTC)\b",
    re.I,
)
_BENEFIT = re.compile(
    r"\b(?:cell\s+phone|lifestyle|wellness|fitness|development|learning|fertility|"
    r"coffee|lunch|meal|home\s+office|commuter|travel|discretionary|education|"
    r"internet|gym|to\s+and\s+from\s+the\s+office)\b",
    re.I,
)
_UNCERTAIN = re.compile(r"\b(?:potential|on\s+average|may\s+pay|might)\b", re.I)
# "Paid/Unpaid internship?" asks a question, and "unpaid leave" is a benefit;
# neither says the internship is unpaid.
_UNPAID_WORD = r"(?<!paid/)(?<!paid /)\bunpaid\b(?!\s+(?:leave|time\s+off|vacation|sick))"
_UNPAID = re.compile(
    rf"\b(?:stipend|internship)\b.{{0,80}}{_UNPAID_WORD}|"
    rf"{_UNPAID_WORD}.{{0,80}}\b(?:stipend|internship)\b",
    re.I,
)
_STIPEND_FIELD = re.compile(r"\bstipend(?:\s+structure)?\s*[:(]", re.I)
_CANADA_PAY_LABEL = re.compile(r"\b(?:CAN|Canada)\s+(?:annual\s+)?$", re.I)
_EXTRA_PAY = re.compile(r"\b(?:incentives?|bonus|bonuses|commissions?)\b", re.I)
_FIXED_PAY = re.compile(r"\bfixed\b", re.I)
_EARNINGS = re.compile(r"\bearnings\b", re.I)
_INTERN_PAY = re.compile(r"\bintern(?:ship)?\s+is\s*$", re.I)
_PARENTHETICAL = re.compile(r"\([^)]*\)")
_STIPEND = re.compile(r"stipend", re.I)
_PAID = re.compile(
    r"competitive\s*stipend(?:\s*package)?|\ba\s+stipend\s+is\s+available\b|"
    r"\bpaid\s+internship\b",
    re.I,
)
_CURRENCY = r"(?:CA\$|C\$|A\$|S\$|INR|USD|CAD|AUD|SGD|GBP|EUR|₹|\$|£|€)"
_NUMBER = r"\d+(?:[,.]\d+)*"
_DOT_THOUSANDS = re.compile(r"\d{1,3}(?:\.\d{3})+")
_VALID_NUMBER = re.compile(r"(?:\d+(?:\.\d+)?|\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d{1,3}(?:\.\d{3})+)")
_INDIAN_NUMBER = re.compile(r"\d{1,2}(?:,\d{2})*,\d{3}(?:\.\d+)?")
_CURRENCY_CODE = re.compile(r"\b(INR|USD|CAD|AUD|SGD|GBP|EUR)\b", re.I)
_SCALE = r"(?:lakhs?|lakh|[kl])"
_PERIOD_TOKEN = r"(?:/\s*(?:month|hour|hr|yr|year|week|wk|day))"
_AMOUNTS = re.compile(
    rf"(?<![\w,.])(?P<currency>(?:{_CURRENCY}\s*){{1,2}})?\s*"
    rf"(?P<low>{_NUMBER})(?:\s*(?P<low_scale>{_SCALE})\b)?"
    rf"(?:\s*{_CURRENCY})?(?:\s*{_PERIOD_TOKEN})?"
    rf"(?:\s*(?:[–—-]|\bto\b|\band\b)\s*(?:{_CURRENCY}\s*){{0,2}}"
    rf"(?P<high>{_NUMBER})(?:\s*(?P<high_scale>{_SCALE})\b)?"
    rf"(?:\s*{_CURRENCY})?(?:\s*{_PERIOD_TOKEN})?)?",
    re.I,
)
_MONTH = re.compile(r"/\s*-?\s*month|per\s+month|monthly", re.I)
_HOUR = re.compile(r"/\s*(?:hour|hr)\b|per\s+hour|\bhourly\b", re.I)
_YEAR = re.compile(r"/\s*(?:yr|year)\b|per\s+year|\bannual(?:ly)?\b|\byearly\b", re.I)
_WEEK = re.compile(r"/\s*(?:week|wk)\b|\bper\s+week\b|\bweekly\b", re.I)
_UNSUPPORTED_PERIOD = re.compile(
    r"/\s*(?:day|d)\b|\bper\s+day\b|\bdaily\b|\bbi[- ]?weekly\b|"
    r"\bfortnightly\b|/\s*(?:fortnight|quarter)\b|\bone[- ]time\b|"
    r"\blump[- ]sum\b|\bin\s+total\b",
    re.I,
)
_PERIODS = {"hour": _HOUR, "month": _MONTH, "year": _YEAR, "week": _WEEK, None: _UNSUPPORTED_PERIOD}
_NON_PAY_AMOUNT = re.compile(
    r"\b(?:funding|revenue|budget|raised|tuition|fees?|costs?)\b|"
    r"^\s*(?:users|customers|employees|clients|hours|weeks|months|years)\b",
    re.I,
)
_OTE = re.compile(r"\bOTE\b|on[- ]target\s+earnings", re.I)
_PART_TIME = re.compile(r"\bpart[- ]time\b", re.I)
_PART_TIME_LINE = re.compile(r"^\s*(?:employment\s+)?type\s*:\s*part[- ]time\b", re.I | re.M)
_JOB_OFFER = re.compile(
    r"\bpre[- ]placement\s+offer\b|\bFTE\s+conversion\b|"
    r"\bfull[- ]time\s+conversion\b|\bconversion\s+to\s+full[- ]time\b|"
    r"\bfull[- ]time\s+role\s+based\s+on\s+performance\b",
    re.I,
)
_PPO = re.compile(r"\bPPO\b")
_DURATION = re.compile(
    r"\b(?:internship\s+)?duration\s*:?\s*(?:from\s+)?"
    r"(?P<label>\d{1,2})(?:\s*(?:to|[–—-])\s*(?P<label_end>\d{1,2}))?\s*months?"
    r"(?:\s+to\s+(?:a\s+maximum\s+)?(?P<extended>\d{1,2})\s*months?)?"
    r"|\b(?P<prefix>\d{1,2})[- ]months?\s+internship\b"
    r"|\binternship\s+for\s+(?P<suffix>\d{1,2})\s+months?\b"
    r"|\bfrom\s+(?P<range_start>\d{1,2})\s+to\s+(?P<range_end>\d{1,2})\s+months?\b"
    r"|\b(?P<months_start>\d{1,2})\s+months?\s+to\s+(?:a\s+maximum\s+)?"
    r"(?P<months_end>\d{1,2})\s+months?\b",
    re.I,
)
_DURATION_EXCLUDE = re.compile(r"\b(?:over|tenure|vesting|leave)\b", re.I)


def _number(value: str, scale: str | None, currency: str) -> float | None:
    # Preserve explicit INR lakh/crore grouping. Other currencies require
    # three-digit comma groups with a leading group of one to three digits.
    if not _VALID_NUMBER.fullmatch(value) and not (
        currency == "INR" and _INDIAN_NUMBER.fullmatch(value)
    ):
        return None
    # European salary bands use dots as thousands separators, including 55.800.
    if _DOT_THOUSANDS.fullmatch(value):
        value = value.replace(".", "")
    amount = float(value.replace(",", ""))
    if scale and amount <= 1000:
        amount *= 1000 if scale.lower() == "k" else 100000
    return amount


def _currency(
    text: str, before: str, pay_word: re.Match | None, country: str | None, stipend: bool
) -> str | None:
    codes = _CURRENCY_CODE.findall(text)
    if codes:
        return codes[-1].upper()
    for symbol, code in (
        ("CA$", "CAD"),
        ("C$", "CAD"),
        ("A$", "AUD"),
        ("S$", "SGD"),
        ("₹", "INR"),
        ("£", "GBP"),
        ("€", "EUR"),
    ):
        if symbol.casefold() in text.casefold():
            return code
    if "$" in text:
        if pay_word and _CANADA_PAY_LABEL.search(before[: pay_word.start()]):
            return "CAD"
        return "USD"
    return "INR" if stipend and country == "IN" else None


def _period(
    before: str, amount_and_after: str, stipend: bool, currency: str, maximum: float
) -> str | None:
    # Prefer the unit attached to this amount, then the nearest preceding unit.
    # Earlier amounts and their periods must not leak into a later pay band.
    for text, nearest in ((amount_and_after, min), (before, max)):
        matches = [
            (match.start(), period)
            for period, pattern in _PERIODS.items()
            for match in pattern.finditer(text)
        ]
        if matches:
            return nearest(matches, key=lambda match: match[0])[1]
    if stipend:
        return "month" if _STIPEND_FIELD.search(before) else None
    if currency == "USD" and maximum < 1000:
        return "hour"
    return "year"


def _plausible(low: float, high: float, currency: str, period: str) -> bool:
    if period == "week":
        return 0 < low <= high
    # USD, CAD, AUD, SGD, GBP and EUR share the non-INR bounds.
    bounds = {
        "month": (500, 1000000) if currency == "INR" else (100, 20000),
        "year": (100000, 200000000) if currency == "INR" else (10000, 3000000),
        "hour": (5, 1000) if currency != "INR" else (1, 0),
    }
    floor, ceiling = bounds[period]
    return floor <= low <= high <= ceiling


def _compensation(text: str, category: str | None, country: str | None) -> dict | None:
    # Some source descriptions glue the attribution directly to a pay unit.
    text = re.sub(r"(?<=\w)(?=Originally posted on\b)", "\n", text)
    sentences = _SENTENCES.split(text)
    # Explicit unpaid wording wins even when a later clause promises paid work.
    if any(_UNPAID.search(sentence) for sentence in sentences):
        return {"unpaid": True, "source": "text"}
    paid_without_amount = False
    first_amount = None
    for sentence in sentences:
        if _UNCERTAIN.search(sentence):
            continue
        stipend = bool(_STIPEND.search(sentence))
        if stipend and _BENEFIT.search(sentence):
            continue
        amounts = list(_AMOUNTS.finditer(sentence))
        previous_end = 0
        for amount in amounts:
            before = sentence[: amount.start()]
            label = _PARENTHETICAL.sub("", sentence[previous_end : amount.start()])
            previous_end = amount.end()
            pay_words = list(_PAY_WORD.finditer(before))
            pay_word = pay_words[-1] if pay_words else None
            close_pay_word = pay_word is not None and amount.start() - pay_word.end() <= 80
            context = before + amount.group()
            after = sentence[amount.end() : amount.end() + 24]
            monthly_range = (
                amount.group("high") is not None
                and "₹" in amount.group()
                and _MONTH.search(context + after)
            )
            # Some ATS listings state the monthly amount as "Intern is $800 USD monthly".
            intern_pay = _INTERN_PAY.search(before) and _MONTH.search(after)
            if not close_pay_word and not monthly_range and not intern_pay:
                continue
            if _EXTRA_PAY.search(label) and not (len(amounts) == 1 and _EARNINGS.search(sentence)):
                continue
            pay_label = before[pay_word.end() :] if pay_word else label
            if _NON_PAY_AMOUNT.search(pay_label) or _NON_PAY_AMOUNT.search(after):
                continue
            currency = _currency(amount.group(), before, pay_word, country, stipend)
            if currency is None:
                continue
            low = _number(
                amount.group("low"),
                amount.group("low_scale") or amount.group("high_scale"),
                currency,
            )
            high = (
                _number(amount.group("high"), amount.group("high_scale"), currency)
                if amount.group("high")
                else low
            )
            if low is None or high is None:
                continue
            low, high = sorted((low, high))
            period = _period(label, amount.group() + after, stipend, currency, high)
            if period is None or not _plausible(low, high, currency, period):
                continue
            result = {
                "min": low,
                "max": high,
                "currency": currency,
                "period": period,
                "source": "text",
            }
            if monthly_inr_equivalent({"compensation": result}) is None:
                continue
            if _OTE.search(context + after):
                result["ote"] = True
            if _FIXED_PAY.search(label):
                return result
            if first_amount is None:
                first_amount = result
        if category == "internship" and _PAID.search(sentence):
            paid_without_amount = True
    if first_amount is not None:
        return first_amount
    return {"paid": True, "source": "text"} if paid_without_amount else None


def role_signals(
    title: str | None, description: str | None, category: str | None, country: str | None
) -> dict:
    """Return only signals explicitly supported by the role's text."""
    title, description = title or "", description or ""
    text = f"{title}\n{description}"
    result = {}
    compensation = _compensation(text, category, country)
    if compensation:
        result["compensation"] = compensation
    if _PART_TIME.search(title) or _PART_TIME_LINE.search(description):
        result["part_time"] = True
    if category == "internship":
        for sentence in _SENTENCES.split(text):
            if _DURATION_EXCLUDE.search(sentence):
                continue
            duration = _DURATION.search(sentence)
            if duration:
                months = max(int(value) for value in duration.groups() if value)
                if 1 <= months <= 24:
                    result["duration_months"] = months
                    break
        if _PPO.search(text) or _JOB_OFFER.search(text):
            result["job_offer"] = True
    return result


def merge_role_signals(
    meta: dict | None,
    title: str | None,
    description: str | None,
    category: str | None,
    country: str | None,
) -> dict:
    """Refresh text signals while preserving structured compensation."""
    merged = dict(meta or {})
    if category not in {"internship", "job"}:
        return merged
    signals = role_signals(title, description, category, country)
    compensation = merged.get("compensation")
    if isinstance(compensation, dict) and compensation.get("source") == "unstop":
        signals.pop("compensation", None)
    elif isinstance(compensation, dict) and compensation.get("source") != "text":
        signals.pop("compensation", None)
    elif isinstance(compensation, dict):
        merged.pop("compensation", None)
    merged.update(signals)
    return merged
