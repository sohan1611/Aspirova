"""ALERT-01 integration acceptance tests, on the reviewer's disposable Postgres."""

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import event, select

from core import models
from core.alert_identity import announcement_meta
from core.alert_relevance import UNKNOWN_ELIGIBILITY
from pipeline import notifications as worker
from scripts import alert_gold_set as gold
from tests import test_notifications as fixtures

db_session = fixtures.db_session
free_plan = fixtures.free_plan
NOW = datetime(2035, 1, 2, 12, tzinfo=timezone.utc)
PROFILE = {
    "stream": "engineering",
    "divisions": ["cse"],
    "interests": ["data_science"],
    "country": "IN",
}


@pytest.fixture(autouse=True)
def offline_render(monkeypatch):
    monkeypatch.setattr("core.unsubscribe._signing_key", lambda: b"alert-relevance-fixture-key")
    monkeypatch.setattr(worker, "programme_watch_updates", lambda *args: [])
    monkeypatch.setattr(worker, "collect_programme_watch_changes", lambda *args: None)
    monkeypatch.setattr(worker, "_hackathon_digest_opportunities", lambda *args: [])


def reader(db, profile=None, skills=None):
    user = models.User(
        email=f"alert-relevance-{uuid.uuid4()}@example.com",
        display_name="Private reader",
        field_profile=profile,
        graduation_year=2026,
        skills=skills,
    )
    db.add(user)
    db.flush()
    return user


def role(db, title="Data Science Intern", description="", **fields):
    identity = uuid.uuid4().hex
    company = fields.pop("company", None)
    if company is None:
        company = models.Company(
            slug=f"alert-rel-{identity}",
            name=f"Relevance {identity}",
            prestige_rank=fields.pop("prestige_rank", None),
        )
        db.add(company)
        db.flush()
    values = {
        "slug": f"alert-rel-{identity}",
        "title": title,
        "title_normalized": title.lower(),
        "description_raw": description,
        "company_id": company.id,
        "category": "internship",
        "country": "IN",
        "apply_url": "https://example.com/apply",
        "status": "active",
        "first_seen_at": NOW - timedelta(hours=1),
        "last_seen_at": NOW,
    }
    values.update(fields)
    opportunity = models.Opportunity(**values)
    db.add(opportunity)
    db.flush()
    return opportunity


def compose(db, user):
    return worker.compose_daily_digest(db, user, NOW, SimpleNamespace(for_reader=lambda *args: []))


def test_no_profile_is_exact_legacy_selection_and_never_queries_profile(db_session, monkeypatch):
    user = reader(db_session, {"country": "IN"})
    for index in range(7):
        role(db_session, f"Marketing Intern {index}", prestige_rank=index + 1)
    expected = worker._generic_recent_opportunities(db_session, NOW - timedelta(days=1), 5, NOW)
    monkeypatch.setattr(
        worker,
        "_profile_recent_opportunities",
        lambda *args: pytest.fail("no profile must retain legacy query path"),
    )
    draft = compose(db_session, user)
    assert [o.id for o in draft.opportunities] == [o.id for o in expected]
    assert {r["code"] for r in draft.reasons.values()} == {"generic"}


def test_interests_precede_generic_with_rank_and_followed_picks_stay_first(db_session):
    user = reader(db_session, PROFILE)
    for index in range(6):
        role(db_session, f"Marketing Intern {index}", prestige_rank=index + 1)
    matched = role(
        db_session,
        description="Data science data science",
        prestige_rank=1000,
        first_seen_at=NOW - timedelta(hours=20),
    )
    legacy = worker._generic_recent_opportunities(db_session, NOW - timedelta(days=1), 5, NOW)
    assert matched.id not in {o.id for o in legacy}
    draft = compose(db_session, user)
    assert draft.opportunities[0].id == matched.id and len(draft.opportunities) == 5
    reason = draft.reasons[str(matched.id)]
    assert reason["code"] == "profile_interest" and reason["matched_term"] == "data science"
    assert reason["rank"] > 0 and "Matches your interest: Data Science" in draft.text
    followed = role(db_session, "Finance Intern")
    db_session.add(models.DreamCompany(user_id=user.id, company_id=followed.company_id))
    db_session.flush()
    draft = compose(db_session, user)
    assert [o.id for o in draft.opportunities][:2] == [followed.id, matched.id]
    assert draft.reasons[str(followed.id)]["code"] == "company_follow"


