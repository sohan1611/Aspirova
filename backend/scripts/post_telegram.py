"""Preview the daily Telegram channel post, or send it with --apply.

Usage:
    uv run python -m scripts.post_telegram
    uv run python -m scripts.post_telegram --apply
"""

import argparse
import html
import logging
import math
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import and_, case, exists, func, not_, or_, select, text
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.sql import Select

from api.filters import competition_prize_expression, open_opportunity_filters
from core import models
from core.config import get_settings
from core.db import make_engine

logger = logging.getLogger(__name__)
INDIA_TIME = ZoneInfo("Asia/Kolkata")
MESSAGE_LIMIT = 4096
Sender = Callable[[str], int]


@dataclass
class TelegramResult:
    items: int = 0
    sent: bool = False
    failures: int = 0

    @property
    def exit_code(self) -> int:
        return 1 if self.failures else 0


class TelegramSendError(Exception):
    """A send failed without exposing its credential-bearing URL."""


def _candidate_query() -> Select[tuple[models.Opportunity]]:
    already_posted = exists(
        select(models.TelegramPost.id).where(
            models.TelegramPost.opportunity_id == models.Opportunity.id
        )
    )
    return (
        select(models.Opportunity)
        .options(joinedload(models.Opportunity.company))
        .where(
            *open_opportunity_filters(),
            not_(already_posted),
            models.Opportunity.first_seen_at >= func.now() - text("interval '14 days'"),
            models.Opportunity.first_seen_at <= func.now(),
            or_(
                models.Opportunity.country == "IN",
                and_(
                    models.Opportunity.is_remote.is_(True),
                    func.btrim(func.coalesce(models.Opportunity.country, "")) == "",
                ),
            ),
        )
    )


def select_candidates(session: Session) -> list[models.Opportunity]:
    compensation = models.Opportunity.meta["compensation"]
    unpaid = compensation["unpaid"].as_boolean().is_(True)
    paid = and_(
        func.jsonb_typeof(compensation) == "object",
        compensation["unpaid"].as_boolean().is_not(True),
    )
    internships = session.scalars(
        _candidate_query()
        .where(models.Opportunity.category == "internship", not_(unpaid))
        .order_by(
            case((paid, 0), else_=1),
            models.Opportunity.first_seen_at.desc(),
            models.Opportunity.id.desc(),
        )
        .limit(5)
    ).all()
    competitions = session.scalars(
        _candidate_query()
        .where(
            models.Opportunity.category.in_(("hackathon", "competition")),
            models.Opportunity.deadline > func.now(),
        )
        .order_by(
            competition_prize_expression().desc().nulls_last(),
            models.Opportunity.deadline.asc(),
            models.Opportunity.id.asc(),
        )
        .limit(3)
    ).all()
    return [*internships, *competitions]


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


def _prize(meta: dict | None) -> str | None:
    value = (meta or {}).get("prize_text")
    return value.strip() if isinstance(value, str) and value.strip() else None


def _place(opportunity: models.Opportunity) -> str | None:
    places = [
        part.strip() for part in re.split(r"[,;]", opportunity.location or "") if part.strip()
    ]
    if not places:
        return "Remote" if opportunity.is_remote else None
    return places[0] + (f" +{len(places) - 1} more" if len(places) > 1 else "")


def _item(opportunity: models.Opportunity) -> str:
    slug = quote(opportunity.slug, safe="")
    url = f"https://www.aspirova.org/opportunity/{slug}?utm_source=telegram&utm_medium=channel"
    lines = [f'<a href="{html.escape(url, quote=True)}">{html.escape(opportunity.title)}</a>']
    if opportunity.company:
        lines.append(html.escape(opportunity.company.name))
    place = _place(opportunity)
    if place:
        lines.append(html.escape(place))
    pay = (
        format_pay(opportunity.meta)
        if opportunity.category == "internship"
        else _prize(opportunity.meta)
    )
    if pay:
        lines.append(html.escape(pay))
    if opportunity.deadline:
        deadline = opportunity.deadline.astimezone(INDIA_TIME).strftime("%d %b %Y")
        lines.append(f"Apply by {html.escape(deadline)}")
    return "\n".join(lines)


