"""TRUST-05: run against the reviewer's throwaway Postgres, never production."""

import re
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from api import middleware, reports
from api.deps import get_db
from api.main import app
from core import models, report_receipts
from core.account_deletion import OWNED_MODELS
from core.adapters import NormalizedListing, RawListing
from crawlers.runner import _reopen_seen_inventory_listings, _reopen_seen_rolling_listings
from pipeline import liveness
from pipeline.ingest import _make_opportunity_slug, ingest_one, load_board_state
from pipeline.reopen import reopen_estimate
from pipeline.retirement import reopen_government_extension
from scripts import reports as cli
from scripts.cleanup_expired_competitions import cleanup_expired_competitions
from scripts.fix_garbage_deadlines import fix_garbage_deadlines
from scripts.flag_listing import flag_listing
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
        slug=f"triage-{uuid.uuid4().hex}", name="Triage Co", name_normalized="triage co"
    )
    db_session.add(row)
    db_session.flush()
    return row


@pytest.fixture
def user(db_session):
    row = models.User(email=f"triage-{uuid.uuid4().hex}@example.com")
    db_session.add(row)
    db_session.flush()
    return row


def listing(session, company, now, **values):
    row = models.Opportunity(
        **{
            "slug": f"triage-{uuid.uuid4().hex}",
            "title": "Engineering Intern",
            "title_normalized": "engineering intern",
            "company_id": company.id,
            "apply_url": "https://example.com/apply",
            "category": "internship",
            "description_raw": "Build Python software with the engineering team.",
            "last_seen_at": now,
            "first_seen_at": now - timedelta(days=2),
            **values,
        }
    )
    session.add(row)
    session.flush()
    return row


def report(session, opportunity=None, user=None, **values):
    row = report_receipts.store_report(
        session,
        message="PRIVATE REPORT",
        category="wrong_info",
        opportunity_id=opportunity.id if opportunity else None,
        user_id=user.id if user else None,
        **values,
    )
    return row


@pytest.fixture
def client(db_session, monkeypatch):
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[reports.get_optional_current_user] = lambda: None
    monkeypatch.setattr(reports, "get_redis", lambda: None)
    monkeypatch.setattr(middleware, "get_redis", lambda: None)
    monkeypatch.setattr(reports.get_settings(), "waitlist_notify_email", "")
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


@pytest.mark.parametrize("category", cli.CATEGORIES)
def test_intake_receipt_and_private_lookup(client, db_session, category):
    response = client.post(
        "/reports",
        json={
            "category": category,
            "message": "PRIVATE MESSAGE",
            "contact_email": "private@example.com",
            "page_url": "https://private.example.com",
        },
    )
    assert response.status_code == 200
    receipt = response.json()
    assert receipt["ok"] is True
    assert re.fullmatch(report_receipts.REFERENCE_PATTERN, receipt["reference"])
    data = client.get(f"/reports/status/{receipt['reference']}").json()
    assert set(data) == {
        "reference",
        "category",
        "status",
        "created_at",
        "triaged_at",
        "resolved_at",
        "resolution",
        "resolution_note",
        "listing_slug",
        "listing_title",
    }
    assert data["status"] == "open" and data["category"] == category
    assert "PRIVATE" not in str(data) and "private.example" not in str(data)
    assert client.get("/reports/status/R-INVALID").status_code == 404


def test_reference_collision_retries_savepoint(db_session, monkeypatch):
    existing = report(db_session)
    references = iter([existing.reference, "R-ABC234"])
    monkeypatch.setattr(report_receipts, "new_reference", lambda: next(references))
    another = report(db_session)
    assert another.reference == "R-ABC234"
    assert existing.reference != another.reference
    assert db_session.get(models.BugReport, existing.id) is not None


def test_founder_email_has_receipt_listing_count_and_command(
    client, db_session, company, now, monkeypatch
):
    opportunity = listing(db_session, company, now)
    report(db_session, opportunity)
    calls = []
    monkeypatch.setattr(reports.get_settings(), "waitlist_notify_email", "founder@example.com")
    monkeypatch.setattr(reports, "send_email", lambda **kw: calls.append(kw) or True)
    response = client.post(
        "/reports",
        json={
            "category": "scam",
            "message": "Fee requested",
            "opportunity_slug": opportunity.slug,
        },
    )
    receipt = response.json()["reference"]
    assert len(calls) == 1 and calls[0]["to"] == "founder@example.com"
    assert calls[0]["subject"] == "Aspirova report: possible scam"
    for part in (calls[0]["html"], calls[0]["text"]):
        for value in (
            receipt,
            opportunity.title,
            opportunity.slug,
            "2",
            f"uv run python -m scripts.reports show {receipt}",
        ):
            assert value in part


