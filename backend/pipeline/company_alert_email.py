"""Deterministic, database-free company alert email rendering."""

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
from urllib.parse import quote, urlencode, urlsplit

from api.filters import SENIOR_TITLE_PATTERN
from core import models
from core.config import get_settings
from core.email_templates import email_layout, text_footer
from core.pay_format import format_pay

ROLE_LABELS = {
    "software": "Software",
    "data": "Data",
    "design": "Design",
    "marketing": "Marketing",
    "finance": "Finance",
    "hr": "HR",
    "sales": "Sales",
    "product": "Product",
    "operations": "Operations",
    "content": "Content",
    "engineering": "Engineering",
    "research": "Research",
}
BODY_FONT = "font-family:Arial,Helvetica,sans-serif;"
HEADING_FONT = "font-family:Georgia,'Times New Roman',serif;"
TABLE = 'role="presentation" cellpadding="0" cellspacing="0" border="0"'


@dataclass(frozen=True)
class CompanyAlertGroup:
    company: models.Company
    roles: list[str]
    opportunities: list[models.Opportunity]


def _collapse_whitespace(value: str | None) -> str:
    return " ".join((value or "").split())


# "location" is real: a live Stripe listing's location field holds that placeholder.
_PLACEHOLDERS = {"unknown", "none", "not stated", "location", "n/a", "na", "tbd", "tba", "-"}


def _clean(value: str | None) -> str:
    value = _collapse_whitespace(value)
    return "" if value.casefold() in _PLACEHOLDERS else value


def _shorten(value: str, limit: int) -> str:
    value = " ".join(value.split())
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


def _join_names(names: list[str]) -> str:
    return " and ".join(names) if len(names) < 3 else ", ".join(names[:-1]) + " and " + names[-1]


def _domains(roles: list[str]) -> str:
    return (
        _join_names([ROLE_LABELS[role] for role in roles if role in ROLE_LABELS]) or "all domains"
    )


def _utc(value: datetime) -> datetime:
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )


def _facts(opportunity: models.Opportunity, now: datetime) -> list[tuple[str, str]]:
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
    if meta.get("job_offer") is True or meta.get("offers_ppo") is True:
        facts.append(("Job offer", "Possible"))
    if opportunity.deadline_confidence == "explicit" and opportunity.deadline is not None:
        deadline = _utc(opportunity.deadline)
        days = (deadline.date() - _utc(now).date()).days
        timing = "today" if days == 0 else "tomorrow" if days == 1 else f"in {days} days"
        facts.append(("Closes", f"{deadline.strftime('%d %b %Y')} ({timing})"))
    return facts


def _company_header(group: CompanyAlertGroup) -> str:
    company = group.company
    name = _collapse_whitespace(company.name)
    initial = escape(name[:1].upper(), quote=True)
    logo = _http_url(company.logo_url)
    if not company.logo_url and company.domain:
        logo = "https://www.google.com/s2/favicons?" + urlencode(
            {"domain": company.domain, "sz": 64}
        )
    tile = initial
    if logo:
        tile = (
            f'<img src="{escape(logo, quote=True)}" alt="{initial}" width="40" height="40" '
            'style="border:0;border-radius:8px;display:block;height:40px;width:40px">'
        )
    return (
        f'<table {TABLE} width="100%" style="margin:24px 0 14px;width:100%"><tr>'
        '<td width="40" height="40" align="center" bgcolor="#faf7f0" '
        f'style="border-radius:8px;color:#5e2b47;{HEADING_FONT}font-size:22px;'
        f'font-weight:700;height:40px;width:40px">{tile}</td>'
        '<td style="padding-left:12px">'
        f'<p style="color:#2b2620;{HEADING_FONT}font-size:19px;font-weight:700;'
        f'line-height:25px;margin:0">{escape(name, quote=True)}</p>'
        f'<p style="color:#6b6259;{BODY_FONT}font-size:12px;line-height:18px;margin:3px 0 0">'
        f"Following for {escape(_domains(group.roles), quote=True)}</p></td></tr></table>"
    )


