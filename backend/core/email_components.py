"""Pure, table-based email primitives shared by every student notification."""

import re
from datetime import datetime, timezone
from html import escape
from typing import Literal
from urllib.parse import quote, urlencode, urlsplit

from core import models
from core.config import get_settings
from core.pay_format import format_pay

BRAND = "#0b4fd6"
BRAND_DEEP = "#1e40af"
INK = "#0f172a"
MUTED = "#5a6475"
BORDER = "#e2e7f0"
PAGE_BG = "#f1f4f9"
CARD_BG = "#ffffff"
ACCENT_BG, ACCENT_INK = "#eaf0fd", "#0b3fae"
URGENT = ("#fdecea", "#b42318")
SOON = ("#fff4e5", "#8a4b00")
SUCCESS = ("#e8f5ee", "#1d6b40")
NEUTRAL = ("#eef1f7", "#1e293b")
BODY_FONT = (
    "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;"
)
HEADING_FONT = "font-family:Georgia,'Times New Roman',serif;"
TABLE = 'role="presentation" cellpadding="0" cellspacing="0" border="0"'
DeadlinePolicy = Literal["explicit_only", "any"]
_PLACEHOLDERS = {"unknown", "none", "not stated", "location", "n/a", "na", "tbd", "tba", "-"}
_TYPE_COLORS = {
    "internship": (ACCENT_BG, ACCENT_INK),
    "job": SUCCESS,
    "hackathon": ("#f3ecfd", "#6b2fb3"),
    "competition": ("#f3ecfd", "#6b2fb3"),
    "fellowship": SOON,
    "scholarship": SOON,
}
_TILE_COLORS = [BRAND, BRAND_DEEP, ACCENT_INK, "#334155", "#0f766e"]


def _collapse_whitespace(value: str | None) -> str:
    return " ".join((value or "").split())


def _clean(value: str | None) -> str:
    value = _collapse_whitespace(value)
    return "" if value.casefold() in _PLACEHOLDERS else value


def _shorten(value: str, limit: int) -> str:
    value = _collapse_whitespace(value)
    if len(value) <= limit:
        return value
    prefix = value[: limit - 1]
    return (prefix.rsplit(" ", 1)[0] if " " in prefix else prefix) + "…"


def _http_url(value: str | None) -> str | None:
    try:
        parsed = urlsplit((value or "").strip())
        if parsed.scheme.lower() in {"http", "https"} and parsed.netloc:
            return value.strip()
    except ValueError:
        pass
    return None


def _utc(value: datetime) -> datetime:
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )


def greeting(display_name: str | None) -> str:
    name = _collapse_whitespace(display_name)
    return f"Hi {name.split()[0]}," if name and "@" not in name else "Hi there,"


def listing_url(opportunity: models.Opportunity) -> str:
    site = (_http_url(get_settings().site_url) or "https://www.aspirova.org").rstrip("/")
    return f"{site}/opportunity/{quote(opportunity.slug or '', safe='')}"


def button(
    label: str, url: str, *, full_width_on_mobile: bool = True, secondary: bool = False
) -> str:
    url = _http_url(url)
    if not url:
        return ""
    bg, ink = (CARD_BG, BRAND) if secondary else (BRAND, CARD_BG)
    mobile_class = ' class="em-button"' if full_width_on_mobile else ""
    return (
        f'<table {TABLE}{mobile_class} style="border-collapse:separate"><tr{mobile_class}>'
        f'<td{mobile_class} bgcolor="{bg}" align="center" style="background-color:{bg};'
        f'border:1px solid {BRAND};border-radius:8px;mso-padding-alt:14px 28px">'
        f'<a{mobile_class} href="{escape(url, quote=True)}" style="{BODY_FONT}'
        f"color:{ink};display:inline-block;font-size:15px;font-weight:700;line-height:20px;"
        'padding:14px 28px;text-align:center;text-decoration:none;border-radius:8px">'
        f"{escape(label, quote=True)}</a></td></tr></table>"
    )


def pill(text: str, bg: str, ink: str) -> str:
    return (
        f'<span style="background-color:{escape(bg, quote=True)};'
        f"color:{escape(ink, quote=True)};{BODY_FONT}display:inline-block;"
        "font-size:12px;font-weight:700;line-height:18px;padding:3px 8px;"
        'border-radius:999px;margin:0 6px 6px 0">'
        f"{escape(text, quote=True)}</span>"
    )


def type_label(category: str | None) -> str:
    return _collapse_whitespace(category).replace("_", " ").capitalize()


def type_tag(category: str | None) -> str:
    label = type_label(category)
    return pill(label, *_TYPE_COLORS.get((category or "").casefold(), NEUTRAL)) if label else ""


