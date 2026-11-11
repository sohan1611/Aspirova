"""Public email examples rendered with fictional, transient data only."""

from datetime import datetime, timedelta, timezone

from core import models
from pipeline.company_alert_email import CompanyAlertGroup, render_company_alert
from pipeline.weekly_report import WeeklyReportData, _render_weekly_report


def _today() -> datetime:
    """Sample dates follow today, so the public example never shows a past deadline."""
    return datetime.now(timezone.utc).replace(hour=9, minute=0, second=0, microsecond=0)


UNSUBSCRIBE = "https://www.aspirova.org/account?section=notifications"


def _sample_opportunities(now: datetime) -> list[models.Opportunity]:
    companies = [
        models.Company(name="Northwind Labs", slug="northwind-labs", domain=None, logo_url=None),
        models.Company(name="Campus Loom", slug="campus-loom", domain=None, logo_url=None),
        models.Company(
            name="Brightpath Analytics", slug="brightpath-analytics", domain=None, logo_url=None
        ),
    ]
    return [
        models.Opportunity(
            id=index + 1,
            title=title,
            slug=f"sample-role-{index + 1}",
            category=category,
            company=companies[index % len(companies)],
            apply_url=f"https://example.com/careers/sample-role-{index + 1}",
            location="Bengaluru, India" if index % 2 == 0 else "Remote",
            is_remote=index % 2 == 1,
            meta={},
            deadline=now + timedelta(days=index + 2),
            deadline_confidence="explicit",
            first_seen_at=now - timedelta(hours=index),
            summary=(
                "Build useful tools with a small team, learn from mentors, "
                "and work on projects with clear goals and regular feedback."
            ),
            skills=["Python", "SQL", "Git"],
        )
        for index, (title, category) in enumerate(
            [
                ("Software Engineering Intern", "internship"),
                ("Graduate Platform Engineer", "job"),
                ("Data Analyst Intern", "internship"),
                ("Backend Developer Intern", "internship"),
                ("Associate Data Scientist", "job"),
            ]
        )
    ]


def render_sample(kind: str, *, now: datetime | None = None) -> tuple[str, str] | None:
    """Return a real template's subject and HTML without DB, AI or transport calls."""
    if kind not in {"company-alert", "weekly-report"}:
        return None

    now = now or _today()
    user = models.User(display_name=None)
    opportunities = _sample_opportunities(now)
    if kind == "company-alert":
        groups = [
            CompanyAlertGroup(
                opportunities[index].company, ["software", "data"], opportunities[index::3]
            )
            for index in range(3)
        ]
        subject, html, _text = render_company_alert(
            display_name=user.display_name,
            user_skills=[{"name": "Python"}, {"name": "SQL"}],
            groups=groups,
            unsub_url=UNSUBSCRIBE,
            now=now,
        )
        return subject, html

    html, _text = _render_weekly_report(
        user,
        WeeklyReportData(
            dream_company_matches=opportunities[:3],
            closing_soon=opportunities[3:],
            hidden_opportunities=[],
            # No intro: it renders as an "AI-assisted overview", and AI is deferred
            # (README 2026-11-03: Pro sells only what runs), so a public sample must
            # not show one.
            intro=None,
        ),
        unsub_url=UNSUBSCRIBE,
        now=now,
    )
    return "Your Aspirova weekly career report", html
