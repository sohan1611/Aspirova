"""Destination write seams and backfill against a disposable PostgreSQL database."""

import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import delete, event, update
from sqlalchemy.orm import Session

from core import models
from api.opportunity_loading import opportunity_list_load_options
from api.schemas import OpportunityDetail, OpportunityListItem
from core.destination_facts import classify_destination_facts, url_key
from pipeline import liveness
from scripts.backfill_destination_facts import backfill_destination_facts
from scripts.destination_eval import sample_rows


@pytest.fixture
def listing(engine):
    suffix = uuid.uuid4().hex
    with Session(engine) as session:
        company = models.Company(
            slug=f"trust01-{suffix}",
            name="Synthetic trust test",
            domain="example.com",
            ats_type="lever",
            ats_board_id="acme",
        )
        session.add(company)
        session.flush()
        row = models.Opportunity(
            slug=f"trust01-{suffix}",
            title="Synthetic intern",
            company_id=company.id,
            category="internship",
            apply_url="https://jobs.lever.co/acme/1",
            primary_source="lever",
            meta={"summary_source": "ai"},
            last_seen_at=datetime.now(timezone.utc) - timedelta(days=8),
        )
        session.add(row)
        session.commit()
        row_id, company_id = row.id, company.id
    try:
        yield row_id
    finally:
        with engine.begin() as connection:
            connection.execute(delete(models.Opportunity).where(models.Opportunity.id == row_id))
            connection.execute(delete(models.Company).where(models.Company.id == company_id))


def test_orm_insert_update_and_source_change(engine, listing):
    with Session(engine) as session:
        row = session.get(models.Opportunity, listing)
        assert row.destination_facts["employer_verified"]
        original = row.destination_facts
        observation = {
            "url_key": url_key(row.apply_url),
            "status": "sign_in_required",
            "checked_at": "2026-11-24T00:00:00+00:00",
            "warnings": [],
        }
        row.destination_facts = classify_destination_facts(
            row.apply_url,
            "example.com",
            source="lever",
            company_id=row.company_id,
            ats_type="lever",
            ats_board_id="acme",
            computed_at=original["computed_at"],
            observation=observation,
        )
        session.flush()
        assert row.destination_facts["status"] == "sign_in_required"
        row.apply_url = "https://jobs.lever.co/other/2"
        row.primary_source = "github_lists"
        session.flush()
        facts = row.destination_facts
        assert not facts["employer_verified"] and facts["status"] == "unchecked"
        assert facts["checked_at"] is None
        assert facts["aggregator_warning"] and row.meta == {"summary_source": "ai"}


def test_meta_only_changes_and_unchanged_ingest_never_rewrite_destination(engine, listing):
    with Session(engine) as session:
        row = session.get(models.Opportunity, listing)
        before = row.destination_facts.copy()
        connection = session.connection()
        statements = []

        def capture(_connection, _cursor, statement, _parameters, _context, _many):
            statements.append(statement.lower())

        event.listen(connection, "before_cursor_execute", capture)
        try:
            row.meta = {"summary_source": "ai", "prize": "$1,000"}
            session.flush()
            assert row.destination_facts == before
            assert all("destination_facts" not in sql for sql in statements)
            statements.clear()
            row.apply_url = row.apply_url
            session.flush()
            models.refresh_destination_for_opportunity(connection, row)
            session.flush()
            assert row.destination_facts == before
            assert not any(sql.startswith("update opportunities") for sql in statements)
        finally:
            event.remove(connection, "before_cursor_execute", capture)


def test_backfill_read_only_default_then_idempotent_apply(engine, listing):
    with engine.begin() as connection:
        connection.execute(
            update(models.Opportunity)
            .where(models.Opportunity.id == listing)
            .values(destination_facts=None)
        )
    before = backfill_destination_facts(engine)
    assert before["pending"] >= 1 and before["updated"] == 0
    with Session(engine) as session:
        assert session.get(models.Opportunity, listing).destination_facts is None
    applied = backfill_destination_facts(engine, batch=2, dry_run=False)
    assert applied["updated"] >= 1
    with Session(engine) as session:
        facts = session.get(models.Opportunity, listing).destination_facts
    assert backfill_destination_facts(engine, dry_run=False)["updated"] == 0
    with Session(engine) as session:
        row = session.get(models.Opportunity, listing)
        assert row.meta == {"summary_source": "ai"} and row.destination_facts == facts
    with engine.connect().execution_options(postgresql_readonly=True) as connection:
        with connection.begin(), Session(bind=connection) as session:
            assert connection.exec_driver_sql("SHOW transaction_read_only").scalar() == "on"
            assert any(row["id"] == listing for row in sample_rows(session, 100))


