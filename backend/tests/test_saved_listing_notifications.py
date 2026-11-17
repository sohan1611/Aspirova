"""ALERT-04 integration tests. Run only against the reviewer's throwaway Postgres."""

import argparse
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, insert, select, update
from sqlalchemy.orm import Session

from api import middleware, reports
from api.auth import get_current_user
from api.deps import get_db
from api.main import app
from core import models
from core.adapters import NormalizedListing, RawListing
from core.config import get_settings
from core.listing_safety import safety_flag
from crawlers.runner import _reopen_seen_inventory_listings, _reopen_seen_rolling_listings
from pipeline import liveness, notifications, revalidate
from pipeline.ingest import _make_opportunity_slug, ingest_one, load_board_state
from pipeline.reopen import reopen_estimate
from pipeline.retirement import reopen_government_extension
from pipeline.saved_listing_notifications import load_closure_notice_breaker
from scripts.flag_listing import flag_listing, https_url, main
from scripts.cleanup_expired_competitions import cleanup_expired_competitions
from scripts.reopen_rolling_ttl import reopen_rolling_ttl
from scripts.reopen_windowed_source_closures import reopen


@pytest.fixture
def db_session(engine):
    with engine.connect() as connection:
        transaction = connection.begin()
        with Session(bind=connection) as session:
            yield session
        transaction.rollback()


@pytest.fixture
def now():
    return datetime.now(timezone.utc).replace(microsecond=0)


@pytest.fixture
def company(db_session):
    row = models.Company(
        slug=f"saved-safety-{uuid.uuid4().hex}",
        name="Safety Test Co",
        name_normalized="safety test co",
    )
    db_session.add(row)
    db_session.flush()
    return row


@pytest.fixture
def user(db_session):
    row = models.User(email=f"saved-safety-{uuid.uuid4().hex}@example.com")
    db_session.add(row)
    db_session.flush()
    return row


@pytest.fixture
def mail(monkeypatch):
    calls = []

    def deliver(to, subject, html, text, headers=None):
        calls.append({"to": to, "subject": subject, "html": html, "text": text})
        return True

    monkeypatch.setattr(notifications, "send_email", deliver)
    monkeypatch.setattr("core.unsubscribe._signing_key", lambda: b"saved-safety-test-key")
    return calls


@pytest.fixture
def client(db_session, user, monkeypatch):
    monkeypatch.setattr(middleware, "get_redis", lambda: None)
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


def listing(db_session, company, now, **overrides):
    values = {
        "slug": f"saved-safety-{uuid.uuid4().hex}",
        "title": "Software Engineering Intern",
        "title_normalized": "software engineering intern",
        "company_id": company.id,
        "category": "internship",
        "apply_url": "https://example.com/careers/intern",
        "description_raw": "Build software and learn Python with our engineering team.",
        "country": "IN",
        "is_remote": False,
        "first_seen_at": now - timedelta(days=10),
        "last_seen_at": now,
        "closed_at": now - timedelta(hours=30),
    }
    row = models.Opportunity(**{**values, **overrides})
    db_session.add(row)
    db_session.flush()
    return row


def save(db_session, user, opportunity, now, *, status="saved", created_at=None):
    db_session.add(
        models.Bookmark(
            user_id=user.id,
            opportunity_id=opportunity.id,
            status=status,
            created_at=created_at or now - timedelta(days=10),
        )
    )
    db_session.flush()


def flagged(db_session, company, now, **overrides):
    row = listing(db_session, company, now, **overrides)
    flag_listing(
        db_session,
        slug=row.slug,
        kind="scam",
        note="An unauthorised fee request.",
        source_url="https://example.com/safety/source",
        now=now,
    )
    db_session.flush()
    return row


def notices(db_session, user):
    return list(
        db_session.scalars(
            select(models.Notification).where(
                models.Notification.user_id == user.id,
                models.Notification.type.in_(("saved_closed", "saved_safety")),
            )
        )
    )