def _card(
    opportunity: models.Opportunity, skill_names: set[str], site_url: str, now: datetime
) -> tuple[str, str]:
    listing_url = f"{site_url}/opportunity/{quote(opportunity.slug, safe='')}"
    safe_listing = escape(listing_url, quote=True)
    title = _collapse_whitespace(opportunity.title)
    category = _collapse_whitespace(opportunity.category).capitalize()
    facts = _facts(opportunity, now)
    fact_rows = "".join(
        f'<tr><td valign="top" style="color:#6b6259;{BODY_FONT}font-size:13px;'
        f'line-height:20px;padding:2px 12px 2px 0;white-space:nowrap">{label}</td>'
        f'<td style="color:{"#8a4b2f" if label == "Closes" else "#2b2620"};{BODY_FONT}'
        f'font-size:13px;line-height:20px;padding:2px 0">'
        f"{escape(value, quote=True)}</td></tr>"
        for label, value in facts
    )
    summary = _collapse_whitespace(opportunity.summary)
    summary = _shorten(summary, 220) if summary.casefold() != title.casefold() else ""
    summary_html = (
        f'<p style="color:#6b6259;{BODY_FONT}font-size:14px;line-height:21px;margin:12px 0">'
        f"{escape(summary, quote=True)}</p>"
        if summary
        else ""
    )
    skills = list(
        dict.fromkeys(
            _collapse_whitespace(skill)
            for skill in (opportunity.skills or [])
            if _collapse_whitespace(skill)
        )
    )
    skills.sort(key=lambda skill: skill.casefold() not in skill_names)
    matched_count = sum(skill.casefold() in skill_names for skill in skills)
    chips = []
    for skill in skills[:6]:
        matched = skill.casefold() in skill_names
        chips.append(
            f'<span style="background-color:{"#5e2b47" if matched else "#faf7f0"};'
            f'border-radius:4px;color:{"#ffffff" if matched else "#6b6259"};'
            f"display:inline-block;{BODY_FONT}font-size:12px;line-height:18px;"
            f'margin:0 4px 6px 0;padding:3px 7px">{escape(skill, quote=True)}</span>'
        )
    overlap = ""
    if matched_count:
        overlap = (
            "You have the 1 skill listed"
            if len(skills) == 1
            else f"You have {matched_count} of the {len(skills)} skills listed"
        )
    skills_html = f'<p style="margin:12px 0 0">{"".join(chips)}</p>' if chips else ""
    if overlap:
        skills_html += (
            f'<p style="color:#5e2b47;{BODY_FONT}font-size:12px;line-height:18px;'
            f'margin:0 0 12px">{overlap}</p>'
        )
    apply_url = _http_url(opportunity.apply_url)
    apply_html = (
        f'<p style="margin:12px 0 0"><a href="{escape(apply_url, quote=True)}" '
        f'style="color:#5e2b47;{BODY_FONT}font-size:13px;line-height:20px;'
        'text-decoration:underline">Apply on the original listing</a></p>'
        if apply_url
        else ""
    )
    eyebrow = (
        f'<p style="color:#5e2b47;{BODY_FONT}font-size:11px;font-weight:700;'
        f'letter-spacing:1px;line-height:16px;margin:0 0 8px;text-transform:uppercase">'
        f"{escape(category, quote=True)}</p>"
        if category
        else ""
    )
    html = (
        f'<table {TABLE} width="100%" style="border:1px solid #e7e0d4;'
        "border-collapse:separate;border-radius:10px;border-spacing:0;margin:0 0 12px;"
        'width:100%"><tr><td style="padding:18px;overflow-wrap:anywhere">'
        f'{eyebrow}<p style="{HEADING_FONT}font-size:19px;font-weight:700;'
        f'line-height:26px;margin:0 0 12px"><a href="{safe_listing}" '
        f'style="color:#2b2620;text-decoration:none">{escape(title, quote=True)}</a></p>'
        f"<table {TABLE}>{fact_rows}</table>{summary_html}{skills_html}"
        f'<table {TABLE} style="margin-top:14px"><tr><td bgcolor="#5e2b47" '
        'style="border-radius:6px;mso-padding-alt:10px 16px">'
        f'<a href="{safe_listing}" style="background-color:#5e2b47;border:1px solid #5e2b47;'
        f"border-radius:6px;color:#ffffff;display:inline-block;{BODY_FONT}font-size:14px;"
        'font-weight:700;line-height:20px;padding:10px 16px;text-decoration:none">'
        f"View details</a></td></tr></table>{apply_html}</td></tr></table>"
    )
    lines = [f"{category}: {title}" if category else title]
    lines.extend(f"{label}: {value}" for label, value in facts)
    if summary:
        lines.append(summary)
    if skills:
        lines.append("Skills: " + ", ".join(skills[:6]))
    if overlap:
        lines.append(overlap)
    lines.append(f"View details: {listing_url}")
    if apply_url:
        lines.append(f"Apply on the original listing: {apply_url}")
    return html, "\n".join(lines)