def test_status_lookup_rate_limit(client, db_session, monkeypatch):
    row = report(db_session)
    monkeypatch.setattr(reports.get_settings(), "rate_limit_ip_report_per_minute", 1)
    assert client.get(f"/reports/status/{row.reference}").status_code == 200
    assert client.get(f"/reports/status/{row.reference}").status_code == 429


@pytest.mark.parametrize(
    "action,field,resolution",
    [
        ({"close_listing": True}, "closed_at", "closed_listing"),
        ({"set_deadline": "2026-12-01"}, "deadline", "corrected"),
        ({"withdraw": True, "kind": "scam"}, "safety", "withdrawn"),
        ({"withdraw": True, "kind": "recalled"}, "safety", "withdrawn"),
        ({"duplicate_of": "target"}, "duplicate_of", "duplicate"),
        ({"company": "target"}, "company_id", "corrected"),
    ],
)
def test_resolution_actions_atomic_and_idempotent(
    db_session, company, user, now, action, field, resolution
):
    opportunity = listing(db_session, company, now, meta={"custom": "keep"})
    original = listing(db_session, company, now)
    target = models.Company(slug=f"other-triage-{uuid.uuid4().hex}", name="Correct Co")
    db_session.add(target)
    db_session.flush()
    action = {**action}
    if "duplicate_of" in action:
        action["duplicate_of"] = original.slug
    if "company" in action:
        action["company"] = target.slug
    row = report(db_session, opportunity, user)
    with db_session.begin_nested() as transaction:
        result, slug, changed = cli.resolve_report(
            db_session,
            row.reference,
            resolution=resolution,
            note="Verified by founder.",
            now=now,
            **action,
        )
        assert changed and slug == opportunity.slug
        assert (
            result.status == "resolved" and result.triaged_at == now and result.resolved_at == now
        )
        assert result.correction == opportunity.meta["corrections"]
        assert field in {item["field"] for item in result.correction}
        assert {d["report"] for d in result.correction} == {row.reference}
        assert "PRIVATE REPORT" not in str(opportunity.meta)
        assert opportunity.meta["custom"] == "keep"
        notice = db_session.scalar(
            select(models.Notification).where(
                models.Notification.type == "report_resolved",
                models.Notification.user_id == user.id,
            )
        )
        assert notice.meta == {
            "reference": row.reference,
            "resolution": resolution,
            "note": "Verified by founder.",
            "slug": opportunity.slug,
        }
        assert (
            cli.resolve_report(
                db_session,
                row.reference,
                resolution=resolution,
                note="Verified by founder.",
                now=now,
                **action,
            )[2]
            is False
        )
        assert (
            db_session.scalar(
                select(func.count(models.Notification.id)).where(
                    models.Notification.user_id == user.id,
                    models.Notification.type == "report_resolved",
                )
            )
            == 1
        )
        if field == "deadline":
            assert opportunity.deadline.isoformat() == "2026-12-01T18:29:59+00:00"
            assert opportunity.deadline_confidence == "explicit"
        if field == "company_id":
            assert opportunity.company_id == target.id
        transaction.rollback()
    db_session.refresh(row)
    db_session.refresh(opportunity)
    assert row.status == "open" and row.correction is None and row.resolved_at is None
    assert opportunity.meta == {"custom": "keep"} and opportunity.closed_at is None
    assert (
        db_session.scalar(
            select(func.count(models.Notification.id)).where(
                models.Notification.user_id == user.id,
            )
        )
        == 0
    )


@pytest.mark.parametrize("resolution", cli.RESOLUTIONS)
def test_resolve_without_action_and_triage(db_session, resolution, now):
    row = report(db_session)
    assert cli.triage_report(db_session, row.reference, note="Being checked", now=now)
    assert not cli.triage_report(db_session, row.reference, now=now + timedelta(hours=1))
    assert row.triaged_at == now
    cli.resolve_report(
        db_session,
        row.reference,
        resolution=resolution,
        note="Checked",
        now=now + timedelta(hours=2),
    )
    assert row.correction == []
    with pytest.raises(ValueError, match="resolved"):
        cli.triage_report(db_session, row.reference)