@pytest.mark.parametrize(
    "age,deadline_offset,created_after,stage,eligible",
    [
        (30, None, False, "saved", True),
        (30, 24, False, "saved", True),
        (30, 0, False, "saved", False),
        (30, -1, False, "saved", False),
        (23, None, False, "saved", False),
        (24, None, False, "saved", True),
        (7 * 24, None, False, "saved", True),
        (7 * 24 + 1, None, False, "saved", False),
        (None, None, False, "saved", False),
        (30, None, True, "saved", False),
        (30, None, False, "applied", False),
        (30, None, False, "interviewing", False),
        (30, None, False, "offer", False),
        (30, None, False, "archived", False),
        (30, None, False, "rejected", False),
    ],
)
def test_closure_eligibility(
    db_session, user, company, now, mail, age, deadline_offset, created_after, stage, eligible
):
    closed_at = now - timedelta(hours=age) if age is not None else None
    deadline = closed_at + timedelta(hours=deadline_offset) if deadline_offset is not None else None
    row = listing(db_session, company, now, closed_at=closed_at, deadline=deadline)
    save(
        db_session,
        user,
        row,
        now,
        status=stage,
        created_at=closed_at + timedelta(seconds=1) if created_after else None,
    )
    notifications.send_closing_soon_alerts(db_session, now=now)
    rows = notices(db_session, user)
    assert bool(rows) is eligible
    assert bool([call for call in mail if call["to"] == user.email]) is eligible
    if eligible:
        assert rows[0].type == "saved_closed"
        assert next(call for call in mail if call["to"] == user.email)["subject"] == (
            "A listing you saved has closed"
        )
        assert rows[0].meta["emailed_at"] == now.isoformat()


@pytest.mark.parametrize("stage", ["saved", "applied", "interviewing", "offer", "archived"])
def test_safety_includes_every_tracker_stage(db_session, user, company, now, mail, stage):
    row = flagged(db_session, company, now)
    save(db_session, user, row, now, status=stage)
    notifications.send_closing_soon_alerts(db_session, now=now)
    assert [n.type for n in notices(db_session, user)] == ["saved_safety"]
    email = next(call for call in mail if call["to"] == user.email)
    for part in (email["html"], email["text"]):
        assert "reported as a scam" in part
        assert "An unauthorised fee request." in part
        assert "Do not pay any fee or share bank or ID documents." in part
        assert "https://example.com/safety/source" in part
    assert email["subject"] == "Safety warning about a listing you saved"


def test_combined_email_and_dedupe(db_session, user, company, now, mail, client):
    unsafe = flagged(db_session, company, now)
    closed = listing(db_session, company, now, title="Closed test internship")
    soon = listing(
        db_session,
        company,
        now,
        title="Soon test internship",
        closed_at=None,
        deadline=now + timedelta(days=2),
        deadline_confidence="explicit",
    )
    for row in (unsafe, closed, soon):
        save(db_session, user, row, now)
    for _ in range(2):
        notifications.send_closing_soon_alerts(db_session, now=now)
    emails = [call for call in mail if call["to"] == user.email]
    assert len(emails) == 1
    for part in (emails[0]["html"], emails[0]["text"]):
        assert (
            part.index("Safety warnings") < part.index("Closed early") < part.index("Closing soon")
        )
    assert len(notices(db_session, user)) == 2
    response = client.get("/notifications")
    assert response.status_code == 200
    items = {item["type"]: item for item in response.json()["items"]}
    assert items["saved_safety"]["title"] == "Safety warning"
    assert items["saved_safety"]["body"] == (
        "‘Software Engineering Intern’ was reported as a scam. Don't pay fees or share documents."
    )
    assert items["saved_safety"]["opportunity_slug"] == unsafe.slug
    assert items["saved_closed"]["title"] == "A saved listing closed"
    assert items["saved_closed"]["body"] == (
        "‘Closed test internship’ at Safety Test Co stopped accepting applications."
    )