def test_explicit_mismatches_cannot_return_through_generic_fallback(db_session):
    user = reader(db_session, PROFILE)
    wrong_batch = role(db_session, description="2027 batch", prestige_rank=1)
    wrong_country = role(
        db_session,
        country="US",
        is_remote=True,
        meta={"eligibility": ["Work authorization required"]},
    )
    unknown = role(db_session, "Data Science Analyst Intern")
    matched = role(db_session, "Data Science Research Intern", "2025/2026 passouts")
    foreign_unrestricted = role(db_session, "Data Science Reporting Intern", country="US")
    draft = compose(db_session, user)
    ids = {o.id for o in draft.opportunities}
    assert wrong_batch.id not in ids and wrong_country.id not in ids
    assert {unknown.id, matched.id, foreign_unrestricted.id}.issubset(ids)
    assert draft.reasons[str(unknown.id)]["eligibility"]["text"] == UNKNOWN_ELIGIBILITY
    assert "Open to 2026 graduates" in draft.reasons[str(matched.id)]["eligibility"]["text"]
    assert UNKNOWN_ELIGIBILITY in draft.text
    assert "Open to 2026 graduates" in draft.html


def test_skill_only_profile_and_country_is_only_a_relevance_tiebreaker(db_session):
    user = reader(db_session, {"country": "IN"}, [{"name": "Python", "level": "beginner"}])
    india = role(db_session, "Python Intern", country="IN")
    foreign = role(db_session, "Python Python Python Intern", country="BR")
    remote = role(db_session, "Python Intern", country=None, is_remote=True)
    rows, evidence, _blocked = worker._profile_recent_opportunities(
        db_session, user, NOW - timedelta(days=1), NOW, frozenset(), "IN"
    )
    assert [o.id for o in rows] == [foreign.id, india.id, remote.id]
    reasons = worker._profile_pick_reasons(db_session, user, rows, evidence)
    draft = compose(db_session, user)
    assert draft.opportunities[0].id == foreign.id
    assert reasons[foreign.id]["code"] == "skill"
    assert "Uses your skill: Python" in draft.text


def test_profile_never_creates_a_new_send_or_bypasses_entitlement(db_session, monkeypatch):
    user = reader(db_session, PROFILE)
    role(db_session)
    monkeypatch.setattr(worker, "_generic_recent_opportunities", lambda *args: [])
    monkeypatch.setattr(
        worker,
        "_profile_recent_opportunities",
        lambda *args: pytest.fail("legacy-empty must stay empty"),
    )
    assert compose(db_session, user).empty
    assert worker.compose_daily_digest(
        db_session,
        user,
        NOW,
        SimpleNamespace(for_reader=lambda *args: []),
        include_recommendations=False,
    ).empty


def test_profile_collapse_and_cross_sender_identity_still_hold(db_session):
    user = reader(db_session, PROFILE)
    board = role(db_session, apply_url="https://arbeitnow.com/job/role", primary_source="arbeitnow")
    direct = role(
        db_session,
        company=board.company,
        apply_url="https://jobs.lever.co/example/role",
        primary_source="lever",
    )
    assert [o.id for o in compose(db_session, user).opportunities] == [direct.id]
    db_session.add(
        models.Notification(
            user_id=user.id,
            type="saved_search_alert",
            status="sent",
            sent_at=NOW,
            opportunity_id=board.id,
            meta=announcement_meta([board], "saved_search_alert"),
        )
    )
    db_session.flush()
    assert compose(db_session, user).empty


def test_employer_copy_need_not_repeat_fts_terms_and_cannot_hide_batch_restriction(db_session):
    user = reader(db_session, PROFILE)
    board = role(
        db_session,
        "Research Intern",
        "Data science",
        primary_source="arbeitnow",
        apply_url="https://arbeitnow.com/job/research",
    )
    direct = role(
        db_session,
        "Research Intern",
        company=board.company,
        primary_source="lever",
        apply_url="https://jobs.lever.co/example/research",
    )
    draft = compose(db_session, user)
    assert [o.id for o in draft.opportunities] == [direct.id]
    assert draft.reasons[str(direct.id)]["match_source_id"] == board.id
    direct.description_raw = "2027 batch"
    db_session.flush()
    assert compose(db_session, user).empty


