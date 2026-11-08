"""Deterministic, database-free company alert email rendering."""

import re
from dataclasses import dataclass
from datetime import datetime
from html import escape
from urllib.parse import quote

from api.filters import SENIOR_TITLE_PATTERN
from core import models
from core.config import get_settings
from core.email_components import (
    BODY_FONT,
    BRAND,
    HEADING_FONT,
    INK,
    MUTED,
    TABLE,
    _collapse_whitespace,
    _http_url,
    _shorten,
    _utc,
    greeting as email_greeting,
    logo_tile,
    opportunity_card,
    pill,
)
from core.email_templates import email_layout, text_footer

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


@dataclass(frozen=True)
class CompanyAlertGroup:
    company: models.Company
    roles: list[str]
    opportunities: list[models.Opportunity]


def _join_names(names: list[str]) -> str:
    return " and ".join(names) if len(names) < 3 else ", ".join(names[:-1]) + " and " + names[-1]


def _domains(roles: list[str]) -> str:
    return (
        _join_names([ROLE_LABELS[role] for role in roles if role in ROLE_LABELS]) or "all domains"
    )


def _company_header(group: CompanyAlertGroup) -> str:
    return (
        f'<table {TABLE} width="100%" style="margin:24px 0 14px"><tr>'
        f'{logo_tile(group.company)}<td style="padding-left:12px">'
        f'<p class="em-ink" style="color:{INK};{HEADING_FONT}font-size:19px;'
        'font-weight:700;line-height:25px;margin:0">'
        f"{escape(_collapse_whitespace(group.company.name), quote=True)}</p>"
        f'<p class="em-muted" style="color:{MUTED};font-size:12px;line-height:18px;margin:3px 0 0">'
        f"Following for {escape(_domains(group.roles), quote=True)}</p></td></tr></table>"
    )


def _card(
    opportunity: models.Opportunity,
    skill_names: set[str],
    site_url: str,
    now: datetime,
    *,
    company: models.Company | None = None,
) -> tuple[str, str]:
    listing = f"{site_url}/opportunity/{quote(opportunity.slug, safe='')}"
    title = _collapse_whitespace(opportunity.title)
    summary = _collapse_whitespace(opportunity.summary)
    summary = _shorten(summary, 220) if summary.casefold() != title.casefold() else ""
    summary_html = (
        f'<p class="em-muted" style="color:{MUTED};font-size:14px;line-height:21px;margin:12px 0">'
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
    chips = "".join(
        pill(
            skill,
            BRAND if skill.casefold() in skill_names else "#eef1f7",
            "#ffffff" if skill.casefold() in skill_names else MUTED,
        )
        for skill in skills[:6]
    )
    overlap = ""
    if matched_count:
        noun = "skill" if len(skills) == 1 else "skills"
        overlap = f"You have {matched_count} of {len(skills)} {noun} listed"
    skills_html = f'<p style="margin:12px 0 0">{chips}</p>' if chips else ""
    if overlap:
        skills_html += (
            f'<p class="em-link" style="color:{BRAND};font-size:12px;'
            'line-height:18px;margin:0 0 12px">'
            f"{overlap}</p>"
        )
    apply = _http_url(opportunity.apply_url)
    html, text = opportunity_card(
        opportunity,
        now=now,
        button_url=listing,
        deadline_policy="explicit_only",
        extra_html=summary_html + skills_html,
        secondary_link=("Apply on the original listing", apply) if apply else None,
        company=company,
    )
    extra_text = [summary] if summary else []
    if skills:
        extra_text.append("Skills: " + ", ".join(skills[:6]))
    if overlap:
        extra_text.append(overlap)
    return html, text + ("\n" + "\n".join(extra_text) if extra_text else "")


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
    site_url = (_http_url(get_settings().site_url) or "https://www.aspirova.org").rstrip("/")
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
    greeting = email_greeting(name)
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
            card_html, card_text = _card(
                opportunity, skill_names, site_url, now, company=group.company
            )
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
                '<p style="margin:10px 0 22px"><a class="em-link" '
                f'href="{escape(company_url, quote=True)}" '
                f'style="color:#0b4fd6;{BODY_FONT}font-size:13px;line-height:20px;'
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
        kind_label="Company alert",
        greeting=greeting,
        summary=intro[len(greeting) + 1 :],
        preheader=intro[len(greeting) + 1 :],
        cta_label="See all on Aspirova",
        cta_url=f"{site_url}/companies",
        body_html="".join(html_parts),
        footer_note=footer_note,
        unsubscribe_url=unsub_url,
    )
    text_parts.extend([footer_note, text_footer(unsub_url)])
    return subject, html, "\n\n".join(text_parts)
