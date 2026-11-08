"""Render student emails and Supabase dashboard templates without a DB or transport.

Run from backend with uv run python -m scripts.render_email_previews --out <dir>.
"""

import argparse
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path

from core import models
from core.config import get_settings
from core.email_components import BODY_FONT, MUTED
from core.email_templates import email_layout, subscription_layout, text_footer
from pipeline.company_alert_email import CompanyAlertGroup, render_company_alert
from pipeline.notifications import (
    COMBINED_DIGEST_SUBJECT,
    DAILY_DIGEST_SUBJECT,
    HACKATHON_DIGEST_SUBJECT,
    _render_closing_soon,
    _render_closing_soon_text,
    _render_digest,
)
from pipeline.saved_search_alerts import _render_saved_search_alert
from pipeline.weekly_report import WeeklyReportData, _render_weekly_report

NOW = datetime(2026, 11, 8, 9, tzinfo=timezone.utc)
UNSUBSCRIBE = "https://aspirova-api.onrender.com/notifications/unsubscribe?token=PREVIEW"
AUTH_SITE = "https://www.aspirova.org"
CONFIRMATION_TOKEN = "{{ .ConfirmationURL }}"
AUTH_RECEIVING = (
    "You're receiving this because this address was used on Aspirova. "
    "If that wasn't you, you can ignore this email."
)
AUTH_VARIANTS = [
    (
        "confirm-signup",
        "Confirm your email",
        "Confirm email",
        "Confirm your email to get started on Aspirova.",
    ),
    (
        "reset-password",
        "Reset your password",
        "Reset password",
        "Use the link below to choose a new password.",
    ),
    (
        "magic-link",
        "Your sign-in link",
        "Sign in",
        "Use this link to sign in to your Aspirova account.",
    ),
    (
        "change-email",
        "Confirm your new email",
        "Confirm change",
        "Confirm {{ .NewEmail }} as your new Aspirova email address.",
    ),
]
AUTH_README = """# Supabase Auth email templates

Paste each HTML file into Supabase under Authentication → Emails → Templates.
The files use the Aspirova shared transactional shell and the fixed public site
https://www.aspirova.org for the logo and footer links.

| File | Dashboard template | Suggested subject |
| --- | --- | --- |
| confirm-signup.html | Confirm signup | Confirm your email |
| reset-password.html | Reset password | Reset your password |
| magic-link.html | Magic link | Your sign-in link |
| change-email.html | Change email address | Confirm your new email |

If a current template uses a custom link, such as a token_hash flow, keep that
link in both the button and fallback text instead of replacing it with
{{ .ConfirmationURL }}. Preserve the current authentication redirect behaviour.
These are dashboard handover files. The preview script only writes files.
"""


def sample_opportunities(
    count: int, *, categories: list[str] | None = None, numbered: bool = True
) -> list[models.Opportunity]:
    """Transient ORM objects only. No engine, session or persisted identifiers.

    numbered=True suffixes each title with its index so tests can locate every card;
    the founder-facing previews pass numbered=False for realistic titles.
    """
    companies = [
        models.Company(name="Google", slug="google", domain="google.com"),
        models.Company(
            name="Razorpay",
            slug="razorpay",
            domain="razorpay.com",
            logo_url="https://razorpay.com/favicon.png",
        ),
        models.Company(name="Campus Loom", slug="campus-loom"),
    ]
    categories = categories or ["internship", "job", "hackathon", "competition", "fellowship"]
    titles = {
        "internship": [
            "Software Engineering Intern",
            "Data Analyst Intern",
            "Product Design Intern",
            "Backend Developer Intern",
        ],
        "job": ["Graduate Platform Engineer", "Associate Data Scientist", "SDE I, Payments"],
        "hackathon": ["Campus Build Sprint", "Open Source Weekend Hack", "FinTech Ideathon"],
        "competition": ["Design for Tomorrow Challenge", "Case Study Championship"],
        "fellowship": ["Student Research Fellowship"],
        "scholarship": ["Future Makers Scholarship"],
    }
    opportunities = []
    per_category: dict[str, int] = {}
    for index in range(count):
        category = categories[index % len(categories)]
        options = titles[category]
        title = options[per_category.get(category, 0) % len(options)]
        per_category[category] = per_category.get(category, 0) + 1
        if numbered:
            title = f"{title} {index + 1}"
        meta = {
            "duration_months": 6,
            "offers_ppo": category == "internship",
            "compensation": {
                "min": 15000 if category == "internship" else 1200000,
                "max": 15000 if category == "internship" else 1800000,
                "currency": "INR",
                "period": "month" if category == "internship" else "year",
            },
        }
        if category in {"hackathon", "competition"}:
            meta = {"prize_text": "₹2,00,000 prize pool and mentoring"}
        opportunities.append(
            models.Opportunity(
                id=index + 1,
                title=title,
                slug=f"preview-{category}-{index + 1}",
                category=category,
                company=companies[index % len(companies)],
                apply_url=f"https://example.com/careers/preview-{index + 1}",
                location=["Bengaluru, Karnataka, India", "Pune", "Remote"][index % 3],
                is_remote=index % 3 == 2,
                meta=meta,
                deadline=NOW + timedelta(days=index % 12),
                deadline_confidence="inferred" if index == 2 else "explicit",
                first_seen_at=NOW - timedelta(hours=index),
                summary=(
                    "Build reliable tools with a small team, learn from experienced mentors, "
                    "and ship improvements used by students across India. Work on real systems "
                    "with clear project goals and regular feedback."
                ),
                skills=["Python", "SQL", "Git", "Linux", "TypeScript", "Communication"],
            )
        )
    return opportunities