def render_company_alert(
    *,
    display_name: str | None,
    user_skills: list[dict] | None,
    groups: list[CompanyAlertGroup],
    unsub_url: str,
    now: datetime,
) -> tuple[str, str, str]:
    """Returns (subject, html, text)."""
    groups = [group for group in groups if group.opportunities]
    if not groups:
        raise ValueError("A company alert needs at least one opportunity")
    site_url = get_settings().site_url.rstrip("/")
    opportunities = [opportunity for group in groups for opportunity in group.opportunities]
    count = len(opportunities)
    noun = (
        "roles"
        if all(o.category in {"internship", "job"} for o in opportunities)
        else "opportunities"
    )
    company_name = _collapse_whitespace(groups[0].company.name)
    if count == 1:
        subject = f"New at {company_name}: {_collapse_whitespace(opportunities[0].title)}"
    elif len(groups) == 1:
        subject = f"{count} new {noun} at {company_name}"
    else:
        more = len(groups) - 1
        subject = (
            f"{count} new {noun} at {company_name} and {more} more "
            f"{'company' if more == 1 else 'companies'}"
        )
    subject = _shorten(subject, 90)
    title = subject
    if count == 1 and len(groups[0].roles) == 1:
        domain = ROLE_LABELS[groups[0].roles[0]]
        singular = "role" if noun == "roles" else "opportunity"
        title = f"New {domain} {singular} at {company_name}"
    name = _collapse_whitespace(display_name)
    greeting = f"Hi {name.split()[0]}," if name and "@" not in name else "Hi,"
    if count == 1:
        singular = "role" if noun == "roles" else "opportunity"
        intro = (
            f"{greeting} {company_name} just posted a {singular} that matches "
            "what you asked us to watch for."
        )
    else:
        intro = f"{greeting} {count} new {noun} match the companies and domains you picked."
    skill_names = {
        skill["name"].strip().casefold()
        for skill in (user_skills or [])
        if isinstance(skill, dict) and isinstance(skill.get("name"), str)
    }
    ordered = [
        sorted(
            group.opportunities,
            key=lambda o: (
                o.category != "internship",
                re.search(SENIOR_TITLE_PATTERN, o.title or "", re.IGNORECASE) is not None,
                -_utc(o.first_seen_at or now).timestamp(),
            ),
        )
        for group in groups
    ]
    # Round-robin allocation keeps a busy company from taking another's first card.
    allocations = [0] * len(groups)
    remaining = 8
    for _ in range(4):
        for index, items in enumerate(ordered):
            if remaining and allocations[index] < len(items):
                allocations[index] += 1
                remaining -= 1
    html_parts = []
    text_parts = [intro]
    for group, items, allocation in zip(groups, ordered, allocations):
        html_parts.append(_company_header(group))
        text_parts.append(
            f"{_collapse_whitespace(group.company.name)}\nFollowing for {_domains(group.roles)}"
        )
        for opportunity in items[:allocation]:
            card_html, card_text = _card(opportunity, skill_names, site_url, now)
            html_parts.append(card_html)
            text_parts.append(card_text)
        more = len(items) - allocation
        if more:
            more_noun = ("role" if noun == "roles" else "opportunity") if more == 1 else noun
            more_label = (
                f"+{more} more new {more_noun} at {_collapse_whitespace(group.company.name)}"
            )
            company_url = f"{site_url}/companies/{quote(group.company.slug, safe='')}"
            html_parts.append(
                f'<p style="margin:10px 0 22px"><a href="{escape(company_url, quote=True)}" '
                f'style="color:#5e2b47;{BODY_FONT}font-size:13px;line-height:20px;'
                f'text-decoration:underline">{escape(more_label, quote=True)}</a></p>'
            )
            text_parts.append(f"{more_label}: {company_url}")
    names = [_collapse_whitespace(group.company.name) for group in groups]
    companies = (
        f"{', '.join(names[:3])} and {len(names) - 3} more"
        if len(names) > 3
        else _join_names(names)
    )
    footer_note = (
        f"You get this because you follow {companies} on Aspirova. "
        "Change your companies and domains under Manage email preferences."
    )
    html = email_layout(
        title=title,
        intro_html=(
            f'<p style="color:#6b6259;{BODY_FONT}font-size:15px;line-height:22px;'
            f'margin:0 0 20px">{escape(intro, quote=True)}</p>'
        ),
        body_html="".join(html_parts),
        footer_note=footer_note,
        unsubscribe_url=unsub_url,
    )
    text_parts.extend([footer_note, text_footer(unsub_url)])
    return subject, html, "\n\n".join(text_parts)