def build_message(
    candidates: Sequence[models.Opportunity], now: datetime | None = None
) -> tuple[str, list[models.Opportunity]]:
    date = (now or datetime.now(INDIA_TIME)).astimezone(INDIA_TIME).strftime("%d %b %Y")
    message = f"<b>Today on Aspirova</b>\n{html.escape(date)}"
    included = []
    for opportunity in candidates:
        updated = f"{message}\n\n{_item(opportunity)}"
        if len(updated.encode("utf-16-le")) // 2 >= MESSAGE_LIMIT:
            break
        message = updated
        included.append(opportunity)
    return message, included


def _posted_today(session: Session, now: datetime) -> bool:
    start = now.astimezone(INDIA_TIME).replace(hour=0, minute=0, second=0, microsecond=0)
    return bool(
        session.scalar(
            select(
                exists().where(
                    models.TelegramPost.posted_at >= start,
                    models.TelegramPost.posted_at < start + timedelta(days=1),
                )
            )
        )
    )


def post_telegram(
    session: Session,
    *,
    apply: bool = False,
    sender: Sender | None = None,
) -> TelegramResult:
    if apply and sender is None:
        raise ValueError("sender is required in apply mode")
    if _posted_today(session, datetime.now(INDIA_TIME)):
        logger.info("Today's Telegram post has already been sent")
        return TelegramResult()
    message, included = build_message(select_candidates(session))
    result = TelegramResult(items=len(included))
    if not included:
        logger.info("No Telegram candidates")
        return result
    if not apply:
        logger.info("Telegram dry run (%d listings):\n%s", result.items, message)
        return result
    assert sender is not None
    try:
        message_id = sender(message)
        if not isinstance(message_id, int) or isinstance(message_id, bool):
            raise TelegramSendError("Invalid Telegram message id")
    except Exception:
        logger.error("Telegram send failed; no listings recorded")
        result.failures = 1
        return result
    for opportunity in included:
        session.add(models.TelegramPost(opportunity_id=opportunity.id, message_id=message_id))
    session.commit()
    result.sent = True
    logger.info("Telegram post sent (%d listings)", result.items)
    return result


def _http_sender(client: httpx.Client, token: str, channel_id: str) -> Sender:
    # httpx logs request URLs at INFO, and Telegram puts the token in the URL.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    def send(message: str) -> int:
        try:
            response = client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={
                    "chat_id": channel_id,
                    "text": message,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
            )
        except Exception:
            response = None
        if response is None:
            raise TelegramSendError("Telegram request failed") from None
        try:
            body = response.json()
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        result = body.get("result")
        message_id = result.get("message_id") if isinstance(result, dict) else None
        if (
            response.status_code == 200
            and body.get("ok") is True
            and isinstance(message_id, int)
            and not isinstance(message_id, bool)
        ):
            return message_id
        description = body.get("description")
        safe_description = (
            description.replace(token, "[redacted]")
            if isinstance(description, str)
            else "Invalid Telegram response"
        )
        logger.error("Telegram HTTP %d: %s", response.status_code, safe_description)
        raise TelegramSendError("Telegram send failed") from None

    return send


def main() -> int:
    parser = argparse.ArgumentParser(description="Preview or send the daily Telegram channel post.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Preview only (default).")
    mode.add_argument("--apply", action="store_true", help="Send and record the post.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    settings = get_settings()
    if args.apply and (
        not settings.telegram_bot_token.strip() or not settings.telegram_channel_id.strip()
    ):
        logger.error("--apply requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHANNEL_ID")
        return 1
    engine = make_engine()
    with Session(engine) as session:
        if not args.apply:
            return post_telegram(session).exit_code
        with httpx.Client(timeout=30.0) as client:
            sender = _http_sender(client, settings.telegram_bot_token, settings.telegram_channel_id)
            return post_telegram(session, apply=True, sender=sender).exit_code


if __name__ == "__main__":
    raise SystemExit(main())