@pytest.mark.parametrize(
    "action",
    [
        {"duplicate_of": "missing-listing"},
        {"company": "missing-company"},
        {"set_deadline": "not-a-date"},
        {"withdraw": True},
        {"close_listing": True, "set_deadline": "2026-12-01"},
    ],
)
def test_invalid_resolution_does_not_change_report(db_session, company, now, action):
    opportunity = listing(db_session, company, now)
    row = report(db_session, opportunity)
    with pytest.raises(ValueError):
        cli.resolve_report(
            db_session, row.reference, resolution="corrected", note="Checked", **action
        )
    assert row.status == "open" and row.resolved_at is None and opportunity.meta is None


def test_duplicate_cannot_point_to_itself(db_session, company, now):
    opportunity = listing(db_session, company, now)
    row = report(db_session, opportunity)
    with pytest.raises(ValueError, match="differ"):
        cli.resolve_report(
            db_session,
            row.reference,
            resolution="duplicate",
            note="Checked",
            duplicate_of=opportunity.slug,
        )


def test_detail_only_exposes_sanitized_corrections(client, db_session, company, now):
    opportunity = listing(db_session, company, now)
    row = report(db_session, opportunity, contact_email="private@example.com")
    cli.resolve_report(
        db_session,
        row.reference,
        resolution="corrected",
        note="Deadline checked",
        set_deadline="2026-12-01",
        now=now,
    )
    data = client.get(f"/opportunity/{opportunity.slug}").json()
    assert set(data["corrections"][0]) == {"at", "field", "summary"}
    assert data["corrections"][0]["summary"] == "deadline changed after a reader report."
    assert "PRIVATE REPORT" not in str(data) and "private@example" not in str(data)
    assert row.reference not in str(data)
    assert "deadline_override" not in (data["meta"] or {})


@pytest.mark.parametrize("identity", ["anonymous", "user", "deleted"])
def test_resolution_notification_and_contact_email(
    db_session, user, now, identity, monkeypatch, client
):
    calls = []
    owner = user if identity != "anonymous" else None
    if identity == "deleted":
        user.deleted_at = now
        user.email = None
    row = report(db_session, user=owner, contact_email="contact@example.com")
    monkeypatch.setattr(cli, "send_email", lambda **kw: calls.append(kw) or True)
    cli.resolve_report(
        db_session, row.reference, resolution="no_change", note="No change needed", now=now
    )
    assert cli.send_resolution_email(db_session, row.reference) is (identity != "deleted")
    notices = list(
        db_session.scalars(
            select(models.Notification).where(
                models.Notification.user_id == user.id,
                models.Notification.type == "report_resolved",
            )
        )
    )
    assert bool(notices) is (identity == "user")
    assert bool(calls) is (identity != "deleted")
    if calls:
        assert len(calls) == 1 and calls[0]["to"] == "contact@example.com"
        for part in (calls[0]["html"], calls[0]["text"]):
            assert row.reference in part and "No change needed" in part
            assert f"/report/status?ref={row.reference}" in part
    if notices:
        from api.notifications import _notification_copy

        assert _notification_copy("report_resolved", None, None, notices[0].meta) == (
            "Your report was resolved",
            f"{row.reference}: No change needed",
        )
    assert models.BugReport in OWNED_MODELS


def test_no_contact_means_no_resolution_email(db_session, user, now, monkeypatch):
    row = report(db_session, user=user)
    monkeypatch.setattr(cli, "send_email", lambda **kw: pytest.fail("Unexpected email"))
    cli.resolve_report(db_session, row.reference, resolution="spam", note="Closed", now=now)
    assert not cli.send_resolution_email(db_session, row.reference)


