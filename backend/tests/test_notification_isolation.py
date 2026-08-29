"""Regression tests for per-user notification-worker error isolation."""

from datetime import datetime, timezone

import pipeline.notifications as notifications_module
import pipeline.weekly_report as weekly_report_module
from tests import test_notifications as notification_tests
from tests.test_weekly_report import _paid_plan, _subscribe, _user

_make_opportunity = notification_tests._make_opportunity
_make_user = notification_tests._make_user
db_session = notification_tests.db_session
free_plan = notification_tests.free_plan
sent_emails = notification_tests.sent_emails
source_and_company = notification_tests.source_and_company


class _ScalarResult:
    def __init__(self, items):
        self._items = items

    def all(self):
        return self._items


def test_daily_digest_isolates_per_user_render_failure(
    db_session, free_plan, sent_emails, source_and_company, monkeypatch
) -> None:
    _source, company = source_and_company
    now = datetime.now(timezone.utc)
    failed_user = _make_user(db_session)
    second_user = _make_user(db_session)
    third_user = _make_user(db_session)
    users = [failed_user, second_user, third_user]
    opportunities_by_user = {
        user.id: _make_opportunity(db_session, company, first_seen_at=now) for user in users
    }
    failed_opportunity = opportunities_by_user[failed_user.id]
    rollback_calls = []

    monkeypatch.setattr(
        db_session,
        "scalars",
        lambda *_args, **_kwargs: _ScalarResult(users),
    )
    monkeypatch.setattr(
        notifications_module,
        "_already_sent_today",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        notifications_module,
        "_already_alerted",
        lambda *_args, **_kwargs: False,
    )

    def dream_company_opportunities(_session, user_id, *_args, **_kwargs):
        return [opportunities_by_user[user_id]]

    monkeypatch.setattr(
        notifications_module,
        "_dream_company_opportunities",
        dream_company_opportunities,
    )

    def render_digest(opportunities, *_args, **_kwargs):
        if opportunities[0].id == failed_opportunity.id:
            raise RuntimeError("digest render failed")
        return "<p>Digest</p>", "Digest"

    monkeypatch.setattr(notifications_module, "_render_digest", render_digest)
    # The shared db_session fixture owns the outer transaction. Keep its
    # setup rows available after the simulated render failure while asserting
    # that the worker requests the required rollback.
    monkeypatch.setattr(db_session, "rollback", lambda: rollback_calls.append(True))

    result = notifications_module.send_daily_digests(db_session, now=now)

    assert result["failed"] == 1
    assert result["sent"] == 2
    assert rollback_calls == [True]
    assert {email["to"] for email in sent_emails} == {second_user.email, third_user.email}


def test_weekly_report_isolates_per_user_render_failure(db_session, monkeypatch) -> None:
    plan = _paid_plan(db_session, "isolation")
    failed_user = _user(db_session, "failed")
    second_user = _user(db_session, "second")
    third_user = _user(db_session, "third")
    users = [failed_user, second_user, third_user]
    for user in users:
        _subscribe(db_session, user, plan)

    sent_emails = []
    rollback_calls = []
    monkeypatch.setattr(
        db_session,
        "scalars",
        lambda *_args, **_kwargs: _ScalarResult(users),
    )
    monkeypatch.setattr(
        weekly_report_module,
        "_already_sent_this_week",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        weekly_report_module,
        "_closing_soon_opportunities",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        weekly_report_module,
        "_recent_hidden_opportunities",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        weekly_report_module,
        "_recent_dream_company_matches",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        weekly_report_module,
        "_cohort_intro",
        lambda *_args, **_kwargs: None,
    )

    def render_weekly_report(user, data):
        if user.id == failed_user.id:
            raise RuntimeError("weekly report render failed")
        return "<p>Weekly report</p>", "Weekly report"

    def send_email(to, subject, html, text):
        sent_emails.append({"to": to, "subject": subject, "html": html, "text": text})
        return True

    monkeypatch.setattr(weekly_report_module, "_render_weekly_report", render_weekly_report)
    monkeypatch.setattr(weekly_report_module.email_client, "send_email", send_email)
    monkeypatch.setattr(db_session, "rollback", lambda: rollback_calls.append(True))

    result = weekly_report_module.send_weekly_reports(
        db_session,
        now=datetime.now(timezone.utc),
    )

    assert result["failed"] == 1
    assert result["sent"] == 2
    assert rollback_calls == [True]
    assert {email["to"] for email in sent_emails} == {second_user.email, third_user.email}
