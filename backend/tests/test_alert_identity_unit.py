"""Pure identity/ranking checks, also runnable with pytest --noconftest."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from core import models
from core.alert_identity import (
    NEW_LISTING_EVENTS,
    already_notified,
    announcement_meta,
    collapse_duplicates,
    load_sent_alert_index,
    role_key,
    version_key,
)

NOW = datetime(2030, 1, 1, 12, tzinfo=timezone.utc)


def listing(identity=1, **fields):
    values = {
        "id": identity,
        "company_id": 1,
        "title": "Software Engineer Intern",
        "country": "IN",
        "apply_url": "https://arbeitnow.com/jobs/role",
        "first_seen_at": NOW,
    }
    values.update(fields)
    return models.Opportunity(**values)


def test_role_normalization_and_country_boundaries():
    original = listing()
    assert role_key(original) == role_key(listing(2, title=" SOFTWARE  Engineer\nIntern "))
    assert role_key(original) == role_key(listing(2, location="another city", country="in"))
    for other in (
        listing(2, title="Product Intern"),
        listing(2, company_id=2),
        listing(2, country="US"),
    ):
        assert role_key(original) != role_key(other)
    remote = listing(2, country=None, is_remote=True)
    assert role_key(remote) != role_key(listing(3, country=None, is_remote=False))


def test_orphans_use_normalized_name_when_available_and_never_guess_employer():
    first = listing(company_id=None, meta={"company_name": "Example, Inc."})
    second = listing(2, company_id=None, meta={"company_name": " example "})
    assert role_key(first) == role_key(second)
    assert role_key(listing(company_id=None)) != role_key(listing(2, company_id=None))


@pytest.mark.parametrize("event", sorted(NEW_LISTING_EVENTS))
def test_announcement_version_changes_only_after_closure(event):
    opportunity = listing(deadline=NOW + timedelta(days=2))
    assert version_key(opportunity, event) == "new"
    opportunity.deadline += timedelta(days=1)
    opportunity.last_seen_at = NOW + timedelta(days=1)
    opportunity.updated_at = NOW + timedelta(days=1)
    assert version_key(opportunity, event) == "new"
    opportunity.meta = {
        "alert_reopened_after": NOW.isoformat(),
        "alert_reopened_at": (NOW + timedelta(hours=1)).isoformat(),
    }
    assert version_key(opportunity, event) == f"reopened:{NOW.isoformat()}"


def test_closing_version_uses_utc_date_only():
    opportunity = listing(deadline=NOW)
    original = version_key(opportunity, "closing_soon")
    opportunity.deadline += timedelta(hours=1)
    assert version_key(opportunity, "closing_soon") == original
    opportunity.deadline += timedelta(days=1)
    assert version_key(opportunity, "closing_soon") != original
    with pytest.raises(ValueError):
        version_key(opportunity, "saved_safety")


def test_source_preference_then_deadline_then_first_seen_preserves_role_order():
    company = models.Company(id=1, name="Example", domain="example.com")
    board = listing(deadline=NOW + timedelta(days=1), company=company)
    unrelated = listing(2, title="Product Intern", company=company)
    employer = listing(3, apply_url="https://careers.example.com/role", company=company)
    assert collapse_duplicates([board, unrelated, employer]) == [employer, unrelated]
    ats = listing(4, apply_url="https://jobs.lever.co/example/role", deadline=NOW, company=company)
    older = listing(5, apply_url=ats.apply_url, deadline=NOW, first_seen_at=NOW - timedelta(days=1))
    assert collapse_duplicates([board, employer, ats, older]) == [older]
    assert collapse_duplicates([ats, listing(6, apply_url=ats.apply_url, deadline=NOW)]) == [ats]


class LedgerSession:
    """Exercise the reader's identity logic without a database or config load."""

    def __init__(self, rows, legacy=()):
        self.rows = [(row, opportunity, row.sent_at or NOW) for row, opportunity in rows]
        self.legacy = legacy
        self.queries = 0

    def execute(self, query):
        self.queries += 1
        return SimpleNamespace(all=lambda: self.rows)

    def scalars(self, query):
        self.queries += 1
        return SimpleNamespace(all=lambda: self.legacy)


def notified(session, candidates, events=NEW_LISTING_EVENTS):
    return already_notified(
        session, uuid4(), candidates, events=events, since=NOW - timedelta(days=7)
    )