def mass_closures(db_session, company, closed_at, *, deadline_passed=False, status="active"):
    """Populate a catalogue incident in one bulk insert, not 1,600 round trips."""
    batch = uuid.uuid4().hex
    rows = []
    for index in range(1600):
        timestamp = closed_at + timedelta(hours=index % 5 - 2)
        rows.append(
            {
                "slug": f"saved-mass-{batch}-{index}",
                "company_id": company.id,
                "title": "Mass closure fixture",
                "apply_url": "https://example.com/careers/mass-fixture",
                "status": status,
                "closed_at": timestamp,
                "deadline": timestamp - timedelta(hours=1) if deadline_passed else None,
            }
        )
    return list(
        db_session.scalars(insert(models.Opportunity).returning(models.Opportunity.id), rows)
    )


def test_breaker_holds_incident_four_days_later_but_not_quiet_closure_or_safety(
    db_session, user, company, now, mail, monkeypatch, caplog
):
    monkeypatch.setattr(get_settings(), "saved_closure_notice_breaker", 1500)
    incident = now - timedelta(hours=30)
    held = listing(db_session, company, now, title="Incident listing", closed_at=incident)
    quiet = listing(
        db_session, company, now, title="Quiet listing", closed_at=incident - timedelta(days=3)
    )
    mass_closures(db_session, company, incident)
    unsafe = flagged(db_session, company, now)
    for row in (held, quiet, unsafe):
        save(db_session, user, row, now)

    for run_at in (now, now + timedelta(days=4)):
        caplog.clear()
        notifications.send_closing_soon_alerts(db_session, now=run_at)
        rows = notices(db_session, user)
        assert {(row.type, row.opportunity_id) for row in rows} == {
            ("saved_closed", quiet.id),
            ("saved_safety", unsafe.id),
        }
        warnings = [
            r.getMessage()
            for r in caplog.records
            if "Saved closure notice breaker" in r.getMessage()
        ]
        assert len(warnings) == 1
        assert "held 1 candidates" in warnings[0]
        assert "largest window count 1601" in warnings[0]
    emails = [call for call in mail if call["to"] == user.email]
    assert len(emails) == 1
    assert quiet.title in emails[0]["text"]
    assert held.title not in emails[0]["text"]
    assert "Safety warnings" in emails[0]["text"]


def test_breaker_window_quiet_after_mass_reopen(db_session, user, company, now, mail, monkeypatch):
    monkeypatch.setattr(get_settings(), "saved_closure_notice_breaker", 1500)
    incident = now - timedelta(hours=30)
    remaining = listing(db_session, company, now, title="Still closed listing", closed_at=incident)
    reopened = listing(db_session, company, now, title="Reverted listing", closed_at=incident)
    ids = mass_closures(db_session, company, incident)
    for row in (remaining, reopened):
        save(db_session, user, row, now)
    db_session.execute(
        update(models.Opportunity)
        .where(models.Opportunity.id.in_([*ids, reopened.id]))
        .values(closed_at=None)
    )
    notifications.send_closing_soon_alerts(db_session, now=now)
    assert [(row.type, row.opportunity_id) for row in notices(db_session, user)] == [
        ("saved_closed", remaining.id)
    ]
    email = next(call for call in mail if call["to"] == user.email)
    assert remaining.title in email["text"]
    assert reopened.title not in email["text"]


def test_breaker_buckets_only_early_nonwithdrawn_closures(
    db_session, user, company, now, mail, monkeypatch
):
    monkeypatch.setattr(get_settings(), "saved_closure_notice_breaker", 1500)
    incident = now - timedelta(hours=30)
    candidate = listing(db_session, company, now, closed_at=incident)
    mass_closures(db_session, company, incident, deadline_passed=True)
    mass_closures(db_session, company, incident, status="withdrawn")
    listing(db_session, company, now, closed_at=now - timedelta(days=8, hours=1))
    listing(db_session, company, now, closed_at=now + timedelta(hours=1))
    save(db_session, user, candidate, now)
    breaker = load_closure_notice_breaker(db_session, now)
    assert sum(count for _, count in breaker.buckets) == 1
    notifications.send_closing_soon_alerts(db_session, now=now)
    assert [(row.type, row.opportunity_id) for row in notices(db_session, user)] == [
        ("saved_closed", candidate.id)
    ]
    assert any(call["to"] == user.email for call in mail)


