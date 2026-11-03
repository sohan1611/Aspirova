import json
import uuid
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from core import models
from scripts import backfill_competition_signals as backfill


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


def test_transform_preserves_other_keys_and_handles_missing_raw_payload():
    meta = {
        "prize": "$0",
        "prize_inr": 1000,
        "prize_text": "stale",
        "team_size": 4,
        "summary_source": "extracted",
    }
    before = deepcopy(meta)
    assert backfill.transform_meta(meta, "hackathon", "unstop", None) == {
        "prize": "$0",
        "team_size": 4,
        "summary_source": "extracted",
    }
    assert backfill.transform_meta(meta, "hackathon", "unstop", {}) == {
        "prize": "$0",
        "summary_source": "extracted",
    }
    assert meta == before


def test_backfill_dry_run_apply_and_second_run(db_session, monkeypatch):
    monkeypatch.setattr(backfill, "BATCH_SIZE", 1)
    suffix = uuid.uuid4().hex
    source = models.Source(slug=f"team-backfill-{suffix}", adapter_key="unstop")
    db_session.add(source)
    db_session.flush()
    rows = [
        models.Opportunity(
            slug=f"competition-backfill-{index}-{suffix}",
            title="Competition backfill",
            category=category,
            primary_source=primary_source,
            apply_url=f"https://example.com/backfill/{index}/{suffix}",
            meta=meta,
        )
        for index, (category, primary_source, meta) in enumerate(
            [
                (
                    "competition",
                    "unstop",
                    {
                        "prizes": [{"cash": "1000", "currency": "fa-dollar"}],
                        "team_size": 99,
                        "keep": "yes",
                    },
                ),
                ("hackathon", "devpost", {"prize": "$0", "prize_inr": 100, "keep": "yes"}),
                ("scholarship", "unstop", {"prize": "€8,000", "keep": "yes"}),
                ("job", "unstop", {"prize": "$1,000", "keep": "yes"}),
            ]
        )
    ]
    db_session.add_all(rows)
    db_session.flush()
    payload = json.loads(
        (Path(__file__).parent / "fixtures" / "unstop_team_sample.json").read_text(encoding="utf-8")
    )
    now = datetime.now(UTC)
    db_session.add_all(
        [
            models.RawListing(
                source_id=source.id,
                opportunity_id=rows[0].id,
                external_id=f"old-{suffix}",
                raw_payload={"regnRequirements": {"max_team_size": 99}},
                crawled_at=now - timedelta(days=1),
            ),
            models.RawListing(
                source_id=source.id,
                opportunity_id=rows[0].id,
                external_id=f"latest-{suffix}",
                raw_payload=payload,
                crawled_at=now,
            ),
        ]
    )
    ids = [row.id for row in rows]
    before = [deepcopy(row.meta) for row in rows]
    db_session.commit()

    def stored_meta():
        return list(
            db_session.scalars(
                select(models.Opportunity.meta)
                .where(models.Opportunity.id.in_(ids))
                .order_by(models.Opportunity.id)
            )
        )

    dry = backfill.backfill_competition_signals(db_session)
    assert dry["would_change"] >= 3
    assert stored_meta() == before
    applied = backfill.backfill_competition_signals(db_session, apply=True)
    assert applied == dry
    assert stored_meta() == [
        {**before[0], "prize_inr": 88000, "prize_text": "$1,000", "team_min": 1, "team_size": 4},
        {"prize": "$0", "keep": "yes"},
        {**before[2], "prize_inr": 800000, "prize_text": "€8,000"},
        before[3],
    ]
    assert backfill.backfill_competition_signals(db_session, apply=True)["would_change"] == 0
    row = db_session.get(models.Opportunity, ids[0])
    row.meta = {**row.meta, "prize_text": "stale"}
    db_session.commit()
    repaired = backfill.backfill_competition_signals(db_session, apply=True)
    assert repaired["would_change"] == repaired["prize_changed"] == 1
    assert stored_meta()[0]["prize_text"] == "$1,000"
    assert backfill.backfill_competition_signals(db_session, apply=True)["would_change"] == 0