def test_queue_show_stats_remind(db_session, company, now, monkeypatch):
    # Isolate the cohort and backlog within this test's rolled-back transaction.
    db_session.execute(delete(models.BugReport))
    opportunity = listing(db_session, company, now)
    first = report(db_session, opportunity, created_at=now - timedelta(days=10))
    cli.triage_report(db_session, first.reference, now=first.created_at + timedelta(hours=24))
    cli.resolve_report(
        db_session,
        first.reference,
        resolution="no_change",
        note="Checked",
        now=first.created_at + timedelta(hours=48),
    )
    second = report(db_session, opportunity, created_at=now - timedelta(days=9))
    cli.triage_report(db_session, second.reference, now=second.created_at + timedelta(hours=72))
    cli.resolve_report(
        db_session,
        second.reference,
        resolution="corrected",
        note="Checked",
        now=second.created_at + timedelta(hours=192),
    )
    pending = report(db_session, opportunity, created_at=now - timedelta(days=4))
    triaged = report(db_session, opportunity, created_at=now - timedelta(days=8))
    cli.triage_report(db_session, triaged.reference, now=triaged.created_at + timedelta(hours=24))
    recent = report(db_session, created_at=now - timedelta(hours=1))
    metrics = cli.report_stats(db_session, days=30, now=now)
    assert metrics["by_status"] == {"resolved": 2, "open": 2, "triaged": 1}
    assert metrics["by_category"] == {"wrong_info": 5}
    assert metrics["by_resolution"] == {"no_change": 1, "corrected": 1}
    assert metrics["triaged_at"]["median_hours"] == 24
    assert metrics["triaged_at"]["p90_hours"] == pytest.approx(62.4)
    assert metrics["triaged_at"]["within_sla_percent"] == 50
    assert metrics["resolved_at"]["median_hours"] == 120
    assert metrics["resolved_at"]["p90_hours"] == pytest.approx(177.6)
    assert metrics["resolved_at"]["within_sla_percent"] == pytest.approx(100 / 3)
    assert metrics["open_overdue"] == 2
    queue = cli.list_reports(db_session, status="all", category="wrong_info", now=now)
    assert {r["reference"] for r in queue if r["sla"] == "OVERDUE"} == {
        pending.reference,
        triaged.reference,
    }
    assert len(cli.list_reports(db_session, status="resolved", limit=1)) == 1
    detail = cli.show_report(db_session, first.reference)
    assert detail["message"] == "PRIVATE REPORT" and detail["listing"]["slug"] == opportunity.slug
    assert len(detail["other_reports"]) == 3
    calls = []
    monkeypatch.setattr(cli.get_settings(), "waitlist_notify_email", "founder@example.com")
    monkeypatch.setattr(cli, "send_email", lambda **kw: calls.append(kw) or True)
    assert cli.remind(db_session, now=now)
    assert (
        len(calls) == 1
        and pending.reference in calls[0]["text"]
        and triaged.reference in calls[0]["text"]
    )
    assert first.reference not in calls[0]["text"] and recent.reference not in calls[0]["text"]
    cli.resolve_report(
        db_session, pending.reference, resolution="no_change", note="Checked", now=now
    )
    cli.resolve_report(
        db_session, triaged.reference, resolution="no_change", note="Checked", now=now
    )
    assert not cli.remind(db_session, now=now) and len(calls) == 1


@pytest.fixture
def cli_session(db_session, engine, monkeypatch):
    monkeypatch.setattr(cli, "make_engine", lambda: engine)
    monkeypatch.setattr(
        cli,
        "Session",
        lambda _: Session(
            bind=db_session.connection(),
            join_transaction_mode="create_savepoint",
        ),
    )
    monkeypatch.setattr(engine, "dispose", lambda: None)


@pytest.mark.parametrize(
    "action",
    [
        ["--close-listing"],
        ["--set-deadline", "2026-12-01"],
        ["--withdraw", "--kind", "scam"],
        ["--duplicate-of", "target"],
        ["--company", "target"],
        [],
    ],
)
def test_cli_dry_run_and_post_commit_delivery(
    db_session, company, now, cli_session, monkeypatch, action, capsys
):
    opportunity = listing(db_session, company, now)
    original = listing(db_session, company, now)
    row = report(db_session, opportunity, contact_email="contact@example.com")
    action = [
        (
            original.slug
            if x == "target" and "--duplicate-of" in action
            else company.slug if x == "target" else x
        )
        for x in action
    ]
    callbacks = []
    monkeypatch.setattr(
        cli,
        "refresh_api_details",
        lambda slugs: callbacks.append(("refresh", slugs)) or {"status": "test"},
    )

    def notify(slugs, *, landing):
        assert landing is False
        callbacks.append(("revalidate", slugs))
        return {"status": "test"}

    monkeypatch.setattr(cli, "notify_changed", notify)

    def send(**kw):
        # Outcome is visible outside the command's transaction before any email.
        db_session.expire_all()
        assert db_session.get(models.BugReport, row.id).status == "resolved"
        callbacks.append(("email", kw))
        return True

    monkeypatch.setattr(cli, "send_email", send)
    args = ["resolve", row.reference, "--resolution", "corrected", "--note", "Checked", *action]
    cli.main([*args, "--dry-run"])
    db_session.expire_all()
    assert db_session.get(models.BugReport, row.id).status == "open"
    assert db_session.get(models.Opportunity, opportunity.id).closed_at is None
    assert not callbacks
    cli.main(args)
    cli.main(args)
    assert [item[0] for item in callbacks].count("email") == 1
    if action:
        assert [item[0] for item in callbacks[:2]] == ["refresh", "revalidate"]
    else:
        assert [item[0] for item in callbacks] == ["email"]
    assert '"changed": false' in capsys.readouterr().out