def auth_templates() -> dict[str, tuple[str, str, str]]:
    templates = {}
    # The placeholder is validated by the ordinary HTTP-only shell. Replace only
    # this developer-owned constant after rendering so Go tokens survive literally.
    placeholder = "https://email-template.invalid/confirmation"
    for slug, title, label, message in AUTH_VARIANTS:
        fallback = (
            f'<p class="em-muted" style="color:{MUTED};font-size:12px;line-height:18px;'
            'overflow-wrap:anywhere">Button not working? Paste this link into your browser:<br>'
            f"{CONFIRMATION_TOKEN}</p>"
        )
        html = email_layout(
            title=title,
            kind_label="Account",
            variant="transactional",
            greeting="Hi there,",
            summary=message,
            preheader=message,
            body_html="",
            cta_label=label,
            cta_url=placeholder,
            receiving_note=AUTH_RECEIVING,
            site_url=AUTH_SITE,
            show_preferences=False,
        )
        # Keep fallback directly beneath the button, inside the white card.
        marker = '</td></tr><tr><td class="em-muted em-page"'
        html = html.replace(marker, fallback + marker, 1).replace(placeholder, CONFIRMATION_TOKEN)
        text = (
            f"Hi there,\n\n{message}\n\n{label}: {CONFIRMATION_TOKEN}\n\n"
            f"Button not working? Paste this link into your browser:\n{CONFIRMATION_TOKEN}\n\n"
            f"{AUTH_RECEIVING}\n"
            f"Aspirova · Every opportunity. One place. · aspirova.org ({AUTH_SITE})"
        )
        templates[slug] = (title, html, text)
    return templates