def section(heading: str, count: int, cards_html: str, *, see_all_url: str | None = None) -> str:
    url = _http_url(see_all_url)
    link = (
        f'<td align="right"><a href="{escape(url, quote=True)}" '
        f'class="em-link" style="color:{BRAND};font-size:12px;'
        'text-decoration:underline">See all →</a></td>'
        if url
        else ""
    )
    return (
        f'<table {TABLE} width="100%" style="margin:20px 0 12px"><tr>'
        f'<td class="em-ink" style="color:{INK};{HEADING_FONT}font-size:18px;font-weight:700">'
        f'{escape(heading, quote=True)} <span class="em-muted" style="{BODY_FONT}'
        f'color:{MUTED};font-size:12px;font-weight:400">{count} new</span></td>{link}'
        f"</tr></table>{cards_html}"
    )


def logo_tile(company: models.Company | None) -> str:
    name = _collapse_whitespace(company.name) if company else ""
    words = name.split()
    initials = "".join(word[0] for word in words[:2]).upper() or "?"
    safe_initials = escape(initials, quote=True)
    logo = _http_url(company.logo_url) if company else None
    if not logo and company and company.domain:
        logo = "https://www.google.com/s2/favicons?" + urlencode(
            {"domain": company.domain, "sz": 64}
        )
    bg = CARD_BG if logo else _TILE_COLORS[sum(map(ord, name or "?")) % len(_TILE_COLORS)]
    content = (
        f'<img src="{escape(logo, quote=True)}" width="44" height="44" alt="{safe_initials}" '
        f'style="background-color:#ffffff;border-radius:8px;display:block;color:{INK};'
        f'{BODY_FONT}font-size:16px;font-weight:700;line-height:44px">'
        if logo
        else safe_initials
    )
    return (
        f'<td width="44" height="44" align="center" valign="middle" bgcolor="{bg}" '
        f'style="background-color:{bg};border:1px solid {BORDER};border-radius:8px;'
        f'width:44px;height:44px;color:#ffffff;{BODY_FONT}font-size:16px;font-weight:700">'
        f"{content}</td>"
    )


def _deadline_text(
    opportunity: models.Opportunity, now: datetime, *, policy: DeadlinePolicy
) -> tuple[str, tuple[str, str]]:
    if opportunity.deadline is None or (
        policy == "explicit_only" and opportunity.deadline_confidence != "explicit"
    ):
        return "", NEUTRAL
    deadline = _utc(opportunity.deadline)
    days = (deadline.date() - _utc(now).date()).days
    if days < 0:
        return "", NEUTRAL
    if days == 0:
        text = "Closes today"
    elif days == 1:
        text = "Closes tomorrow"
    elif days <= 7:
        text = f"Closes in {days} days"
    else:
        text = f"Apply by {deadline.strftime('%d %b')}"
    if policy == "any":
        if opportunity.deadline_confidence == "inferred":
            text += " (est.)"
        elif opportunity.deadline_confidence == "unknown":
            text += " · verify"
    return text, URGENT if days <= 3 else SOON if days <= 7 else NEUTRAL


def deadline_badge(
    opportunity: models.Opportunity, now: datetime, *, policy: DeadlinePolicy
) -> str:
    text, colors = _deadline_text(opportunity, now, policy=policy)
    return pill(text, *colors) if text else ""


def _facts(opportunity: models.Opportunity) -> list[tuple[str, str]]:
    facts = []
    location = _clean(opportunity.location)
    places = [part.strip() for part in re.split(r"[,;]", location) if part.strip()]
    if len(places) > 3:
        places.sort(key=lambda place: place.casefold() != "india")
        location = f"{', '.join(places[:3])} and {len(places) - 3} more"
    if opportunity.is_remote and "remote" not in location.casefold():
        location = f"{location} · Remote" if location else "Remote"
    if location:
        facts.append(("Where", location))
    meta = opportunity.meta or {}
    compensation = meta.get("compensation")
    pay = (
        "Unpaid"
        if isinstance(compensation, dict) and compensation.get("unpaid") is True
        else format_pay(meta)
    )
    if pay:
        facts.append(("Pay", pay))
    duration = meta.get("duration_months")
    if isinstance(duration, (int, float)) and not isinstance(duration, bool) and duration > 0:
        facts.append(("Duration", f"{duration:g} {'month' if duration == 1 else 'months'}"))
    prize = meta.get("prize_text")
    if (
        opportunity.category in {"hackathon", "competition"}
        and isinstance(prize, str)
        and _clean(prize)
    ):
        facts.append(("Prize", f"Prize: {_shorten(prize, 40)}"))
    return facts