def test_all_read_and_triage_cli_commands(db_session, cli_session, now, monkeypatch, capsys):
    row = report(db_session, created_at=now)
    monkeypatch.setattr(cli, "send_email", lambda **kw: pytest.fail("Not overdue"))
    for args in (
        ["list", "--status", "all", "--category", "wrong_info", "--limit", "1"],
        ["show", row.reference],
        ["stats", "--days", "30"],
        ["remind"],
        ["triage", row.reference, "--note", "Checking", "--dry-run"],
    ):
        cli.main(args)
        assert capsys.readouterr().out
    db_session.refresh(row)
    assert row.status == "open"
    cli.main(["triage", row.reference])
    db_session.refresh(row)
    assert row.status == "triaged"


@pytest.mark.parametrize("reason", ["user_report", "duplicate"])
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
        "cleanup",
        "clear_safety",
    ],
)
def test_manual_closure_survives_every_path(db_session, company, now, reason, path_name):
    opportunity = listing(
        db_session,
        company,
        now,
        closed_at=now - timedelta(days=30),
        primary_source="himalayas",
        meta={"closed_reason": reason},
    )
    old = opportunity.closed_at
    if path_name == "inventory":
        _reopen_seen_inventory_listings(db_session, [opportunity.id])
    elif path_name == "rolling":
        _reopen_seen_rolling_listings(db_session, [opportunity.id])
    elif path_name == "government":
        opportunity.primary_source = "meity_careers"
        opportunity.deadline = old - timedelta(days=1)
        assert not reopen_government_extension(
            opportunity, "meity_careers", now + timedelta(days=1), now=now
        )
    elif path_name == "repair_windowed":
        reopen(db_session, since=old.date())
    elif path_name == "repair_ttl":
        reopen_rolling_ttl(db_session, closed_on=old.date(), apply=True)
    elif path_name == "liveness":
        liveness._mark_closed(db_session, opportunity_ids=[opportunity.id], detected_at=now)
        liveness._stamp_checked(db_session, [opportunity.id], now)
    elif path_name == "estimate":
        assert reopen_estimate(db_session, opportunity) is None
    elif path_name == "cleanup":
        cleanup_expired_competitions(db_session, now=now)
    else:
        # A safety clear cannot reverse a later manual closure even if its time matches.
        opportunity.closed_at = None
        flag_listing(db_session, slug=opportunity.slug, kind="scam", note="Checked", now=old)
        flag_listing(db_session, slug=opportunity.slug, clear=True)
    db_session.flush()
    db_session.refresh(opportunity)
    assert opportunity.closed_at == old and opportunity.meta.get("closed_reason") == reason
    assert "liveness_checked_at" not in opportunity.meta


