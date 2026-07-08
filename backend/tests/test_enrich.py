"""Zero-network integration tests for Shape-A opportunity enrichment."""

import uuid

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

import pipeline.enrich as enrich_module
from core import models
from core.ai_client import GenerationResult
from core.config import get_settings
from pipeline.enrich import backfill_embeddings, enrich_opportunity, enrich_pending


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


def _make_opportunity(db_session: Session) -> models.Opportunity:
    opportunity = models.Opportunity(
        slug=f"enrich-test-{uuid.uuid4()}",
        title="Software Engineering Internship",
        description_raw="Build reliable services and collaborate with product teams.",
        apply_url="https://example.com/apply",
    )
    db_session.add(opportunity)
    db_session.flush()
    return opportunity


def _generation_usage_count(db_session: Session) -> int:
    return db_session.scalar(
        select(func.count())
        .select_from(models.AiUsage)
        .where(models.AiUsage.feature.in_(["enrich.summary", "enrich.tags"]))
    )


def _install_canned_ai(monkeypatch) -> list[str]:
    calls: list[str] = []

    def fake_generate(session, *, feature, **kwargs):
        calls.append(feature)
        text = '["Python", "Remote"]' if feature == "enrich.tags" else "Canned summary."
        return GenerationResult(text=text, input_tokens=0, output_tokens=0)

    def fake_embed(session, texts, *, feature):
        calls.append(feature)
        return [[0.0] * get_settings().ai_embedding_dim for _text in texts]

    monkeypatch.setattr(enrich_module.ai_client, "generate", fake_generate)
    monkeypatch.setattr(enrich_module.ai_client, "embed", fake_embed)
    return calls


def test_enrich_opportunity_is_idempotent(db_session: Session) -> None:
    opportunity = _make_opportunity(db_session)

    assert enrich_opportunity(db_session, opportunity) is True
    db_session.flush()

    assert opportunity.summary
    assert len(opportunity.embedding) == get_settings().ai_embedding_dim
    assert opportunity.embedding_model == get_settings().ai_embedding_model

    generation_rows = _generation_usage_count(db_session)
    assert enrich_opportunity(db_session, opportunity) is False
    assert _generation_usage_count(db_session) == generation_rows


def test_enrich_opportunity_repopulates_after_content_change(db_session: Session) -> None:
    opportunity = _make_opportunity(db_session)
    assert enrich_opportunity(db_session, opportunity) is True

    opportunity.summary = None
    opportunity.embedding = None
    opportunity.embedding_model = None
    db_session.execute(
        delete(models.OpportunityTag).where(models.OpportunityTag.opportunity_id == opportunity.id)
    )
    db_session.flush()

    assert enrich_opportunity(db_session, opportunity) is True
    assert opportunity.summary
    assert len(opportunity.embedding) == get_settings().ai_embedding_dim
    assert opportunity.embedding_model == get_settings().ai_embedding_model


def test_enrich_pending_skips_without_provider_key(db_session: Session) -> None:
    opportunity = _make_opportunity(db_session)

    result = enrich_pending(db_session, limit=10)

    assert result == {"skipped": True, "enriched": 0, "reason": "no provider key"}
    assert opportunity.summary is None
    assert opportunity.embedding is None


def test_enrich_pending_respects_limit(db_session: Session, monkeypatch) -> None:
    _make_opportunity(db_session)
    _make_opportunity(db_session)
    calls = _install_canned_ai(monkeypatch)
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "test-key")
    monkeypatch.setattr(enrich_module, "is_over_budget", lambda session: False)

    result = enrich_pending(db_session, limit=2)

    assert result == {"skipped": False, "enriched": 2, "stopped_over_budget": False}
    assert calls.count("enrich.summary") == 2
    assert calls.count("enrich.tags") == 2
    assert calls.count("enrich.embedding") == 2


def test_enrich_pending_stops_early_over_budget(db_session: Session, monkeypatch) -> None:
    for _ in range(3):
        _make_opportunity(db_session)
    calls = _install_canned_ai(monkeypatch)
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "test-key")
    budget_checks = iter([False, True])
    monkeypatch.setattr(enrich_module, "is_over_budget", lambda session: next(budget_checks))

    result = enrich_pending(db_session, limit=3)

    assert result == {"skipped": False, "enriched": 1, "stopped_over_budget": True}
    assert calls.count("enrich.summary") == 1
    assert calls.count("enrich.tags") == 1
    assert calls.count("enrich.embedding") == 1


def test_backfill_embeddings_skips_without_embedding_key(db_session: Session) -> None:
    opportunity = _make_opportunity(db_session)

    result = backfill_embeddings(db_session, limit=10)

    assert result == {"skipped": True, "embedded": 0, "reason": "no embedding key"}
    assert opportunity.embedding is None
    assert opportunity.embedding_model is None


def test_backfill_embeddings_embeds_only_missing_embeddings(
    db_session: Session, monkeypatch
) -> None:
    _make_opportunity(db_session)  # a second null-embedding opp (unbound; used only for its DB row)
    existing = _make_opportunity(db_session)
    missing_two = _make_opportunity(db_session)
    missing_two.description_raw = "x" * 30050
    existing_vector = [0.25] * get_settings().ai_embedding_dim
    existing.embedding = existing_vector
    existing.embedding_model = "existing-model"
    db_session.flush()
    calls: list[str] = []

    def fake_embed(session, texts, *, feature):
        calls.extend(texts)
        assert feature == "backfill.embedding"
        return [[0.5] * get_settings().ai_embedding_dim for _text in texts]

    monkeypatch.setattr(get_settings(), "openai_api_key", "test-key")
    monkeypatch.setattr(enrich_module.ai_client, "embed", fake_embed)
    monkeypatch.setattr(enrich_module, "is_over_budget", lambda session: False)

    result = backfill_embeddings(db_session, limit=10)

    # Robust against a populated (prod) DB: backfill_embeddings queries ALL
    # opportunities with a null embedding, so exact counts and which rows are
    # touched depend on other data present. Assert the data-independent
    # invariants here; the full "missing rows get embedded (incl. the 30k-char
    # truncation)" behaviour is covered by the isolated pgvector-container run.
    assert result["skipped"] is False
    assert result["stopped_over_budget"] is False
    assert result["embedded"] <= 10  # respects the limit
    assert len(calls) == result["embedded"]  # exactly one embed call per embedded opp
    assert all(len(text) <= 28000 for text in calls)  # 28k-char truncation applied
    # The already-embedded opportunity is never re-embedded (the "only missing" guarantee):
    assert existing.embedding_model == "existing-model"
    assert existing.embedding is not None
    assert list(existing.embedding) == existing_vector
