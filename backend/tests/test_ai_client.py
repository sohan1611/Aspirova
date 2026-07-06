"""Zero-cost tests for the single generation/embedding provider seam."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from core import models
from core.ai_client import embed, generate
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


@pytest.fixture(autouse=True)
def blank_ai_keys(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(settings, "ai_embedding_dim", 1536)


def test_generate_uses_stub_and_writes_one_usage_row(db_session: Session) -> None:
    feature = f"test-generate-{uuid.uuid4()}"

    result = generate(db_session, feature=feature, prompt="Summarize this opportunity.")

    rows = list(
        db_session.scalars(select(models.AiUsage).where(models.AiUsage.feature == feature)).all()
    )
    assert result.text
    assert len(rows) == 1
    assert rows[0].model == get_settings().ai_generation_model
    assert rows[0].ok is True


def test_embed_uses_stub_vectors_and_writes_one_usage_row(db_session: Session) -> None:
    feature = f"test-embed-{uuid.uuid4()}"

    vectors = embed(db_session, ["software engineering", "climate fellowship"], feature=feature)

    rows = list(
        db_session.scalars(select(models.AiUsage).where(models.AiUsage.feature == feature)).all()
    )
    assert len(vectors) == 2
    assert all(len(vector) == 1536 for vector in vectors)
    assert len(rows) == 1
    assert rows[0].model == get_settings().ai_embedding_model
    assert rows[0].ok is True
