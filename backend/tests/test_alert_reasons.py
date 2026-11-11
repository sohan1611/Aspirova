"""N-09: every opportunity email states the rule that triggered it.

Renders run on transient ORM objects only: no database, no transport.
"""

from datetime import datetime, timedelta, timezone
from html import unescape

from core import models
from pipeline.notifications import (
    _CLOSING_SOON_REASON,
    DigestHistory,
    _digest_since_label,
    _render_closing_soon,
    _render_closing_soon_text,
    _render_digest,
)
from pipeline.saved_search_alerts import _filter_summary, _render_saved_search_alert
from pipeline.weekly_report import WeeklyReportData, _render_weekly_report

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)


def _opportunity(index: int, category: str, *, deadline_days: int = 5) -> models.Opportunity:
    return models.Opportunity(
        id=index,
        title=f"{category.title()} listing {index}",
        slug=f"reason-{category}-{index}",
        category=category,
        company=models.Company(name=f"Northwind {index}", slug=f"northwind-{index}"),
        apply_url=f"https://example.com/apply/{index}",
        location="Remote",
        is_remote=True,
        deadline=NOW + timedelta(days=deadline_days),
        deadline_confidence="explicit",
        first_seen_at=NOW - timedelta(hours=index),
        meta={},
    )


def _both(html: str, text: str) -> str:
    return unescape(html) + "\n" + text


def test_generic_digest_states_its_window_and_selection_rule() -> None:
    jobs = [_opportunity(1, "internship"), _opportunity(2, "job")]
    events = [_opportunity(3, "hackathon")]

    html, text = _render_digest(
        jobs, hackathons=events, now=NOW, since_label="since your last digest on 10 Nov"
    )

    for rendered in (unescape(html), text):
        assert "You get this because the daily digest is on." in rendered
        assert (
            "The roles are the newest internships and jobs for students that we found "
            "since your last digest on 10 Nov, spread across companies." in rendered
        )
        assert "Follow companies to get their roles first." in rendered
        assert "none repeat from your digests of the last 7 days" in rendered
        assert "Change what you get under Manage email preferences." in rendered


def test_followed_company_digest_says_so() -> None:
    html, text = _render_digest(
        [_opportunity(1, "internship")],
        now=NOW,
        jobs_from_followed=True,
        since_label="in the last 24 hours",
    )

    combined = _both(html, text)
    assert "The roles are new at companies you follow, found in the last 24 hours." in combined
    assert "Follow companies to get their roles first." not in combined
    assert "hackathons and competitions are still open" not in combined


def test_hackathon_only_digest_explains_only_the_hackathons() -> None:
    html, text = _render_digest([], hackathons=[_opportunity(3, "hackathon")], now=NOW)

    combined = _both(html, text)
    assert "The roles are" not in combined
    assert "The hackathons and competitions are still open for entry" in combined


def test_since_label_matches_the_window_rule() -> None:
    no_history = DigestHistory(last_sent_at=None, recent_ids=frozenset())
    assert _digest_since_label(no_history, NOW - timedelta(hours=24), NOW) == (
        "in the last 24 hours"
    )

    last = datetime(2026, 11, 10, 12, 22, tzinfo=timezone.utc)
    recent = DigestHistory(last_sent_at=last, recent_ids=frozenset())
    assert _digest_since_label(recent, last, NOW) == "since your last digest on 10 Nov"

    # A digest five days ago is capped at the 72-hour window, so the label says 3 days.
    old = DigestHistory(last_sent_at=NOW - timedelta(days=5), recent_ids=frozenset())
    assert _digest_since_label(old, NOW - timedelta(hours=72), NOW) == "in the last 3 days"


def test_closing_soon_states_why_in_html_and_text() -> None:
    items = [_opportunity(1, "internship", deadline_days=2)]

    _subject, html = _render_closing_soon(items, NOW)
    text = _render_closing_soon_text(items, now=NOW)

    assert _CLOSING_SOON_REASON in unescape(html)
    assert _CLOSING_SOON_REASON in text
    assert "as its source states it" in _CLOSING_SOON_REASON


def test_named_saved_search_shows_its_exact_filters() -> None:
    saved = models.SavedSearch(name="My dream roles", params={"q": "data analyst", "country": "IN"})

    html, text = _render_saved_search_alert(saved, [_opportunity(1, "job")], now=NOW)

    filters = _filter_summary(saved.params)
    expected = (
        f"You get this because your saved search ‘My dream roles’ ({filters}) found "
        "listings that are new since its last alert."
    )
    assert expected in unescape(html) and expected in text
    assert "data analyst" in filters and "IN" in filters


def test_unnamed_saved_search_names_its_filters_once() -> None:
    saved = models.SavedSearch(name=None, params={"q": "designer"})

    html, text = _render_saved_search_alert(saved, [_opportunity(1, "job")], now=NOW)

    combined = _both(html, text)
    assert "your saved search ‘designer’ found listings that are new" in combined
    assert "‘designer’ (designer)" not in combined


def test_weekly_report_states_how_each_section_is_picked() -> None:
    user = models.User(display_name="Asha", email="asha@example.com")
    data = WeeklyReportData(
        dream_company_matches=[_opportunity(1, "internship")],
        closing_soon=[_opportunity(2, "job", deadline_days=3)],
        hidden_opportunities=[],
        intro=None,
    )

    html, text = _render_weekly_report(user, data, unsub_url=None, now=NOW)

    combined = _both(html, text)
    assert "You get this every week because the weekly career report is on." in combined
    assert "Dream-company matches are new roles at companies you follow" in combined
    assert "saved whose deadline is in the next 7 days" in combined


def test_weekly_report_omits_the_empty_hidden_section() -> None:
    """Hidden opportunities are not a running feature; an empty section would sell it."""
    user = models.User(display_name="Asha", email="asha@example.com")
    empty = WeeklyReportData(
        dream_company_matches=[_opportunity(1, "internship")],
        closing_soon=[],
        hidden_opportunities=[],
        intro=None,
    )
    html, text = _render_weekly_report(user, empty, unsub_url=None, now=NOW)
    assert "hidden opportunities" not in _both(html, text).lower()

    with_hidden = WeeklyReportData(
        dream_company_matches=[],
        closing_soon=[],
        hidden_opportunities=[_opportunity(9, "job")],
        intro=None,
    )
    html, text = _render_weekly_report(user, with_hidden, unsub_url=None, now=NOW)
    assert "New hidden opportunities" in _both(html, text)