@pytest.mark.parametrize("merge_path", ["identity", "slug", "fuzzy"])
@pytest.mark.parametrize("category", ["internship", "hackathon"])
def test_ingest_preserves_deadline_company_and_meta(
    db_session, company, now, merge_path, category, monkeypatch
):
    source = models.Source(slug=f"triage-ingest-{uuid.uuid4().hex}", name="Test", type="ats")
    db_session.add(source)
    db_session.flush()
    raw = RawListing(
        source_slug="test",
        external_id="test-1",
        source_url="https://example.com/test",
        content_hash="new",
        raw_payload={"changed": True},
    )
    normalized = NormalizedListing(
        source_slug="test",
        external_id=raw.external_id,
        source_url=raw.source_url,
        title="Engineering Intern",
        company_name=company.name,
        category=category,
        apply_url=raw.source_url,
        deadline=now + timedelta(days=2),
        deadline_confidence="inferred",
        description_raw="Work on Python software.",
        meta={"deadline_override": {"value": "bad"}, "corrections": []},
    )
    opportunity = listing(db_session, company, now, category=category, primary_source="test")
    row = report(db_session, opportunity)
    cli.resolve_report(
        db_session,
        row.reference,
        resolution="corrected",
        note="Date checked",
        set_deadline="2027-01-01",
        now=now,
    )
    # A company override must survive both identity and slug cache misses.
    corrected_company = models.Company(
        slug=f"correct-triage-{uuid.uuid4().hex}", name="Correct employer"
    )
    db_session.add(corrected_company)
    db_session.flush()
    company_report = report(db_session, opportunity)
    cli.resolve_report(
        db_session,
        company_report.reference,
        resolution="corrected",
        note="Employer checked",
        company=corrected_company.slug,
        now=now,
    )
    expected = {
        k: opportunity.meta[k] for k in ("deadline_override", "company_override", "corrections")
    }
    if merge_path == "identity":
        db_session.add(
            models.RawListing(
                source_id=source.id,
                external_id=raw.external_id,
                source_url=raw.source_url,
                content_hash="old",
                raw_payload={},
                opportunity_id=opportunity.id,
            )
        )
    elif merge_path == "slug":
        opportunity.slug = _make_opportunity_slug(company.name, normalized.title, raw)
        monkeypatch.setattr("pipeline.ingest.find_matching_opportunity", lambda *a, **kw: None)
    else:
        monkeypatch.setattr(
            "pipeline.ingest.find_matching_opportunity", lambda *a, **kw: opportunity
        )
    db_session.flush()
    # Deliberately load without a company: corrected companies can leave the original cache.
    state = load_board_state(db_session, source.id, None)
    result, created = ingest_one(db_session, state, source.id, None, raw, normalized)
    db_session.flush()
    db_session.refresh(opportunity)
    assert result.id == opportunity.id and not created
    assert opportunity.company_id == corrected_company.id
    assert opportunity.deadline == cli.deadline_at_end_of_day("2027-01-01")
    assert opportunity.deadline_confidence == "explicit"
    assert all(opportunity.meta[k] == v for k, v in expected.items())
    fix_garbage_deadlines(db_session, cutoff=now)
    db_session.refresh(opportunity)
    assert opportunity.deadline == cli.deadline_at_end_of_day("2027-01-01")


@pytest.mark.parametrize("merge_path", ["identity", "slug", "fuzzy"])
@pytest.mark.parametrize("reason", ["user_report", "duplicate"])
def test_ingest_preserves_manual_closure(db_session, company, now, merge_path, reason, monkeypatch):
    source = models.Source(slug=f"triage-closed-{uuid.uuid4().hex}", name="Test", type="ats")
    db_session.add(source)
    db_session.flush()
    raw = RawListing(
        source_slug="test",
        external_id="closed-1",
        source_url="https://example.com/closed",
        content_hash="changed",
        raw_payload={},
    )
    normalized = NormalizedListing(
        source_slug="test",
        external_id=raw.external_id,
        source_url=raw.source_url,
        title="Engineering Intern",
        company_name=company.name,
        category="internship",
        apply_url=raw.source_url,
        description_raw="A longer upstream description that cannot clear the manual closure.",
    )
    opportunity = listing(db_session, company, now, closed_at=now, meta={"closed_reason": reason})
    if merge_path == "identity":
        db_session.add(
            models.RawListing(
                source_id=source.id,
                external_id=raw.external_id,
                source_url=raw.source_url,
                content_hash="old",
                raw_payload={},
                opportunity_id=opportunity.id,
            )
        )
    elif merge_path == "slug":
        opportunity.slug = _make_opportunity_slug(company.name, normalized.title, raw)
        monkeypatch.setattr("pipeline.ingest.find_matching_opportunity", lambda *a, **kw: None)
    else:
        monkeypatch.setattr(
            "pipeline.ingest.find_matching_opportunity", lambda *a, **kw: opportunity
        )
    db_session.flush()
    state = load_board_state(db_session, source.id, company.id)
    result, created = ingest_one(db_session, state, source.id, company.id, raw, normalized)
    db_session.flush()
    db_session.refresh(opportunity)
    assert not created and result.id == opportunity.id
    assert opportunity.closed_at == now and opportunity.meta == {"closed_reason": reason}