def opportunity_card(
    opportunity: models.Opportunity,
    *,
    now: datetime,
    button_url: str,
    button_label: str = "View & Apply",
    deadline_policy: DeadlinePolicy,
    extra_html: str = "",
    secondary_link: tuple[str, str] | None = None,
    company: models.Company | None = None,
) -> tuple[str, str]:
    """Render escaped data. extra_html is a trusted, already-escaped renderer slot."""
    listing = listing_url(opportunity)
    url = _http_url(button_url) or listing
    title = _collapse_whitespace(opportunity.title)
    company = company or opportunity.company
    company_name = _collapse_whitespace(company.name) if company else "Unknown"
    meta = opportunity.meta or {}
    offer = meta.get("job_offer") is True or meta.get("offers_ppo") is True
    facts = [value for _, value in _facts(opportunity)]
    # Reminder/report cards retain the full date as well as the relative badge,
    # unless the badge already shows it ("Apply by 17 Nov", beyond seven days).
    if deadline_policy == "any" and opportunity.deadline is not None:
        deadline = _utc(opportunity.deadline)
        if (deadline.date() - _utc(now).date()).days <= 7:
            facts.append(f"Deadline {deadline.strftime('%d %b %Y')}")
    timing, _ = _deadline_text(opportunity, now, policy=deadline_policy)
    tags = type_tag(opportunity.category) + deadline_badge(opportunity, now, policy=deadline_policy)
    if offer:
        tags += pill("Job offer possible", ACCENT_BG, ACCENT_INK)
    secondary_html, secondary_text = "", ""
    if secondary_link and (secondary_url := _http_url(secondary_link[1])):
        label = secondary_link[0]
        secondary_html = (
            '<p style="margin:12px 0 0;font-size:12px"><a class="em-link" href="'
            f'{escape(secondary_url, quote=True)}" style="color:{BRAND};'
            f'text-decoration:underline">{escape(label, quote=True)}</a></p>'
        )
        secondary_text = f"\n{label}: {secondary_url}"
    html = (
        f'<table {TABLE} width="100%" class="em-card" bgcolor="{CARD_BG}" '
        f'style="background-color:{CARD_BG};border:1px solid {BORDER};border-collapse:separate;'
        'border-spacing:0;border-radius:12px;margin:0 0 12px;width:100%">'
        '<tr><td style="padding:16px;overflow-wrap:anywhere;word-break:break-word">'
        f'<table {TABLE} width="100%"><tr>{logo_tile(company)}'
        '<td valign="top" style="padding-left:12px">'
        '<p style="margin:0 0 4px;font-size:16px;font-weight:700;line-height:22px">'
        f'<a class="em-ink" href="{escape(listing, quote=True)}" '
        f'style="color:{INK};text-decoration:none">{escape(title, quote=True)}</a></p>'
        f'<p class="em-muted" style="color:{MUTED};font-size:14px;line-height:20px;margin:0">'
        f"{escape(company_name, quote=True)}</p></td></tr></table>"
        f'<p style="margin:12px 0 4px">{tags}</p>'
        f'<p class="em-muted" style="color:{MUTED};font-size:13px;line-height:20px;'
        f'margin:0 0 12px">{escape(" · ".join(facts), quote=True)}</p>{extra_html}'
        f"{button(button_label, url)}{secondary_html}</td></tr></table>"
    )
    details = [type_label(opportunity.category), *facts, timing]
    if offer:
        details.append("Job offer possible")
    text = (
        f"{title} — {company_name}\n"
        + " · ".join(value for value in details if value)
        + f"\n{button_label}: {url}{secondary_text}"
    )
    return html, text


def grouped_cards(
    opportunities: list[models.Opportunity], *, now: datetime
) -> tuple[str, str, str]:
    """Return HTML, text and the first displayed card's inbox-preview description."""
    groups = [
        ("Internships", {"internship"}, "/internships"),
        ("Jobs", {"job"}, "/jobs"),
        ("Hackathons & competitions", {"hackathon", "competition"}, "/competitions"),
        ("Fellowships & scholarships", {"fellowship", "scholarship"}, None),
        ("More opportunities", set(), None),
    ]
    known = set(_TYPE_COLORS)
    html_parts, text_parts = [], []
    first_card = ""
    for heading, categories, route in groups:
        items = [
            o
            for o in opportunities
            if o.category in categories or (not categories and o.category not in known)
        ]
        if not items:
            continue
        if not first_card:
            company = items[0].company.name if items[0].company else "Unknown"
            first_card = f"{items[0].title} at {company}"
        cards = [
            opportunity_card(o, now=now, button_url=o.apply_url, deadline_policy="explicit_only")
            for o in items
        ]
        url = get_settings().site_url.rstrip("/") + route if route else None
        html_parts.append(
            section(heading, len(items), "".join(h for h, _ in cards), see_all_url=url)
        )
        text_parts.append(heading + "\n\n" + "\n\n".join(t for _, t in cards))
    return "".join(html_parts), "\n\n".join(text_parts), first_card


def status_panel(kind: Literal["success", "urgent", "accent"], lines: list[str]) -> str:
    bg, ink = {"success": SUCCESS, "urgent": URGENT, "accent": (ACCENT_BG, ACCENT_INK)}[kind]
    paragraphs = "".join(
        '<p style="margin:0 0 8px;font-size:15px;line-height:23px;'
        f'font-weight:{700 if index == 0 else 400}">{escape(line, quote=True)}</p>'
        for index, line in enumerate(lines)
    )
    return (
        f'<table {TABLE} width="100%" bgcolor="{bg}" style="background-color:{bg};'
        f'color:{ink};border-radius:8px;margin:0 0 20px">'
        f'<tr><td style="padding:16px">{paragraphs}</td></tr></table>'
    )