def test_email_off_keeps_in_app_notices(db_session, user, company, now, mail, client):
    user.notification_prefs = {"closing_soon": False}
    for row in (listing(db_session, company, now), flagged(db_session, company, now)):
        save(db_session, user, row, now)
    notifications.send_closing_soon_alerts(db_session, now=now)
    rows = notices(db_session, user)
    assert {row.type for row in rows} == {"saved_closed", "saved_safety"}
    assert all(row.channel == "in_app" and not row.meta["email_pending"] for row in rows)
    assert not any(call["to"] == user.email for call in mail)
    assert client.get("/notifications").json()["unread"] == 2


@pytest.mark.parametrize("raises", [False, True])
def test_failed_email_retries_without_duplicate_in_app(
    db_session, user, company, now, mail, monkeypatch, raises
):
    for row in (listing(db_session, company, now), flagged(db_session, company, now)):
        save(db_session, user, row, now)
    successful_send = notifications.send_email

    def failed_send(*args, **kwargs):
        if raises:
            raise RuntimeError("temporary mail failure")
        return False

    monkeypatch.setattr(notifications, "send_email", failed_send)
    notifications.send_closing_soon_alerts(db_session, now=now)
    first_ids = {row.id for row in notices(db_session, user)}
    assert len(first_ids) == 2
    assert all(
        row.meta["email_pending"] and "emailed_at" not in row.meta
        for row in notices(db_session, user)
    )
    monkeypatch.setattr(notifications, "send_email", successful_send)
    notifications.send_closing_soon_alerts(db_session, now=now + timedelta(hours=1))
    assert {row.id for row in notices(db_session, user)} == first_ids
    assert all(
        not row.meta["email_pending"] and row.meta["emailed_at"]
        for row in notices(db_session, user)
    )
    assert len([call for call in mail if call["to"] == user.email]) == 1


def test_reopened_or_cleared_warning_is_not_emailed_on_retry(
    db_session, user, company, now, mail, monkeypatch
):
    closed = listing(db_session, company, now)
    unsafe = flagged(db_session, company, now)
    for row in (closed, unsafe):
        save(db_session, user, row, now)
    sender = notifications.send_email
    monkeypatch.setattr(notifications, "send_email", lambda *a, **kw: False)
    notifications.send_closing_soon_alerts(db_session, now=now)
    closed.closed_at = None
    flag_listing(db_session, slug=unsafe.slug, clear=True)
    # Clearing restored the earlier source closure, so remove the bookmark too.
    db_session.delete(db_session.get(models.Bookmark, (user.id, unsafe.id)))
    db_session.flush()
    monkeypatch.setattr(notifications, "send_email", sender)
    notifications.send_closing_soon_alerts(db_session, now=now)
    assert not any(call["to"] == user.email for call in mail)
    assert len(notices(db_session, user)) == 2
    assert all(not row.meta["email_pending"] for row in notices(db_session, user))


def test_deleted_user_is_excluded(db_session, user, company, now, mail):
    user.deleted_at = now
    for row in (listing(db_session, company, now), flagged(db_session, company, now)):
        save(db_session, user, row, now)
    notifications.send_closing_soon_alerts(db_session, now=now)
    assert notices(db_session, user) == []
    assert not any(call["to"] == user.email for call in mail)


def test_free_and_paid_receive_both_notices(db_session, user, company, now, mail):
    free_plan = db_session.scalar(select(models.Plan).where(models.Plan.key == "free"))
    if free_plan is None:
        free_plan = models.Plan(key="free", price_paise=0, features={})
        db_session.add(free_plan)
    paid_plan = models.Plan(
        key=f"saved-safety-paid-{uuid.uuid4().hex}",
        price_paise=4900,
        billing="monthly",
        features={},
    )
    paid = models.User(email=f"saved-safety-paid-{uuid.uuid4().hex}@example.com")
    db_session.add_all([paid_plan, paid])
    db_session.flush()
    db_session.add(
        models.Subscription(
            user_id=paid.id,
            plan_id=paid_plan.id,
            status="active",
            current_period_end=now + timedelta(days=30),
        )
    )
    closed, unsafe = listing(db_session, company, now), flagged(db_session, company, now)
    for recipient in (user, paid):
        for row in (closed, unsafe):
            save(db_session, recipient, row, now)
    notifications.send_closing_soon_alerts(db_session, now=now)
    for recipient in (user, paid):
        assert {n.type for n in notices(db_session, recipient)} == {"saved_closed", "saved_safety"}
        assert len([call for call in mail if call["to"] == recipient.email]) == 1