def test_sla_calculation_unit_with_fixed_timestamps():
    now = datetime(2026, 11, 17, tzinfo=timezone.utc)

    def item(age, triage=None, resolve=None, status="open"):
        created = now - timedelta(hours=age)
        return SimpleNamespace(
            created_at=created,
            triaged_at=created + timedelta(hours=triage) if triage is not None else None,
            resolved_at=created + timedelta(hours=resolve) if resolve is not None else None,
            status=status,
            category="wrong_info",
            resolution="corrected" if resolve is not None else None,
        )

    rows = [
        item(240, 24, 48, "resolved"),
        item(216, 72, 192, "resolved"),
        item(192, 24, status="triaged"),
        item(96),
        item(1),
    ]

    class FakeSession:
        def scalars(self, query):
            return rows

    stats = cli.report_stats(FakeSession(), now=now)
    assert stats["triaged_at"]["median_hours"] == 24
    assert stats["triaged_at"]["p90_hours"] == pytest.approx(62.4)
    assert stats["triaged_at"]["within_sla_percent"] == 50
    assert stats["resolved_at"]["median_hours"] == 120
    assert stats["resolved_at"]["p90_hours"] == pytest.approx(177.6)
    assert stats["resolved_at"]["within_sla_percent"] == pytest.approx(100 / 3)
    assert stats["open_overdue"] == 2
    assert not cli.overdue(item(48), now)
    assert cli.overdue(item(48.01), now)
    assert not cli.overdue(item(168, 1, status="triaged"), now)
    assert cli.overdue(item(168.01, 1, status="triaged"), now)


def test_empty_sla_and_reminder_unit(monkeypatch):
    class EmptySession:
        def scalars(self, query):
            return []

    monkeypatch.setattr(cli, "send_email", lambda **kw: pytest.fail("Unexpected email"))
    metrics = cli.report_stats(EmptySession())
    assert metrics["total"] == 0 and metrics["open_overdue"] == 0
    assert metrics["triaged_at"]["median_hours"] is None
    assert metrics["resolved_at"]["within_sla_percent"] is None
    assert not cli.remind(EmptySession())


def _linked_board(db_session, company, now, count):
    """A source whose raw listings and provenance already link `count` rows."""
    source = models.Source(slug=f"triage-bulk-{uuid.uuid4().hex}", name="Test", type="ats")
    db_session.add(source)
    db_session.flush()
    opportunities = [listing(db_session, company, now, primary_source="test") for _ in range(count)]
    raws = [
        models.RawListing(
            source_id=source.id,
            external_id=str(index),
            source_url=f"https://example.com/{index}",
            content_hash="unchanged",
            raw_payload={},
            opportunity_id=opportunity.id,
            processed=True,
        )
        for index, opportunity in enumerate(opportunities)
    ]
    db_session.add_all(raws)
    db_session.flush()
    db_session.add_all(
        models.OpportunitySource(
            opportunity_id=opportunity.id,
            source_id=source.id,
            source_url=raw.source_url,
            raw_listing_id=raw.id,
            is_primary=True,
        )
        for opportunity, raw in zip(opportunities, raws)
    )
    db_session.flush()
    return source, opportunities


def _ingest_board_listing(db_session, state, source, company, opportunity, index, content_hash):
    raw = RawListing(
        source_slug="test",
        external_id=str(index),
        source_url=f"https://example.com/{index}",
        content_hash=content_hash,
        raw_payload={},
    )
    normalized = NormalizedListing(
        source_slug="test",
        external_id=str(index),
        source_url=raw.source_url,
        title=f"Changed {opportunity.title}" if content_hash != "unchanged" else opportunity.title,
        company_name=company.name,
        apply_url=raw.source_url,
        description_raw="",
    )
    seen = set()
    ingest_one(db_session, state, source.id, company.id, raw, normalized, seen_opportunity_ids=seen)
    return seen