def test_reasons_recorded_and_sample_uses_send_time_snapshots(
    db_session, free_plan, monkeypatch, tmp_path
):
    user = reader(db_session, PROFILE)
    matched = role(db_session)
    deliveries = []
    monkeypatch.setattr(worker, "send_email", lambda *args, **kw: deliveries.append(args) or True)
    worker.send_daily_digests(db_session, now=NOW)
    ledger = db_session.scalar(
        select(models.Notification).where(
            models.Notification.user_id == user.id, models.Notification.type == "digest"
        )
    )
    reason = ledger.meta["reasons"][str(matched.id)]
    assert reason["code"] == "profile_interest" and reason["rank"] > 0
    assert reason["text"] in next(args[3] for args in deliveries if args[0] == user.email)
    user.field_profile = {"country": "BR"}
    matched.title = "Changed after send"
    db_session.flush()
    samples = gold.sample_rows(db_session, 100)
    row = next(r for r in samples if r["notification_id"] == ledger.id)
    assert row["country"] == "IN" and row["title"] == "Data Science Intern"
    path = tmp_path / "gold.csv"
    gold.write_sample([row], path)
    output = path.read_text(encoding="utf-8")
    assert user.email not in output and user.display_name not in output
    assert gold.sample_rows(db_session, 1)[0]["notification_id"] >= ledger.id


def test_query_count_does_not_grow_with_candidate_count(db_session):
    user = reader(db_session, PROFILE)
    role(db_session)
    statements = []

    def count(*args):
        statements.append(args[2])

    event.listen(db_session.bind, "before_cursor_execute", count)
    try:
        compose(db_session, user)
        initial = len(statements)
        for index in range(20):
            role(db_session, f"Data Science Intern {index}")
        statements.clear()
        compose(db_session, user)
        assert len(statements) == initial
        statements.clear()
        worker._profile_recent_opportunities(
            db_session, user, NOW - timedelta(days=1), NOW, frozenset(), "IN"
        )
        assert len(statements) == 2
        assert "description_raw" not in statements[0]
        assert "matched_term_index" not in statements[0]
        assert "LIMIT" in statements[0]
        assert "description_raw" in statements[1]
        # Term attribution is one batched query over final picks, never one per term/row.
        statements.clear()
        rows, evidence, _blocked = worker._profile_recent_opportunities(
            db_session, user, NOW - timedelta(days=1), NOW, frozenset(), "IN"
        )
        worker._profile_pick_reasons(db_session, user, rows[:5], evidence)
        assert len(statements) == 3
        assert "matched_term_index" in statements[-1]
        assert "description_raw" not in statements[-1]
    finally:
        event.remove(db_session.bind, "before_cursor_execute", count)


def test_profile_shortlist_is_bounded_and_eligibility_does_not_lazy_load(db_session):
    user = reader(db_session, PROFILE)
    for index in range(80):
        role(db_session, f"Data Science Intern {index}", "2025/2026 passouts")
    # Clear the identity map so setup's already-loaded descriptions cannot hide N+1s.
    user_id = user.id
    db_session.expunge_all()
    user = db_session.get(models.User, user_id)
    statements = []

    def count(*args):
        statements.append(args[2])

    event.listen(db_session.bind, "before_cursor_execute", count)
    try:
        rows, evidence, blocked = worker._profile_recent_opportunities(
            db_session, user, NOW - timedelta(days=1), NOW, frozenset(), "IN"
        )
        assert len(rows) == worker.DIGEST_PROFILE_SHORTLIST_SIZE == 60
        assert len(evidence) == 60 and not blocked
        reasons = worker._profile_pick_reasons(db_session, user, rows[:5], evidence)
        assert len(reasons) == 5
        assert all("Open to 2026 graduates" in r["eligibility"]["text"] for r in reasons.values())
        assert len(statements) == 3
    finally:
        event.remove(db_session.bind, "before_cursor_execute", count)