@pytest.mark.parametrize("prior_status,already_closed", [("active", False), ("expired", True)])
def test_flag_and_clear_restore_only_owned_state(
    db_session, company, now, prior_status, already_closed
):
    original_closure = now - timedelta(days=3) if already_closed else None
    row = listing(
        db_session,
        company,
        now,
        status=prior_status,
        closed_at=original_closure,
        meta={"summary_source": "ai", "other": "keep"},
    )
    kwargs = dict(slug=row.slug, kind="recalled", note="Recalled by the source", now=now)
    assert flag_listing(db_session, **kwargs)
    first_flag = dict(row.meta["safety"])
    assert row.status == "withdrawn"
    assert row.closed_at == (original_closure or now)
    assert not flag_listing(db_session, **{**kwargs, "now": now + timedelta(hours=1)})
    assert row.meta["safety"] == first_flag
    # Editing a warning must retain the original restoration metadata.
    assert flag_listing(db_session, **{**kwargs, "note": "Corrected source notice"})
    assert flag_listing(db_session, slug=row.slug, clear=True)
    assert row.status == prior_status
    assert row.closed_at == original_closure
    assert row.meta == {"summary_source": "ai", "other": "keep"}
    assert not flag_listing(db_session, slug=row.slug, clear=True)


def test_clear_preserves_subsequently_changed_closure(db_session, company, now):
    row = flagged(db_session, company, now, closed_at=None)
    row.closed_at = now + timedelta(hours=1)
    flag_listing(db_session, slug=row.slug, clear=True)
    assert row.closed_at == now + timedelta(hours=1)


@pytest.mark.parametrize("url", ["http://example.com", "javascript:alert(1)", "https:///bad"])
def test_flag_refuses_non_https_source(url):
    with pytest.raises(argparse.ArgumentTypeError):
        https_url(url)


def test_flag_cli_dry_run_and_clear(db_session, engine, company, now, monkeypatch, capsys):
    row = listing(db_session, company, now, closed_at=None)
    # CLI gets a session over this test's existing transaction, never a real DB URL.
    monkeypatch.setattr("scripts.flag_listing.make_engine", lambda: engine)
    monkeypatch.setattr(
        "scripts.flag_listing.Session",
        lambda _: Session(bind=db_session.connection(), join_transaction_mode="create_savepoint"),
    )
    monkeypatch.setattr("scripts.flag_listing.refresh_api_details", lambda _: {"status": "test"})
    monkeypatch.setattr("scripts.flag_listing.notify_changed", lambda _, **kw: {"status": "test"})
    monkeypatch.setattr(engine, "dispose", lambda: None)
    main(["--slug", row.slug, "--kind", "scam", "--note", "Fee request", "--dry-run"])
    assert "dry run, rolled back" in capsys.readouterr().out
    db_session.expire_all()
    assert db_session.get(models.Opportunity, row.id).status == "active"
    main(["--slug", row.slug, "--kind", "scam", "--note", "Fee request"])
    db_session.expire_all()
    assert db_session.get(models.Opportunity, row.id).status == "withdrawn"
    main(["--slug", row.slug, "--clear"])
    db_session.expire_all()
    assert db_session.get(models.Opportunity, row.id).status == "active"


def test_detail_and_saved_list_keep_safety_object(db_session, user, company, now, client):
    row = flagged(db_session, company, now)
    save(db_session, user, row, now, status="applied")
    detail = client.get(f"/opportunity/{row.slug}")
    assert detail.status_code == 200
    data = detail.json()
    assert data["status"] == "withdrawn"
    assert {key: data["safety"][key] for key in ("kind", "note", "source_url")} == {
        key: safety_flag(row)[key] for key in ("kind", "note", "source_url")
    }
    assert datetime.fromisoformat(data["safety"]["flagged_at"]) == now
    saved = client.get("/bookmarks").json()
    item = next(item for item in saved if item["slug"] == row.slug)
    assert item["safety"] == data["safety"]
    assert item["bookmark_status"] == "applied"
    assert client.delete(f"/bookmarks/{row.slug}").status_code == 204