def _record_statements(db_session):
    from sqlalchemy import event

    statements = []

    def record(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(db_session.bind, "before_cursor_execute", record)
    return statements, lambda: event.remove(db_session.bind, "before_cursor_execute", record)


def _founder_closes_after_load(db_session, opportunity, now):
    """A founder's write after the board loaded, invisible to the ORM cache."""
    from sqlalchemy import update

    db_session.execute(
        update(models.Opportunity)
        .where(models.Opportunity.id == opportunity.id)
        .values(closed_at=now, meta={"closed_reason": "user_report"})
        .execution_options(synchronize_session=False)
    )


def test_unchanged_listings_take_no_lock_and_keep_manual_edits(db_session, company, now):
    source, opportunities = _linked_board(db_session, company, now, 2)
    state = load_board_state(db_session, source.id, company.id)
    _founder_closes_after_load(db_session, opportunities[0], now)
    statements, stop = _record_statements(db_session)
    try:
        for index, opportunity in enumerate(opportunities):
            _ingest_board_listing(
                db_session, state, source, company, opportunity, index, "unchanged"
            )
        db_session.flush()
    finally:
        stop()
    # An unchanged listing writes nothing canonical: no lock, no per-listing SQL.
    assert statements == []
    db_session.refresh(opportunities[0])
    assert opportunities[0].closed_at == now
    assert opportunities[0].meta["closed_reason"] == "user_report"


def test_changed_listing_locks_one_row_and_keeps_manual_edit(db_session, company, now):
    source, opportunities = _linked_board(db_session, company, now, 2)
    original_title = opportunities[0].title
    state = load_board_state(db_session, source.id, company.id)
    _founder_closes_after_load(db_session, opportunities[0], now)
    statements, stop = _record_statements(db_session)
    try:
        for index, opportunity in enumerate(opportunities):
            _ingest_board_listing(db_session, state, source, company, opportunity, index, "changed")
        db_session.flush()
    finally:
        stop()
    locks = [s for s in statements if "FROM opportunities" in s and "FOR UPDATE" in s]
    assert len(locks) == 2
    assert all(" IN " not in lock for lock in locks)
    db_session.refresh(opportunities[0])
    # Re-checked under the lock: the founder's closure and the title survive.
    assert opportunities[0].closed_at == now
    assert opportunities[0].meta["closed_reason"] == "user_report"
    assert opportunities[0].title == original_title
    db_session.refresh(opportunities[1])
    assert opportunities[1].title.startswith("Changed ")


def test_multi_batch_board_locks_only_changed_rows(db_session, company, now):
    db_session.expire_on_commit = False  # as crawl_company_board's sessions
    source, opportunities = _linked_board(db_session, company, now, 60)
    state = load_board_state(db_session, source.id, company.id)
    changed = {7, 41}
    seen = set()
    statements, stop = _record_statements(db_session)
    try:
        for index, opportunity in enumerate(opportunities):
            content_hash = "changed" if index in changed else "unchanged"
            seen |= _ingest_board_listing(
                db_session, state, source, company, opportunity, index, content_hash
            )
            if (index + 1) % 25 == 0:
                # crawl_company_board commits every 25 listings; each commit used
                # to re-lock and re-read every row of the board.
                db_session.commit()
        db_session.flush()
    finally:
        stop()
    locks = [s for s in statements if "FROM opportunities" in s and "FOR UPDATE" in s]
    assert len(locks) == len(changed)
    assert all(" IN " not in lock for lock in locks)
    assert seen == {opportunity.id for opportunity in opportunities}
    for index in changed:
        db_session.refresh(opportunities[index])
        assert opportunities[index].title.startswith("Changed ")


def test_public_correction_sanitization_unit():
    from core.listing_corrections import public_corrections, public_listing_meta

    history = {
        "corrections": [
            None,
            {"field": []},
            {"field": "deadline", "at": "bad"},
            {
                "field": "deadline",
                "at": "2026-11-17T10:00:00Z",
                "old": "PRIVATE",
                "new": "PRIVATE",
                "report": "R-ABC234",
                "message": "PRIVATE",
            },
        ],
        "deadline_override": {"report": "R-ABC234"},
        "company_override": {"report": "R-ABC234"},
        "duplicate_of": "original",
    }
    assert public_corrections(["legacy"]) == []
    corrections = public_corrections(history)
    assert len(corrections) == 1
    assert set(corrections[0]) == {"at", "field", "summary"}
    assert "PRIVATE" not in str(corrections) and "R-ABC234" not in str(corrections)
    assert public_listing_meta(history) == {"duplicate_of": "original"}


def test_deleted_account_purges_report_before_email(db_session, user, now, monkeypatch):
    from core.account_deletion import tombstone_account

    row = report(db_session, user=user, contact_email="private@example.com")
    reference = row.reference
    cli.resolve_report(db_session, reference, resolution="no_change", note="Checked", now=now)
    tombstone_account(db_session, user.id)
    monkeypatch.setattr(cli, "send_email", lambda **kw: pytest.fail("Deleted reporter was emailed"))
    assert not cli.send_resolution_email(db_session, reference)
    assert (
        db_session.scalar(
            select(models.BugReport.id).where(models.BugReport.reference == reference)
        )
        is None
    )


def test_deadline_end_of_day_unit():
    assert cli.deadline_at_end_of_day("2026-11-17").isoformat() == "2026-11-17T18:29:59+00:00"
    for value in ("20261117", "2026-W47-2", "2026-02-30"):
        with pytest.raises(ValueError):
            cli.deadline_at_end_of_day(value)