def preview_variants() -> dict[str, tuple[str, str, str]]:
    variants = {}
    user = models.User(display_name="Priya Sharma", email="priya@example.com")
    daily = sample_opportunities(
        5, categories=["internship", "internship", "job", "job", "job"], numbered=False
    )
    hackathons = sample_opportunities(5, categories=["hackathon", "competition"], numbered=False)
    hackathons[3].company = models.Company(
        name="Microsoft", slug="microsoft", domain="microsoft.com"
    )
    hackathons[4].company = models.Company(name="Zomato", slug="zomato", domain="zomato.com")
    for opportunity, days in zip(hackathons, [9, 2, 21, 5, 14]):
        opportunity.id += 100
        opportunity.deadline = NOW + timedelta(days=days)
        opportunity.deadline_confidence = "explicit"
    for slug, subject, jobs, events in [
        ("daily-digest", COMBINED_DIGEST_SUBJECT, daily, hackathons),
        ("daily-digest-jobs-only", DAILY_DIGEST_SUBJECT, daily, []),
        ("daily-digest-hackathons-only", HACKATHON_DIGEST_SUBJECT, [], hackathons),
    ]:
        variants[slug] = (
            subject,
            *_render_digest(
                jobs, UNSUBSCRIBE, display_name=user.display_name, now=NOW, hackathons=events
            ),
        )
    roles = sample_opportunities(12, categories=["internship", "job"], numbered=False)
    groups = [
        CompanyAlertGroup(roles[index].company, ["software", "data"], roles[index::3])
        for index in range(3)
    ]
    variants["company-alert"] = render_company_alert(
        display_name=user.display_name,
        user_skills=[{"name": "Python"}, {"name": "SQL"}],
        groups=groups,
        unsub_url=UNSUBSCRIBE,
        now=NOW,
    )
    closing = sample_opportunities(
        3, categories=["internship", "job", "fellowship"], numbered=False
    )
    for opportunity, days in zip(closing, [0, 1, 3]):
        opportunity.deadline = NOW + timedelta(days=days)
    subject, html = _render_closing_soon(closing, NOW, display_name=user.display_name)
    variants["closing-soon"] = (
        subject,
        html,
        _render_closing_soon_text(closing, now=NOW, display_name=user.display_name),
    )
    saved = models.SavedSearch(name="Early-career roles in India", params={"country": "IN"})
    variants["saved-search"] = (
        "7 new matches for your saved search",
        *_render_saved_search_alert(
            saved, sample_opportunities(7, numbered=False), display_name=user.display_name, now=NOW
        ),
    )
    weekly = sample_opportunities(5, numbered=False)
    variants["weekly-report"] = (
        "Your Aspirova weekly career report",
        *_render_weekly_report(
            user,
            WeeklyReportData(
                dream_company_matches=weekly[:3],
                closing_soon=weekly[3:],
                hidden_opportunities=[],
                intro=(
                    "Start with roles that use your Python and SQL skills, "
                    "and review the earliest deadlines first."
                ),
            ),
            now=NOW,
        ),
    )
    site = get_settings().site_url.rstrip("/")
    for active, slug, title in [
        (True, "payment-active", "Your Aspirova Pro is active"),
        (False, "payment-failed", "We couldn't process your payment"),
    ]:
        text = (
            "Your Pro Monthly plan is now active.\n\n"
            "Your Pro features are ready whenever you are.\n"
            f"Open Aspirova: {site}\n\n"
            if active
            else "We couldn't process the payment for your Pro Monthly plan.\n\n"
            "Please update your payment method. Pro features are paused until your payment "
            "succeeds.\n"
            f"View your subscription: {site}/account?section=subscription\n\n"
        )
        variants[slug] = (
            title,
            subscription_layout(
                plan_name="Pro Monthly", active=active, display_name=user.display_name
            ),
            text + text_footer(variant="transactional"),
        )
    variants.update(auth_templates())
    return variants


def main(argv: list[str] | None = None, *, auth_out: Path | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    variants = preview_variants()
    gallery = []
    for slug, (subject, html, text) in variants.items():
        (args.out / f"{slug}.html").write_text(html, encoding="utf-8")
        (args.out / f"{slug}.txt").write_text(text, encoding="utf-8")
        gallery.append(
            f'<h2>{escape(subject, quote=True)}</h2><p><a href="{slug}.html">{slug}</a></p>'
            f'<table role="presentation"><tr><td valign="top"><iframe title="{slug} desktop" '
            f'src="{slug}.html" width="600" height="900"></iframe></td>'
            f'<td valign="top"><iframe title="{slug} phone" src="{slug}.html" '
            'width="375" height="900"></iframe></td></tr></table>'
        )
    (args.out / "index.html").write_text(
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        "<title>Aspirova email previews</title></head>"
        f'<body style="{BODY_FONT}background-color:#f1f4f9;padding:24px">'
        "<h1>Aspirova email previews</h1>" + "".join(gallery) + "</body></html>",
        encoding="utf-8",
    )
    auth_dir = (
        auth_out
        if auth_out is not None
        else Path(__file__).resolve().parents[2] / "docs/email/supabase-auth"
    )
    auth_dir.mkdir(parents=True, exist_ok=True)
    for slug, (_, html, _) in auth_templates().items():
        (auth_dir / f"{slug}.html").write_text(html, encoding="utf-8")
    (auth_dir / "README.md").write_text(AUTH_README, encoding="utf-8")


if __name__ == "__main__":
    main()
