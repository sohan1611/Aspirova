"""Fixture-only transforms and dry-run/apply coverage on the local test DB."""

import json
import uuid
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from core import models
from scripts import backfill_role_signals as backfill
from scripts.backfill_role_signals import transform_row


def test_transform_preserves_unstop_pay_and_unrelated_fields():
    before = {
        "title": "Part-time Intern",
        "category": "internship",
        "country": "IN",
        "description_raw": "Stipend: ₹10,000/month\nDuration: 6 months\nPPO",
        "meta": {
            "compensation": {"unpaid": True, "source": "unstop"},
            "summary_source": "ai",
            "skills": ["Python"],
        },
        "summary": "Untouched",
        "closed_at": None,
    }
    snapshot = deepcopy(before)
    after = transform_row(before)
    assert after == {
        "meta": {**before["meta"], "duration_months": 6, "part_time": True, "job_offer": True}
    }
    assert before == snapshot
    assert transform_row({**before, **after}) == after


def test_transform_adds_pay_and_preserves_null_for_no_signal():
    assert transform_row({"category": "job", "meta": None}) == {"meta": None}
    after = transform_row({"category": "job", "description_raw": "Salary $130,000–150,000"})
    assert after == {
        "meta": {
            "compensation": {
                "min": 130000,
                "max": 150000,
                "currency": "USD",
                "period": "year",
                "source": "text",
            }
        }
    }


def test_transform_removes_last_stale_text_key():
    row = {"category": "job", "meta": {"compensation": {"source": "text", "max": 800}}}
    assert transform_row(row) == {"meta": {}}
    assert transform_row({**row, "meta": {}}) == {"meta": {}}


@pytest.fixture
def db_session(engine):
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.mark.parametrize("batch_size", [1, 2, 500])
def test_backfill_dry_run_apply_and_idempotence(db_session, monkeypatch, capsys, batch_size):
    fixtures = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((Path(__file__).parent / "fixtures" / "pay").glob("*-*.json"))
    ]
    specs = [
        {
            **fixture,
            "meta": {"compensation": fixture["previous_compensation"], "keep": ["Python"]},
        }
        for fixture in fixtures
    ]
    structured = {"min": 800, "max": 800, "currency": "USD", "period": "hour"}
    specs += [
        {"meta": {"compensation": {**structured, "source": source}, "keep": True}}
        for source in ("unstop", "structured", None)
    ]
    specs += [
        {"title": "Paid internship", "meta": {"compensation": {**structured, "source": "text"}}},
        {"description_raw": "Salary $25/hour", "meta": {"keep": True}},
        {"meta": None},
        {"category": "competition", "meta": {"compensation": {**structured, "source": "text"}}},
    ]
    suffix = uuid.uuid4().hex
    rows = []
    for index, spec in enumerate(specs):
        row = models.Opportunity(
            slug=f"pay-backfill-{suffix}-{index}",
            title=spec.get("title", "Intern"),
            description_raw=spec.get("description_raw", "Salary $800/hour"),
            category=spec.get("category", "internship"),
            country=spec.get("country"),
            apply_url=f"https://example.com/{suffix}/{index}",
            meta=spec.get("meta"),
            is_hidden=index == 0,
            closed_at=datetime.now(UTC) if index == 1 else None,
        )
        db_session.add(row)
        rows.append(row)
    db_session.flush()
    ids = [row.id for row in rows]
    before = [deepcopy(row.meta) for row in rows]
    db_session.commit()
    monkeypatch.setattr(backfill, "BATCH_SIZE", batch_size)
    # Isolate this test's rows while exercising the real batching and writes.
    monkeypatch.setattr(
        backfill, "select", lambda *columns: select(*columns).where(models.Opportunity.id.in_(ids))
    )

    def stored_meta():
        return list(
            db_session.scalars(
                select(models.Opportunity.meta)
                .where(models.Opportunity.id.in_(ids))
                .order_by(models.Opportunity.id)
            )
        )

    dry = backfill.backfill_role_signals(db_session)
    assert dry["scanned"] == 12
    assert dry["would_change"] == dry["compensation"] == 8
    assert dry["amounts_removed"] == 6
    assert dry["period_changes"] == 1
    assert stored_meta() == before
    output = capsys.readouterr().out
    assert "total checked: 12" in output
    assert "would change: 8" in output
    assert "amounts removed: 6" in output
    assert "period changes: 1" in output
    assert '"before"' in output and '"after"' in output

    assert backfill.backfill_role_signals(db_session, apply=True) == dry
    after = stored_meta()
    for index, fixture in enumerate(fixtures):
        expected = {"keep": ["Python"]}
        if fixture["expected_compensation"]:
            expected["compensation"] = fixture["expected_compensation"]
        assert after[index] == expected
    assert after[6:9] == before[6:9]
    assert after[9] == {"compensation": {"paid": True, "source": "text"}}
    assert after[10]["compensation"]["max"] == 25
    assert after[11:] == before[11:]
    assert "changed: 8" in capsys.readouterr().out
    again = backfill.backfill_role_signals(db_session, apply=True)
    assert again["scanned"] == 12
    assert again["would_change"] == again["amounts_removed"] == again["period_changes"] == 0