@pytest.mark.parametrize(
    "path_name",
    [
        "inventory",
        "rolling",
        "government",
        "repair_windowed",
        "repair_ttl",
        "liveness",
        "estimate",
        "revalidate",
    ],
)
def test_pipeline_never_reopens_flagged_listing(db_session, company, now, monkeypatch, path_name):
    row = flagged(
        db_session,
        company,
        now,
        primary_source="himalayas",
        meta={"closed_reason": "rolling_window_ttl"},
    )
    original_meta = dict(row.meta)
    original_closed = row.closed_at
    if path_name == "inventory":
        _reopen_seen_inventory_listings(db_session, [row.id])
    elif path_name == "rolling":
        _reopen_seen_rolling_listings(db_session, [row.id])
    elif path_name == "government":
        row.primary_source = "meity_careers"
        row.deadline = row.closed_at - timedelta(days=1)
        assert not reopen_government_extension(
            row, "meity_careers", now + timedelta(days=5), now=now
        )
    elif path_name == "repair_windowed":
        reopen(db_session, since=(now - timedelta(days=4)).date())
    elif path_name == "repair_ttl":
        reopen_rolling_ttl(db_session, closed_on=original_closed.date(), apply=True)
    elif path_name == "liveness":
        liveness._mark_closed(db_session, opportunity_ids=[row.id], detected_at=now)
        liveness._stamp_checked(db_session, [row.id], now)
    elif path_name == "estimate":
        assert reopen_estimate(db_session, row) is None
    else:
        monkeypatch.setenv("REVALIDATE_URL", "")
        assert revalidate.notify_changed([row.slug])["status"] == "unconfigured"
    db_session.flush()
    db_session.refresh(row)
    assert row.status == "withdrawn"
    assert row.closed_at == original_closed
    assert row.meta == original_meta


def test_scam_report_intake_and_founder_subject(client, db_session, monkeypatch):
    calls = []
    monkeypatch.setattr(reports.get_settings(), "waitlist_notify_email", "founder@example.com")
    monkeypatch.setattr(reports, "send_email", lambda **kw: calls.append(kw) or True)
    message = f"Fee demanded: {uuid.uuid4().hex}"
    response = client.post("/reports", json={"category": "scam", "message": message})
    assert response.status_code == 200
    assert (
        db_session.scalar(
            select(models.BugReport).where(models.BugReport.message == message)
        ).category
        == "scam"
    )
    assert calls[0]["subject"] == "Aspirova report: possible scam"


@pytest.mark.parametrize("merge_path", ["identity", "slug"])
def test_ingest_keeps_flagged_canonical_untouched(db_session, company, now, merge_path):
    source = models.Source(slug=f"saved-ingest-{uuid.uuid4().hex}", name="Safety test", type="ats")
    db_session.add(source)
    db_session.flush()
    raw = RawListing(
        source_slug="test",
        external_id="unsafe-1",
        source_url="https://example.com/careers/intern",
        content_hash="changed",
        raw_payload={"title": "Changed upstream"},
    )
    normalized = NormalizedListing(
        source_slug="test",
        external_id="unsafe-1",
        source_url=raw.source_url,
        title="Software Engineering Intern",
        company_name=company.name,
        category="internship",
        apply_url=raw.source_url,
        description_raw="A changed upstream description that must not erase the safety notice.",
    )
    row = flagged(db_session, company, now)
    if merge_path == "identity":
        db_session.add(
            models.RawListing(
                source_id=source.id,
                external_id=raw.external_id,
                source_url=raw.source_url,
                content_hash="old",
                raw_payload={},
                opportunity_id=row.id,
            )
        )
    elif merge_path == "slug":
        row.slug = _make_opportunity_slug(company.name, normalized.title, raw)
        # Missing company anchor bypasses fuzzy matching so the deterministic slug
        # safety net is exercised independently of fuzzy matching.
    db_session.flush()
    state = load_board_state(db_session, source.id, company.id)
    original = (row.meta, row.closed_at, row.description_raw, row.apply_url)
    result, created = ingest_one(
        db_session, state, source.id, None if merge_path == "slug" else company.id, raw, normalized
    )
    db_session.flush()
    db_session.refresh(row)
    assert result.id == row.id and not created
    assert row.status == "withdrawn"
    assert (row.meta, row.closed_at, row.description_raw, row.apply_url) == original