def test_legacy_batch_keys_cover_a_duplicate_in_two_queries():
    board, direct = listing(), listing(2)
    row = models.Notification(type="digest", sent_at=NOW, meta={"hackathon_ids": [board.id]})
    session = LedgerSession([(row, None)], [board])
    assert notified(session, [direct]) == {direct.id}
    assert session.queries == 2


def test_snapshots_cover_duplicate_without_loading_the_old_opportunity():
    board, direct = listing(), listing(2)
    row = models.Notification(type="digest", sent_at=NOW, meta=announcement_meta([board], "digest"))
    session = LedgerSession([(row, None)])
    assert notified(session, [direct]) == {direct.id}
    assert session.queries == 1


def test_reopening_rejects_the_old_announcement_and_accepts_another_crawlers_new_one():
    board, direct = listing(), listing(2)
    direct.meta = {"alert_reopened_after": (NOW + timedelta(hours=1)).isoformat()}
    old = models.Notification(
        type="instant_alert",
        opportunity_id=board.id,
        sent_at=NOW,
        meta=announcement_meta([board], "instant_alert"),
    )
    assert notified(LedgerSession([(old, board)]), [direct]) == set()
    new = models.Notification(
        type="saved_search_alert",
        sent_at=NOW + timedelta(hours=2),
        meta=announcement_meta([board], "saved_search_alert"),
    )
    assert notified(LedgerSession([(old, board), (new, None)]), [direct]) == {direct.id}


def test_closing_snapshot_survives_the_joined_deadline_changing():
    board, direct = listing(deadline=NOW), listing(2, deadline=NOW)
    row = models.Notification(
        type="closing_soon",
        opportunity_id=board.id,
        sent_at=NOW,
        meta=announcement_meta([board], "closing_soon"),
    )
    assert notified(LedgerSession([(row, board)]), [direct], {"closing_soon"}) == {direct.id}
    board.deadline += timedelta(days=1)
    direct.deadline += timedelta(days=1)
    assert notified(LedgerSession([(row, board)]), [direct], {"closing_soon"}) == set()


def test_reusable_index_adds_committed_snapshots_without_database_reads():
    board, direct = listing(), listing(2)
    session = LedgerSession([])
    index = load_sent_alert_index(session, uuid4(), events=NEW_LISTING_EVENTS, since=NOW)
    assert index.already_notified([direct]) == set()
    index.record_sent(announcement_meta([board], "saved_search_alert"), "saved_search_alert", NOW)
    assert index.already_notified([direct]) == {direct.id}
    assert index.already_notified([board, direct]) == {board.id, direct.id}
    assert session.queries == 1


@pytest.mark.parametrize("legacy", [False, True], ids=["snapshots", "legacy-batch"])
def test_digest_loads_index_once_for_all_three_candidate_paths(monkeypatch, legacy):
    import pipeline.notifications as notifications

    board, direct = listing(), listing(2)
    hackathon = listing(3, title="College Hackathon", category="hackathon")
    meta = {"opportunity_ids": [board.id]} if legacy else announcement_meta([board], "digest")
    row = models.Notification(type="digest", sent_at=NOW, meta=meta)
    session = LedgerSession([(row, None)], [board])
    user = models.User(id=uuid4(), email="pure-digest@example.com")
    monkeypatch.setattr(
        notifications,
        "_digest_history",
        lambda *args: notifications.DigestHistory(None, frozenset()),
    )
    monkeypatch.setattr(notifications, "_dream_company_opportunities", lambda *args: [board])
    monkeypatch.setattr(notifications, "_generic_recent_opportunities", lambda *args: [direct])
    monkeypatch.setattr(notifications, "programme_watch_updates", lambda *args: [])
    monkeypatch.setattr(notifications, "_render_digest", lambda *args, **kwargs: ("html", "text"))
    monkeypatch.setattr(notifications, "unsubscribe_url", lambda *args: None)
    loads = []

    def load(*args, **kwargs):
        loads.append(True)
        return load_sent_alert_index(*args, **kwargs)

    monkeypatch.setattr(notifications, "load_sent_alert_index", load)
    picks = SimpleNamespace(for_reader=lambda ids: [hackathon])
    draft = notifications.compose_daily_digest(session, user, NOW, picks)
    assert draft.opportunities == [] and draft.hackathons == [hackathon]
    assert len(loads) == 1
    assert session.queries == (2 if legacy else 1)
