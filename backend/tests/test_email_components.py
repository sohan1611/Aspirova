"""Pure rendering, client-safety and clipping-budget regression tests."""

import builtins
import importlib
from datetime import datetime, timedelta, timezone
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import Mock
from uuid import UUID

import pytest
import sqlalchemy
from sqlalchemy import orm

from core import models
from core.config import get_settings
from core.email_components import (
    _facts,
    button,
    deadline_badge,
    greeting,
    listing_url,
    logo_tile,
    opportunity_card,
    type_tag,
)
from core.email_templates import email_layout, text_footer
from pipeline.company_alert_email import CompanyAlertGroup, render_company_alert
from pipeline.notifications import (
    _render_closing_soon,
    _render_closing_soon_text,
    _render_digest,
)
from pipeline.saved_search_alerts import _render_saved_search_alert
from pipeline.weekly_report import WeeklyReportData, _render_weekly_report
from scripts import render_email_previews as previews

NOW = previews.NOW


@pytest.fixture(scope="session", autouse=True)
def _purge_isolation_test_residue():
    """Override the global DB cleanup so this module remains entirely DB-free."""
    yield


class Markup(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.tags = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def opportunity(**kwargs):
    item = previews.sample_opportunities(1)[0]
    for key, value in kwargs.items():
        setattr(item, key, value)
    return item


def test_logo_source_order_and_initials():
    company = models.Company(
        name="Goldman Sachs",
        slug="gs",
        domain="goldmansachs.com",
        logo_url="https://cdn.test/gs.png",
    )
    html = logo_tile(company)
    assert 'src="https://cdn.test/gs.png"' in html
    assert 'alt="GS"' in html
    assert "google.com/s2" not in html
    company.logo_url = "javascript:bad()"
    assert "domain=goldmansachs.com&amp;sz=64" in logo_tile(company)
    assert "javascript:" not in logo_tile(company)
    company.logo_url = None
    assert "domain=goldmansachs.com&amp;sz=64" in logo_tile(company)
    company.domain = None
    html = logo_tile(company)
    assert "<img" not in html
    assert ">GS</td>" in html
    assert html == logo_tile(company)
    assert ">?</td>" in logo_tile(None)
    html, text = opportunity_card(
        opportunity(company=None), now=NOW, button_url="https://example.test", deadline_policy="any"
    )
    assert "Unknown" in html and "Unknown" in text


@pytest.mark.parametrize(
    "days,label,bg",
    [
        (-1, "", ""),
        (0, "Closes today", "#fdecea"),
        (1, "Closes tomorrow", "#fdecea"),
        (2, "Closes in 2 days", "#fdecea"),
        (3, "Closes in 3 days", "#fdecea"),
        (4, "Closes in 4 days", "#fff4e5"),
        (7, "Closes in 7 days", "#fff4e5"),
        (8, "Apply by 16 Nov", "#eef1f7"),
    ],
)
def test_deadline_boundaries(days, label, bg):
    item = opportunity(deadline=NOW + timedelta(days=days), deadline_confidence="explicit")
    for policy in ["explicit_only", "any"]:
        html = deadline_badge(item, NOW, policy=policy)
        if days < 0:
            assert html == ""
        else:
            assert label in html and bg in html


@pytest.mark.parametrize("confidence,suffix", [("inferred", " (est.)"), ("unknown", " · verify")])
def test_deadline_confidence_policy(confidence, suffix):
    item = opportunity(deadline=NOW + timedelta(days=3), deadline_confidence=confidence)
    assert deadline_badge(item, NOW, policy="explicit_only") == ""
    assert "Closes in 3 days" + suffix in deadline_badge(item, NOW, policy="any")
    item.deadline = None
    assert deadline_badge(item, NOW, policy="any") == ""


def test_deadlines_use_utc_calendar_dates_including_naive_legacy_dates():
    item = opportunity(deadline=datetime(2026, 11, 9), deadline_confidence="explicit")
    current = datetime(2026, 11, 8, 23, 59, tzinfo=timezone.utc)
    assert "Closes tomorrow" in deadline_badge(item, current, policy="any")
    item.deadline = datetime(2026, 11, 9, 1, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    assert "Closes today" in deadline_badge(item, current, policy="any")


@pytest.mark.parametrize(
    "category,label,bg,ink",
    [
        ("internship", "Internship", "#eaf0fd", "#0b3fae"),
        ("job", "Job", "#e8f5ee", "#1d6b40"),
        ("hackathon", "Hackathon", "#f3ecfd", "#6b2fb3"),
        ("competition", "Competition", "#f3ecfd", "#6b2fb3"),
        ("fellowship", "Fellowship", "#fff4e5", "#8a4b00"),
        ("scholarship", "Scholarship", "#fff4e5", "#8a4b00"),
        ("campus_programme", "Campus programme", "#eef1f7", "#1e293b"),
    ],
)
def test_type_tags_and_aa_contrast(category, label, bg, ink):
    html = type_tag(category)
    assert label in html and bg in html and ink in html

    def luminance(color):
        rgb = [int(color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in rgb]
        return sum(channel * weight for channel, weight in zip(linear, (0.2126, 0.7152, 0.0722)))

    assert (luminance(bg) + 0.05) / (luminance(ink) + 0.05) >= 4.5
    assert type_tag("") == type_tag(None) == ""


@pytest.mark.parametrize("url", ["javascript:alert(1)", "data:text/html,bad", "//evil.test", ""])
def test_unsafe_apply_url_falls_back_in_both_parts(url):
    item = opportunity(apply_url=url, slug='title /"<>')
    html, text = opportunity_card(item, now=NOW, button_url=url, deadline_policy="explicit_only")
    assert listing_url(item) in html and listing_url(item) in text
    assert "title%20%2F%22%3C%3E" in html
    for forbidden in ["javascript:", "data:text/html", "//evil.test"]:
        assert forbidden not in html + text


def test_card_escapes_all_untrusted_fields_and_secondary_urls():
    value = '<script>bad("x")</script> & role'
    item = opportunity(
        title=value,
        category=value,
        location=value,
        company=models.Company(
            name=value, slug="escape", logo_url='https://cdn.test/" onerror="bad'
        ),
    )
    html, text = opportunity_card(
        item,
        now=NOW,
        button_url='https://apply.test/?q="<x>&',
        deadline_policy="any",
        secondary_link=(value, "javascript:bad()"),
    )
    assert escape(value, quote=True) in html
    assert value not in html
    assert "<script>" not in html
    assert "q=&quot;&lt;x&gt;&amp;" in html
    assert "javascript:" not in html + text
    imgs = [attrs for tag, attrs in Markup(html).tags if tag == "img"]
    assert all("onerror" not in attrs for attrs in imgs)


def test_common_facts_and_prize_are_bounded():
    item = opportunity(
        location="Nepal, Japan, India, Bhutan, Sri Lanka",
        is_remote=True,
        meta={"compensation": {"unpaid": True}, "duration_months": 6, "offers_ppo": True},
    )
    facts = dict(_facts(item))
    assert facts == {
        "Where": "India, Nepal, Japan and 2 more · Remote",
        "Pay": "Unpaid",
        "Duration": "6 months",
    }
    html, text = opportunity_card(item, now=NOW, button_url=item.apply_url, deadline_policy="any")
    assert "Job offer possible" in html + text
    item.category = "hackathon"
    item.meta = {"prize_text": "Inventive projects and mentoring " * 8}
    prize = dict(_facts(item))["Prize"]
    assert prize.startswith("Prize: ") and len(prize) <= 47 and prize.endswith("…")
    item.location = "LOCATION"
    item.is_remote = False
    assert "Where" not in dict(_facts(item))


@pytest.mark.parametrize(
    "name,expected",
    [("Priya Sharma", "Hi Priya,"), (None, "Hi there,"), ("a@b.test", "Hi there,")],
)
def test_first_name_greeting(name, expected):
    assert greeting(name) == expected


def test_shell_preheader_fallback_and_inline_base_styles():
    html = email_layout(
        title='A <title> "quoted"', intro_html="<p>Intro &amp; details</p>", body_html=""
    )
    assert "<title>A &lt;title&gt; &quot;quoted&quot;</title>" in html
    assert "Intro &amp; details&#847;" in html
    html = email_layout(
        title="Test", intro_html="Ignored preview", body_html="", preheader="Chosen preview"
    )
    assert "Chosen preview&#847;" in html
    assert html.index("Chosen preview") < html.index('<table role="presentation"')
    assert "display:none;max-height:0" in html and "mso-hide:all" in html
    assert html.count("&#847;&zwnj;&nbsp;") == 40
    assert 'name="color-scheme" content="light dark"' in html
    assert "<!--[if mso]>" in html and "[data-ogsc]" in html
    assert 'bgcolor="#0b4fd6"' in html and 'bgcolor="#f1f4f9"' in html
    assert 'width="600" style="width:100%;max-width:600px"' in html
    assert 'href="javascript:' not in button("Bad", "javascript:bad()")


def test_all_preview_variants_are_client_safe_and_have_correct_unsubscribe_scope():
    variants = previews.preview_variants()
    assert len(variants) == 13
    for slug, (_, html, _) in variants.items():
        tags = Markup(html).tags
        assert all(attrs.get("role") == "presentation" for tag, attrs in tags if tag == "table")
        images = [attrs for tag, attrs in tags if tag == "img"]
        assert images and images[0]["alt"] == "Aspirova"
        assert all(
            attrs.get("alt") and attrs.get("width") and attrs.get("height") for attrs in images
        )
        for forbidden in [
            "<link",
            "@import",
            "@font-face",
            "<script",
            "<div",
            "<form",
            "<svg",
            "display:flex",
            "display:grid",
            "position:",
            "background-image",
        ]:
            assert forbidden not in html.lower()
        # Auth emails have no preference to manage; every other email links to it.
        assert ("Manage email preferences" in html) == (slug not in previews.auth_templates())
        assert ("Opportunities are gathered" in html) == (
            slug not in previews.auth_templates() and not slug.startswith("payment-")
        )
        assert (">Unsubscribe</a>" in html) == (
            slug.startswith("daily-digest")
            or slug in {"company-alert", "closing-soon", "saved-search", "weekly-report"}
        )
        if slug.startswith("payment-"):
            assert "This is a service email about your Aspirova account." in html


def test_largest_realistic_emails_stay_below_90kb():
    items = previews.sample_opportunities(15)
    user = models.User(display_name="Priya Sharma")
    saved = models.SavedSearch(
        name="Engineering roles and student opportunities", params={"country": "IN"}
    )
    company_items = previews.sample_opportunities(12, categories=["internship", "job"])
    for item in company_items:
        item.summary = "Build thoughtful student tools and learn from experienced mentors. " * 15
    groups = [
        CompanyAlertGroup(company_items[i].company, ["software", "data"], company_items[i::3])
        for i in range(3)
    ]
    picks = previews.sample_opportunities(5, categories=["hackathon", "competition"])
    for item in picks:
        item.id += 100
    largest = {
        "daily": _render_digest(items[:5], previews.UNSUBSCRIBE, now=NOW, hackathons=picks)[0],
        "saved": _render_saved_search_alert(saved, items[:10], previews.UNSUBSCRIBE, now=NOW)[0],
        "company": render_company_alert(
            display_name=user.display_name,
            user_skills=[{"name": "Python"}],
            groups=groups,
            unsub_url=previews.UNSUBSCRIBE,
            now=NOW,
        )[1],
        "weekly": _render_weekly_report(
            user,
            WeeklyReportData(
                items[:5], items[5:10], items[10:], intro="Plan your applications. " * 25
            ),
            unsub_url=previews.UNSUBSCRIBE,
            now=NOW,
        )[0],
        "hackathon-only": _render_digest(
            [],
            previews.UNSUBSCRIBE,
            now=NOW,
            hackathons=previews.sample_opportunities(8, categories=["hackathon", "competition"]),
        )[0],
        "closing": _render_closing_soon(items[:10], NOW, previews.UNSUBSCRIBE)[1],
    }
    assert largest["company"].count(">View &amp; Apply</a>") == 8
    assert largest["weekly"].count(">View &amp; Apply</a>") == 15
    for name, html in largest.items():
        assert len(html.encode("utf-8")) < 90000, name
    for name, (_, html, _) in previews.preview_variants().items():
        assert len(html.encode("utf-8")) < 90000, name


def test_preview_main_writes_gallery_and_auth_files_without_db_or_transport(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Offline previews must never create an engine/session or send email")

    original_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name in {"resend", "core.email_client", "core.db", "api.payments", "api.deps"}:
            raise AssertionError(f"Offline preview imported {name}")
        if name == "core" and {"email_client", "db"}.intersection(fromlist or ()):
            raise AssertionError("Offline preview imported a core DB/transport module")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(sqlalchemy, "create_engine", forbidden)
    monkeypatch.setattr(orm.Session, "__init__", forbidden)
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    # Reload the rendering imports too so a cached send module cannot conceal a regression.
    for name in [
        "pipeline.notifications",
        "pipeline.saved_search_alerts",
        "pipeline.weekly_report",
    ]:
        importlib.reload(importlib.import_module(name))
    importlib.reload(previews)
    output = tmp_path / "gallery"
    auth_dir = tmp_path / "auth"
    previews.main(["--out", str(output)], auth_out=auth_dir)
    index = (output / "index.html").read_text(encoding="utf-8")
    for slug in previews.preview_variants():
        assert (output / f"{slug}.html").exists()
        assert (output / f"{slug}.txt").exists()
        assert index.count(f'src="{slug}.html"') == 2
    assert index.count('width="600"') == index.count('width="375"') == 13
    assert (auth_dir / "README.md").exists()
    for slug in previews.auth_templates():
        assert (auth_dir / f"{slug}.html").exists()


def test_auth_tokens_hardcoded_site_and_committed_templates_match():
    directory = Path(__file__).resolve().parents[2] / "docs/email/supabase-auth"
    for slug, (_, html, text) in previews.auth_templates().items():
        assert 'href="{{ .ConfirmationURL }}"' in html
        assert html.count("{{ .ConfirmationURL }}") == 2
        assert "{{ .ConfirmationURL }}" in text
        assert "{{ .SiteURL }}" not in html
        assert 'src="https://www.aspirova.org/logo.png"' in html
        assert escape(previews.AUTH_RECEIVING, quote=True) in html
        assert "Button not working? Paste this link into your browser:" in html
        assert (directory / f"{slug}.html").read_text(encoding="utf-8") == html
    assert "{{ .NewEmail }}" in previews.auth_templates()["change-email"][1]


def test_group_order_input_stability_and_existing_button_destinations():
    items = previews.sample_opportunities(
        7,
        categories=[
            "job",
            "internship",
            "hackathon",
            "scholarship",
            "competition",
            "internship",
            "job",
        ],
    )
    html, text = _render_digest(items, previews.UNSUBSCRIBE, now=NOW)
    assert f" — {items[1].title} at {items[1].company.name}&#847;" in html
    headings = [
        "Internships",
        "Jobs",
        "Fellowships &amp; scholarships",
        "Hackathons &amp; competitions",
    ]
    assert [html.index(h) for h in headings] == sorted(html.index(h) for h in headings)
    assert html.index(items[1].title) < html.index(items[5].title)
    for item in items:
        assert f'href="{item.apply_url}"' in html and item.apply_url in text
    assert f'href="{get_settings().site_url}"' in html
    item = opportunity(deadline=NOW + timedelta(days=1), deadline_confidence="inferred")
    subject, closing_html = _render_closing_soon([item], NOW)
    closing_text = _render_closing_soon_text([item], now=NOW)
    assert subject == f"'{item.title}' closes tomorrow"
    assert "09 Nov 2026" in closing_html and "09 Nov 2026" in closing_text
    assert item.apply_url in closing_text and f'href="{item.apply_url}"' in closing_html
    assert "(est.)" in closing_html
    assert "Unsubscribe" not in closing_html
    assert "Aspirova · Every opportunity. One place." in text_footer()


@pytest.mark.parametrize(
    "job_count,event_count,summary",
    [
        (1, 0, "1 new opportunity picked for you today"),
        (2, 0, "2 new opportunities picked for you today"),
        (0, 1, "1 hackathon or competition you can still enter"),
        (0, 2, "2 hackathons and competitions you can still enter"),
        (1, 1, "1 new opportunity and 1 hackathon picked for you today"),
        (2, 2, "2 new opportunities and 2 hackathons picked for you today"),
    ],
)
def test_merged_digest_summary_and_preheader(job_count, event_count, summary):
    jobs = previews.sample_opportunities(job_count, categories=["internship"])
    events = previews.sample_opportunities(event_count, categories=["hackathon"])
    for item in events:
        item.id += 100
    html, text = _render_digest(jobs, previews.UNSUBSCRIBE, now=NOW, hackathons=events)
    assert summary in text and summary + " — " in html
    assert "<title>Your daily opportunity digest</title>" in html
    assert ">Daily digest</td>" in html
    assert "See all on Aspirova</a>" in html


def test_merged_digest_moves_events_after_all_job_sections_without_duplicates():
    items = previews.sample_opportunities(
        6, categories=["fellowship", "hackathon", "internship", "competition", "job", "scholarship"]
    )
    items[5].category = "campus_programme"
    items[5].title = "Student Ambassador Programme"
    items[1].deadline_confidence = "inferred"
    events = previews.sample_opportunities(2, categories=["hackathon", "competition"])
    for item in events:
        item.id += 100
    html, text = _render_digest(
        items, previews.UNSUBSCRIBE, now=NOW, hackathons=[items[1], *events]
    )
    headings = [
        "Internships",
        "Jobs",
        "Fellowships &amp; scholarships",
        "More opportunities",
        "Hackathons &amp; competitions",
    ]
    assert [html.index(heading) for heading in headings] == sorted(html.index(h) for h in headings)
    assert html.count("Hackathons &amp; competitions") == 1
    assert text.count("Hackathons & competitions") == 1
    assert html.count(f'href="{listing_url(items[1])}"') == 1
    event_order = [items[1], items[3], *events]
    assert [html.index(o.title) for o in event_order] == sorted(
        html.index(o.title) for o in event_order
    )
    assert [text.index(o.title) for o in event_order] == sorted(
        text.index(o.title) for o in event_order
    )
    assert html.count(">View &amp; Enter</a>") == 4
    assert html.count(">View &amp; Apply</a>") == 4
    assert "4 new opportunities and 4 hackathons picked for you today" in html + text
    assert f'href="{get_settings().site_url.rstrip("/")}/competitions"' in html
    assert "Closes tomorrow (est.)" in html and "Closes tomorrow (est.)" in text
    assert "10 Nov 2026" not in html + text  # Inferred job deadline stays hidden.
    for item in items + events:
        assert f'href="{item.apply_url}"' in html and item.apply_url in text


@pytest.mark.parametrize("kind", ["closing_soon", "saved_search", "weekly_report"])
def test_missing_signing_key_omits_unsubscribe_links_and_headers(kind, monkeypatch):
    import pipeline.notifications as notifications
    import pipeline.saved_search_alerts as saved_alerts
    import pipeline.weekly_report as weekly_report

    monkeypatch.setattr("core.unsubscribe._signing_key", lambda: b"")
    user = models.User(
        id=UUID("00000000-0000-0000-0000-000000000123"),
        display_name="Priya Sharma",
        email="priya@example.com",
    )
    item = previews.sample_opportunities(1)[0]
    session = Mock()
    users = Mock()
    users.all.return_value = [user]
    send = Mock(return_value=True)
    if kind == "closing_soon":
        opportunities = Mock()
        opportunities.all.return_value = [item]
        session.scalars.side_effect = [users, opportunities]
        monkeypatch.setattr(notifications, "_already_alerted", lambda *args, **kwargs: False)
        monkeypatch.setattr(notifications, "_record_notification", Mock())
        monkeypatch.setattr(notifications, "send_email", send)
        notifications.send_closing_soon_alerts(session, now=NOW)
    elif kind == "saved_search":
        saved = models.SavedSearch(id=42, user_id=user.id, params={}, created_at=NOW)
        session.execute.return_value.all.return_value = [(saved, user)]
        session.scalars.return_value.unique.return_value.all.return_value = [item]
        monkeypatch.setattr(saved_alerts, "send_email", send)
        saved_alerts.send_saved_search_alerts(session, now=NOW)
    else:
        session.scalars.return_value = users
        monkeypatch.setattr(weekly_report, "can", lambda *args: True)
        monkeypatch.setattr(weekly_report, "_already_sent_this_week", lambda *args: False)
        monkeypatch.setattr(weekly_report, "_closing_soon_opportunities", lambda *args: [item])
        monkeypatch.setattr(weekly_report, "_recent_hidden_opportunities", lambda *args: [])
        monkeypatch.setattr(weekly_report, "_recent_dream_company_matches", lambda *args: [])
        monkeypatch.setattr(weekly_report, "_cohort_intro", lambda *args, **kwargs: None)
        monkeypatch.setattr(weekly_report, "_record_delivery", Mock())
        monkeypatch.setattr(weekly_report, "send_email", send)
        weekly_report.send_weekly_reports(session, now=NOW)
    send.assert_called_once()
    assert send.call_args.kwargs["headers"] == {}
    assert ">Unsubscribe</a>" not in send.call_args.args[2]
    assert 'href=""' not in send.call_args.args[2]
    assert "Unsubscribe from these emails:" not in send.call_args.args[3]
