"""Category repair preserves structured source signals and unrelated metadata."""

import uuid
from copy import deepcopy
from datetime import UTC, datetime

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from core import models
from scripts import backfill_new_grad_category as backfill


@pytest.mark.parametrize("source", sorted(backfill.TITLE_SOURCES))
@pytest.mark.parametrize(
    "title",
    [
        "Software Engineer, New Grad",
        "New College Grad Engineer",
        "Graduate Data Analyst",
        "Campus Recruiter - Dental Hygiene",
    ],
)
def test_title_sources_reclassify_only_removed_signals(source: str, title: str) -> None:
    before = {"title": title, "primary_source": source, "category": "internship", "meta": {"x": 1}}
    snapshot = deepcopy(before)
    assert backfill.transform_row(before) == {"category": "job"}
    assert before == snapshot
    assert backfill.transform_row({**before, "category": "job"}) == {}


@pytest.mark.parametrize(
    "source,payload",
    [
        ("arbeitnow", {"job_types": ["internship"]}),
        ("himalayas", {"seniority": ["Internship"]}),
        ("himalayas", {"experience": {"label": "Graduate Student"}}),
        ("himalayas", {"jobLevel": "Trainee"}),
        ("jobicy", {"jobLevel": "Apprentice"}),
    ],
)
def test_aggregators_keep_structured_internship_levels(source: str, payload: dict) -> None:
    row = {"title": "New Graduate Engineer", "primary_source": source, "category": "internship"}
    assert backfill.transform_row(row, payload) == {}


@pytest.mark.parametrize(
    "source,payload",
    [
        ("arbeitnow", {"job_types": ["Full-time"]}),
        ("himalayas", {"seniority": ["Entry-level"]}),
        ("himalayas", {"experience": {"label": "Junior"}}),
        ("himalayas", {"jobLevel": "Entry"}),
        ("jobicy", {"jobLevel": "Entry/Junior"}),
        ("arbeitnow", {}),
    ],
)
def test_aggregators_reclassify_with_raw_payload(source: str, payload: dict) -> None:
    row = {"title": "New Graduate Engineer", "primary_source": source, "category": "internship"}
    assert backfill.transform_row(row, payload) == {"category": "job"}
    assert backfill.transform_row(row) == {}


@pytest.mark.parametrize(
    "title,source,category",
    [
        ("New Graduate Engineer", "unstop", "internship"),
        ("New Graduate Engineer", "greenhouse", "job"),
        ("New Graduate Internship", "greenhouse", "internship"),
        ("Intern / New Grad Engineer", "greenhouse", "internship"),
        ("Graduate Student Researcher", "greenhouse", "internship"),
        ("Campus Ambassador", "greenhouse", "internship"),
        ("Graduate Trainee", "jobicy", "internship"),
        ("Software Engineer", "greenhouse", "internship"),
        ("New Graduate Engineer", "unknown", "internship"),
    ],
)
def test_protected_rows_are_untouched(title: str, source: str, category: str) -> None:
    assert (
        backfill.transform_row({"title": title, "primary_source": source, "category": category}, {})
        == {}
    )