def test_new_source_posting_does_not_merge_into_withdrawn_listing(db_session, company, now):
    original_source = models.Source(
        slug=f"saved-original-{uuid.uuid4().hex}", name="Original source", type="ats"
    )
    new_source = models.Source(
        slug=f"saved-new-{uuid.uuid4().hex}", name="Another source", type="ats"
    )
    db_session.add_all([original_source, new_source])
    db_session.flush()
    withdrawn = flagged(db_session, company, now, primary_source=original_source.slug)
    flag_listing(
        db_session, slug=withdrawn.slug, kind="recalled", note="Previous intake recalled.", now=now
    )
    db_session.add(
        models.RawListing(
            source_id=original_source.id,
            external_id="previous-intake",
            source_url=withdrawn.apply_url,
            content_hash="previous",
            raw_payload={},
            opportunity_id=withdrawn.id,
        )
    )
    db_session.flush()
    original = (withdrawn.meta, withdrawn.closed_at, withdrawn.description_raw, withdrawn.apply_url)
    raw = RawListing(
        source_slug=new_source.slug,
        external_id="next-intake",
        source_url="https://example.com/careers/next-intake",
        content_hash="new-intake",
        raw_payload={"title": withdrawn.title},
    )
    normalized = NormalizedListing(
        source_slug=new_source.slug,
        external_id=raw.external_id,
        source_url=raw.source_url,
        title=withdrawn.title,
        company_name=company.name,
        category="internship",
        apply_url=raw.source_url,
        description_raw="A genuine later intake with the same title.",
    )
    state = load_board_state(db_session, new_source.id, company.id)
    result, created = ingest_one(db_session, state, new_source.id, company.id, raw, normalized)
    db_session.flush()
    db_session.refresh(withdrawn)
    assert created and result.id != withdrawn.id
    assert result.status == "active"
    assert result.closed_at is None
    assert safety_flag(result) is None
    assert withdrawn.status == "withdrawn"
    assert (
        withdrawn.meta,
        withdrawn.closed_at,
        withdrawn.description_raw,
        withdrawn.apply_url,
    ) == original


def test_safety_without_source_never_links_to_apply_url(
    db_session, company, now, user, mail, client
):
    unsafe = listing(db_session, company, now)
    flag_listing(
        db_session, slug=unsafe.slug, kind="scam", note="An unauthorised fee request.", now=now
    )
    save(db_session, user, unsafe, now)
    notifications.send_closing_soon_alerts(db_session, now=now)
    email = next(call for call in mail if call["to"] == user.email)
    for part in (email["html"], email["text"]):
        assert unsafe.apply_url not in part
        assert "Read the source of this warning" not in part
        assert f"/opportunity/{unsafe.slug}" in part
        assert "An unauthorised fee request." in part
    response = client.get("/notifications")
    assert response.status_code == 200
    item = next(item for item in response.json()["items"] if item["type"] == "saved_safety")
    assert item["opportunity_slug"] == unsafe.slug
    assert unsafe.apply_url not in response.text


