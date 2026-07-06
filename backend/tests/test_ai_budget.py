"""Integration tests for the daily AI spend guardrail."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from core import models
from core.ai_budget import is_over_budget
from core.config import get_settings


@pytest.fixture
def db_session(engine):
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def test_daily_budget_empty_then_over_cap(db_session: Session, monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "ai_daily_usd_cap", 2.0)
    db_session.execute(delete(models.AiUsage))
    db_session.flush()

    assert is_over_budget(db_session) is False

    db_session.add(
        models.AiUsage(
            created_at=datetime.now(timezone.utc),
            feature="test-budget",
            model="stub",
            input_tokens=0,
            output_tokens=0,
            est_cost=settings.ai_daily_usd_cap + 0.01,
            ok=True,
        )
    )
    db_session.flush()

    assert is_over_budget(db_session) is True