@pytest.fixture
def db_session(engine):
    connection = engine.connect()
    transaction = connection.begin()
    # The script commits/rolls back its own batches; the outer transaction owns all fixtures.
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def test_dry_run_apply_and_rerun_with_provenance(db_session: Session, monkeypatch, capsys) -> None:
    suffix = uuid.uuid4().hex
    company = models.Company(slug=f"new-grad-backfill-{suffix}", name="Backfill Test")
    fixtures = [
        ("greenhouse", "Software Engineer, New Grad", "internship", None),
        ("lever", "Campus Recruiter - Dental Hygiene", "internship", None),
        ("arbeitnow", "Graduate Data Analyst", "internship", {"job_types": ["Full-time"]}),
        ("himalayas", "New Graduate Engineer", "internship", {"experience": ["Junior"]}),
        ("jobicy", "New Grad Engineer", "internship", {"jobLevel": "Entry/Junior"}),
        ("unstop", "New Grad Engineer", "internship", None),
        ("greenhouse", "New Graduate Internship", "internship", None),
        ("greenhouse", "New Grad Engineer", "job", None),
        ("himalayas", "Graduate Data Analyst", "internship", None),
        ("jobicy", "New Grad Engineer", "internship", {"jobLevel": "Internship"}),
        ("arbeitnow", "New Grad Engineer", "internship", None),
    ]
    rows = []
    for index, (source, title, category, payload) in enumerate(fixtures):
        row = models.Opportunity(
            slug=f"new-grad-backfill-{index}-{suffix}",
            title=title,
            title_normalized=title.lower(),
            company=company,
            primary_source=source,
            category=category,
            apply_url=f"https://example.com/backfill/{suffix}/{index}",
            closed_at=datetime.now(UTC) if index == 1 else None,
            status="expired" if index == 1 else "active",
            meta={"untouched": True},
        )
        db_session.add(row)
        db_session.flush()
        rows.append(row)
        if payload is not None:
            source_row = db_session.scalar(
                select(models.Source).where(models.Source.slug == source)
            )
            if source_row is None:
                source_row = models.Source(slug=source, name=source)
                db_session.add(source_row)
                db_session.flush()
            raw = models.RawListing(
                source_id=source_row.id,
                external_id=f"new-grad-backfill-{index}-{suffix}",
                source_url=row.apply_url,
                raw_payload=payload,
            )
            db_session.add(raw)
            db_session.flush()
            db_session.add(
                models.OpportunitySource(
                    opportunity_id=row.id,
                    source_id=source_row.id,
                    raw_listing_id=raw.id,
                    source_url=row.apply_url,
                    is_primary=True,
                )
            )
    # A payload belonging to another source must not repair an Arbeitnow row.
    wrong_source = db_session.scalar(select(models.Source).where(models.Source.slug == "jobicy"))
    wrong_raw = models.RawListing(
        source_id=wrong_source.id,
        external_id=f"wrong-source-{suffix}",
        raw_payload={},
    )
    db_session.add(wrong_raw)
    db_session.flush()
    db_session.add(
        models.OpportunitySource(
            opportunity_id=rows[-1].id,
            source_id=wrong_source.id,
            raw_listing_id=wrong_raw.id,
            source_url=rows[-1].apply_url,
        )
    )
    db_session.flush()
    ids = [row.id for row in rows]
    db_session.commit()

    real_select = backfill.select

    def select_fixture_rows(*entities):
        statement = real_select(*entities)
        if entities[0] is models.Opportunity.id:
            return statement.where(models.Opportunity.id.in_(ids))
        return statement

    monkeypatch.setattr(backfill, "select", select_fixture_rows)
    monkeypatch.setattr(backfill, "BATCH_SIZE", 2)
    expected_before = [fixture[2] for fixture in fixtures]
    writes = []

    def record_writes(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith(("INSERT ", "UPDATE ", "DELETE ")):
            writes.append(statement)

    event.listen(db_session.bind, "before_cursor_execute", record_writes)
    try:
        dry = backfill.backfill_new_grad_category(db_session)
    finally:
        event.remove(db_session.bind, "before_cursor_execute", record_writes)
    assert writes == []
    assert dry["scanned"] == 10
    assert dry["would_change"] == 5
    assert dry["skipped_no_raw"] == 2
    assert [
        db_session.get(models.Opportunity, row_id).category for row_id in ids
    ] == expected_before

    applied = backfill.backfill_new_grad_category(db_session, apply=True)
    assert applied == dry
    assert applied["by_source"]["himalayas"] == {
        "scanned": 2,
        "would_change": 1,
        "skipped_no_raw": 1,
    }
    db_session.expire_all()
    assert [db_session.get(models.Opportunity, row_id).category for row_id in ids] == [
        "job" if index < 5 else category for index, category in enumerate(expected_before)
    ]
    assert all(
        db_session.get(models.Opportunity, row_id).meta == {"untouched": True} for row_id in ids
    )
    assert db_session.get(models.Opportunity, ids[1]).closed_at is not None
    assert db_session.get(models.Opportunity, ids[1]).status == "expired"
    rerun = backfill.backfill_new_grad_category(db_session, apply=True)
    assert rerun["would_change"] == 0
    assert rerun["skipped_no_raw"] == 2
    output = capsys.readouterr().out
    for key in ("scanned", "would_change", "skipped_no_raw", "by_source"):
        assert key in output
    assert "Software Engineer, New Grad" in output