def test_withdrawn_excluded_from_public_surfaces(db_session, company, now, client, mail, user):
    from api.filters import saved_search_base_filters
    from api.sitemap import SITEMAP_PAGE_SIZE, _eligible_sitemap_opportunity_filters
    from scripts.notify_google_indexing import select_opened_candidates
    from scripts.post_telegram import select_candidates

    # Leave closed_at NULL deliberately: these checks must use withdrawal itself,
    # not accidentally rely on the ordinary closure exclusion.
    unsafe = flagged(db_session, company, now, first_seen_at=now - timedelta(hours=1))
    unsafe.closed_at = None
    unsafe.posted_at = now - timedelta(hours=1)
    active = listing(
        db_session, company, now, closed_at=None, first_seen_at=now - timedelta(hours=1)
    )
    db_session.flush()
    for url in (
        f"/feed?company={company.slug}",
        f"/search?q=Software&company={company.slug}",
        f"/company/{company.slug}",
    ):
        response = client.get(url)
        assert response.status_code == 200, response.text
        slugs = {item["slug"] for item in response.json()["items"]}
        assert unsafe.slug not in slugs
        assert active.slug in slugs
    earlier = db_session.scalar(
        select(func.count(models.Opportunity.id)).where(
            models.Opportunity.id < active.id, *_eligible_sitemap_opportunity_filters()
        )
    )
    sitemap = client.get(f"/sitemap-opportunities?page={earlier // SITEMAP_PAGE_SIZE}")
    assert sitemap.status_code == 200
    assert unsafe.slug not in {item["slug"] for item in sitemap.json()}
    assert active.slug in {item["slug"] for item in sitemap.json()}
    since = now - timedelta(days=1)
    generic = notifications._generic_recent_opportunities(db_session, since, 100, now)
    assert unsafe.id not in {row.id for row in generic}
    db_session.add(
        models.DreamCompany(
            user_id=user.id, company_id=company.id, created_at=now - timedelta(days=2)
        )
    )
    db_session.flush()
    followed = notifications._dream_company_opportunities(db_session, user.id, since, now)
    assert unsafe.id not in {row.id for row in followed}
    notifications.send_company_alerts(db_session, now=now)
    email = next(call for call in mail if call["to"] == user.email)
    assert unsafe.slug not in email["html"] + email["text"]
    assert active.slug in email["html"] + email["text"]
    search_matches = list(
        db_session.scalars(
            select(models.Opportunity.id).where(
                models.Opportunity.company_id == company.id, *saved_search_base_filters({})
            )
        )
    )
    assert active.id in search_matches and unsafe.id not in search_matches
    assert unsafe.id not in {row.id for row in select_candidates(db_session)}
    assert unsafe.id not in {
        row.opportunity_id for row in select_opened_candidates(db_session, 100)
    }


def test_breaker_cancels_pending_email_for_a_held_candidate(
    db_session, company, now, user, mail, monkeypatch
):
    closed = listing(db_session, company, now)
    save(db_session, user, closed, now)
    sender = notifications.send_email
    monkeypatch.setattr(notifications, "send_email", lambda *a, **kw: False)
    notifications.send_closing_soon_alerts(db_session, now=now)
    original_id = notices(db_session, user)[0].id
    monkeypatch.setattr(notifications, "send_email", sender)
    monkeypatch.setattr(get_settings(), "saved_closure_notice_breaker", 0)
    notifications.send_closing_soon_alerts(db_session, now=now)
    assert not any(call["to"] == user.email for call in mail)
    assert not notices(db_session, user)[0].meta["email_pending"]
    monkeypatch.setattr(get_settings(), "saved_closure_notice_breaker", 1500)
    notifications.send_closing_soon_alerts(db_session, now=now)
    assert notices(db_session, user)[0].id == original_id
    assert not any(call["to"] == user.email for call in mail)


def test_withdrawn_survives_closed_listing_cleanup(db_session, company, now, user):
    unsafe = flagged(
        db_session,
        company,
        now,
        closed_at=now - timedelta(days=30),
        deadline=now - timedelta(days=31),
    )
    save(db_session, user, unsafe, now)
    ordinary = listing(db_session, company, now, closed_at=now - timedelta(days=30))
    ordinary_id = ordinary.id
    cleanup_expired_competitions(db_session, now=now)
    db_session.expire_all()
    assert db_session.get(models.Opportunity, ordinary_id) is None
    assert db_session.get(models.Opportunity, unsafe.id).status == "withdrawn"
    assert db_session.get(models.Bookmark, (user.id, unsafe.id)) is not None