def test_api_load_profile_serializes_column_without_lazy_reads(engine, listing):
    from sqlalchemy import select

    with Session(engine) as session:
        row = session.scalar(
            select(models.Opportunity)
            .where(models.Opportunity.id == listing)
            .options(*opportunity_list_load_options())
        )
        statements = []

        def capture(_connection, _cursor, statement, _parameters, _context, _many):
            statements.append(statement)

        connection = session.connection()
        event.listen(connection, "before_cursor_execute", capture)
        try:
            result = OpportunityListItem.from_model(row)
            assert result.destination_facts == row.destination_facts
            assert result.meta == {"summary_source": "ai"}
            assert not statements
        finally:
            event.remove(connection, "before_cursor_execute", capture)
        session.refresh(row)
        assert OpportunityDetail.from_model(row).destination_facts == row.destination_facts


def test_loaded_company_edits_override_cached_evidence_in_the_same_transaction(engine, listing):
    with Session(engine) as session:
        row = session.get(models.Opportunity, listing)
        models.refresh_destination_for_opportunity(session.connection(), row)
        row.company.ats_board_id = "other"
        session.flush()
        row.apply_url = "https://jobs.lever.co/acme/new"
        session.flush()
        assert not row.destination_facts["employer_verified"]


@pytest.mark.parametrize(
    "code,status,closed",
    [
        (404, "gone", True),
        (410, "gone", True),
        (401, "sign_in_required", False),
        (403, "sign_in_required", False),
        (503, "unknown", False),
    ],
)
def test_liveness_persists_observations_through_existing_closure_path(
    engine,
    listing,
    monkeypatch,
    code,
    status,
    closed,
):
    real_client = httpx.Client
    original = liveness.inspect_destination
    monkeypatch.setattr(
        liveness,
        "inspect_destination",
        lambda *args, **kwargs: original(*args, resolve=lambda *_: True, **kwargs),
    )
    active_session = None

    def respond(_request):
        assert not active_session.in_transaction(), "HTTP must not hold a database transaction"
        return httpx.Response(code)

    monkeypatch.setattr(
        liveness.httpx,
        "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    with Session(engine) as session:
        active_session = session
        preloaded = session.get(models.Opportunity, listing)
        computed_at = preloaded.destination_facts["computed_at"]
        liveness.check_listing_liveness(session, apply=True, limit=1)
        session.expire_all()
        row = session.get(models.Opportunity, listing)
        assert row is preloaded and "liveness_checked_at" in row.meta
        assert row.destination_facts["status"] == status
        assert row.destination_facts["computed_at"] == computed_at
        assert row.destination_facts["checked_at"] is not None
        assert (row.closed_at is not None) is closed
        assert row.meta["summary_source"] == "ai" and "destination_facts" not in row.meta


def test_company_evidence_change_is_lazy_without_relocking_opportunities(engine, listing):
    with Session(engine) as session:
        row = session.get(models.Opportunity, listing)
        before = row.destination_facts.copy()
        company = row.company
        statements = []

        def capture(_connection, _cursor, statement, _parameters, _context, _many):
            statements.append(statement.lower())

        connection = session.connection()
        event.listen(connection, "before_cursor_execute", capture)
        try:
            company.ats_board_id = "other"
            session.flush()
            assert not any(sql.startswith("update opportunities") for sql in statements)
        finally:
            event.remove(connection, "before_cursor_execute", capture)
        session.commit()
        assert row.destination_facts == before
    assert backfill_destination_facts(engine, dry_run=False)["updated"] >= 1
    with Session(engine) as session:
        row = session.get(models.Opportunity, listing)
        assert not row.destination_facts["employer_verified"]
        assert row.destination_facts["input_key"] != before["input_key"]
        assert row.meta == {"summary_source": "ai"}


def test_old_check_cannot_close_a_replaced_url(engine, listing):
    def replace_before_result(url):
        with engine.begin() as connection:
            connection.execute(
                update(models.Opportunity)
                .where(models.Opportunity.id == listing)
                .values(apply_url="https://jobs.lever.co/acme/new")
            )
        return "closed"

    with Session(engine) as session:
        result = liveness.check_listing_liveness(session, apply=True, checker=replace_before_result)
        assert result.closed == 0
        assert session.get(models.Opportunity, listing).closed_at is None
