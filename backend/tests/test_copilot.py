"""Integration tests for the gated, bounded, grounded Career Copilot."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import pipeline.copilot as copilot_pipeline
from api import copilot as copilot_api
from api.auth import get_current_user
from api.deps import get_db
from api.filters import STALE_AFTER_DAYS
from api.main import app
from core import models
from core.ai_client import GenerationResult
from core.config import get_settings
from pipeline.copilot import retrieve_context


class FakeAsyncRedis:
    """Minimal Upstash double for the Copilot limiter and answer cache."""

    def __init__(self) -> None:
        self._counters: dict[str, int] = {}
        self._store: dict[str, str] = {}

    async def eval(self, script, keys, args):
        key = keys[0]
        increment_by = int(args[1])
        self._counters[key] = self._counters.get(key, 0) + increment_by
        return self._counters[key]

    async def get(self, key):
        return self._store.get(key)

    async def set(self, key, value, ex=None, **kwargs):
        self._store[key] = value


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


@pytest.fixture
def fake_redis(monkeypatch) -> FakeAsyncRedis:
    fake = FakeAsyncRedis()
    monkeypatch.setattr(copilot_api, "get_redis", lambda: fake)
    monkeypatch.setattr(copilot_pipeline, "get_redis", lambda: fake)
    return fake


@pytest.fixture
def seeded(db_session: Session):
    free_plan = db_session.scalar(select(models.Plan).where(models.Plan.key == "free"))
    if free_plan is None:
        free_plan = models.Plan(key="free", price_paise=0, billing=None, features={})
        db_session.add(free_plan)
        db_session.flush()
    free_plan.features = {**free_plan.features, "copilot": False}

    suffix = str(uuid.uuid4())
    pro_plan = models.Plan(
        key=f"pro-copilot-test-{suffix}",
        price_paise=4900,
        billing="monthly",
        features={"copilot": True},
    )
    user = models.User(email=f"copilot-test-{suffix}@example.com")
    company = models.Company(
        slug=f"copilot-company-{suffix}",
        name=f"Copilot Company {suffix}",
        name_normalized=f"copilot company {suffix}",
    )
    query_vector = [0.0] * 1536
    query_vector[100] = 0.6
    query_vector[101] = 0.8
    nearest = models.Opportunity(
        slug=f"copilot-nearest-{suffix}",
        company=company,
        title=f"Vector Backend Internship {suffix}",
        summary="Build reliable APIs and distributed backend services.",
        apply_url=f"https://example.com/copilot/nearest/{suffix}",
        status="active",
        embedding=query_vector,
        embedding_model=get_settings().ai_embedding_model,
    )
    farthest = models.Opportunity(
        slug=f"copilot-farthest-{suffix}",
        title=f"Unrelated Design Internship {suffix}",
        apply_url=f"https://example.com/copilot/farthest/{suffix}",
        status="active",
        embedding=[-value for value in query_vector],
        embedding_model=get_settings().ai_embedding_model,
    )
    inactive = models.Opportunity(
        slug=f"copilot-inactive-{suffix}",
        title=f"Inactive Exact Match {suffix}",
        apply_url=f"https://example.com/copilot/inactive/{suffix}",
        status="closed",
        embedding=query_vector,
        embedding_model=get_settings().ai_embedding_model,
    )
    stale = models.Opportunity(
        slug=f"copilot-stale-{suffix}",
        title=f"Stale Exact Match {suffix}",
        apply_url=f"https://example.com/copilot/stale/{suffix}",
        status="active",
        posted_at=datetime.now(UTC) - timedelta(days=STALE_AFTER_DAYS + 1),
        embedding=query_vector,
        embedding_model=get_settings().ai_embedding_model,
    )
    missing_embedding = models.Opportunity(
        slug=f"copilot-no-embedding-{suffix}",
        title=f"Missing Embedding {suffix}",
        apply_url=f"https://example.com/copilot/missing/{suffix}",
        status="active",
        embedding=None,
    )
    db_session.add_all(
        [pro_plan, user, company, nearest, farthest, inactive, stale, missing_embedding]
    )
    db_session.flush()
    return {
        "pro_plan": pro_plan,
        "user": user,
        "query_vector": query_vector,
        "nearest": nearest,
        "farthest": farthest,
        "inactive": inactive,
        "stale": stale,
        "missing_embedding": missing_embedding,
    }


@pytest.fixture
def client(db_session, seeded, fake_redis):
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: seeded["user"]
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)


def _subscribe_pro(db_session: Session, seeded) -> None:
    db_session.add(
        models.Subscription(
            user_id=seeded["user"].id,
            plan_id=seeded["pro_plan"].id,
            status="active",
        )
    )
    db_session.flush()


def _keyed_retrieval(monkeypatch, seeded, calls: list[str]) -> None:
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "test-only-key")
    monkeypatch.setattr(copilot_pipeline.ai_budget, "is_over_budget", lambda _session: False)

    def fake_embed(session, texts, *, feature):
        assert feature == "copilot.retrieval"
        calls.append("embed")
        return [seeded["query_vector"] for _text in texts]

    monkeypatch.setattr(copilot_pipeline.ai_client, "embed", fake_embed)


def test_free_user_is_blocked_and_pro_user_is_allowed(
    client, db_session: Session, seeded, monkeypatch
) -> None:
    blocked = client.post("/copilot", json={"message": "What should I apply to?"})
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == copilot_api.PRO_FEATURE_DETAIL

    _subscribe_pro(db_session, seeded)
    monkeypatch.setattr(
        copilot_pipeline.ai_client,
        "generate",
        lambda *args, **kwargs: pytest.fail("unkeyed Copilot must not generate"),
    )
    allowed = client.post("/copilot", json={"message": "What should I apply to?"})
    assert allowed.status_code == 200
    assert allowed.json()["degraded"] is True


def test_unkeyed_returns_graceful_response_with_zero_ai_usage(
    client, db_session: Session, seeded, monkeypatch
) -> None:
    _subscribe_pro(db_session, seeded)
    baseline = db_session.scalar(select(func.count()).select_from(models.AiUsage))
    monkeypatch.setattr(
        copilot_pipeline.ai_client,
        "generate",
        lambda *args, **kwargs: pytest.fail("unkeyed Copilot must not generate"),
    )
    monkeypatch.setattr(
        copilot_pipeline.ai_client,
        "embed",
        lambda *args, **kwargs: pytest.fail("unkeyed Copilot must not retrieve"),
    )

    response = client.post("/copilot", json={"message": "Suggest an internship"})

    assert response.status_code == 200
    assert response.json() == {
        "answer": copilot_pipeline.COPILOT_UNAVAILABLE_ANSWER,
        "sources": [],
        "cached": False,
        "degraded": True,
    }
    assert db_session.scalar(select(func.count()).select_from(models.AiUsage)) == baseline


def test_keyed_answer_is_grounded_in_cosine_top_k(
    client, db_session: Session, seeded, monkeypatch
) -> None:
    _subscribe_pro(db_session, seeded)
    ai_calls: list[str] = []
    _keyed_retrieval(monkeypatch, seeded, ai_calls)
    captured: dict[str, str] = {}

    def fake_generate(session, *, feature, prompt=None, system=None, messages=None):
        assert session is db_session
        assert feature == "copilot.answer"
        assert messages is None
        ai_calls.append("generate")
        captured["prompt"] = prompt
        captured["system"] = system
        return GenerationResult(
            text=(f"Apply to {seeded['nearest'].title}: " f"{seeded['nearest'].apply_url}"),
            input_tokens=20,
            output_tokens=12,
        )

    monkeypatch.setattr(copilot_pipeline.ai_client, "generate", fake_generate)

    top_one = retrieve_context(db_session, "backend systems internship", k=1)
    assert [opportunity.slug for opportunity in top_one] == [seeded["nearest"].slug]

    response = client.post(
        "/copilot",
        json={"message": "Which backend systems internship should I apply to?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["degraded"] is False
    assert body["cached"] is False
    assert seeded["nearest"].title in body["answer"]
    assert seeded["nearest"].apply_url in body["answer"]
    assert seeded["nearest"].slug in {source["slug"] for source in body["sources"]}
    assert seeded["nearest"].title in captured["prompt"]
    assert seeded["nearest"].apply_url in captured["prompt"]
    assert seeded["inactive"].title not in captured["prompt"]
    assert seeded["stale"].title not in captured["prompt"]
    assert seeded["missing_embedding"].title not in captured["prompt"]
    assert "Never invent or fabricate" in captured["system"]
    assert "Keep the answer brief" in captured["system"]
    assert ai_calls == ["embed", "embed", "generate"]


def test_repeated_normalized_question_uses_cache_after_one_generation(
    client, db_session: Session, seeded, monkeypatch
) -> None:
    _subscribe_pro(db_session, seeded)
    ai_calls: list[str] = []
    _keyed_retrieval(monkeypatch, seeded, ai_calls)

    def fake_generate(session, *, feature, prompt=None, system=None, messages=None):
        ai_calls.append("generate")
        return GenerationResult(
            text=f"Consider {seeded['nearest'].title}.",
            input_tokens=10,
            output_tokens=6,
        )

    monkeypatch.setattr(copilot_pipeline.ai_client, "generate", fake_generate)

    first = client.post("/copilot", json={"message": "How do I find a Backend internship?"})
    second = client.post(
        "/copilot",
        json={"message": "  HOW   do I find a backend INTERNSHIP?  "},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["cached"] is False
    assert second.json()["cached"] is True
    assert second.json()["answer"] == first.json()["answer"]
    assert second.json()["sources"] == first.json()["sources"]
    assert ai_calls.count("generate") == 1
    assert ai_calls.count("embed") == 1


def test_daily_rate_limit_returns_429_after_configured_messages(
    client, db_session: Session, seeded, monkeypatch
) -> None:
    _subscribe_pro(db_session, seeded)
    monkeypatch.setattr(get_settings(), "rate_limit_user_copilot_per_day", 2)

    first = client.post("/copilot", json={"message": "First question"})
    second = client.post("/copilot", json={"message": "Second question"})
    third = client.post("/copilot", json={"message": "Third question"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429
    assert int(third.headers["Retry-After"]) >= 0


def test_over_budget_degrades_without_retrieval_or_generation(
    client, db_session: Session, seeded, monkeypatch
) -> None:
    _subscribe_pro(db_session, seeded)
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "test-only-key")
    monkeypatch.setattr(copilot_pipeline.ai_budget, "is_over_budget", lambda _session: True)
    monkeypatch.setattr(
        copilot_pipeline.ai_client,
        "generate",
        lambda *args, **kwargs: pytest.fail("over-budget Copilot must not generate"),
    )
    monkeypatch.setattr(
        copilot_pipeline.ai_client,
        "embed",
        lambda *args, **kwargs: pytest.fail("over-budget Copilot must not retrieve"),
    )

    response = client.post("/copilot", json={"message": "Find me a role"})

    assert response.status_code == 200
    assert response.json() == {
        "answer": copilot_pipeline.COPILOT_CAPACITY_ANSWER,
        "sources": [],
        "cached": False,
        "degraded": True,
    }


def test_message_rejects_blank_and_oversized_input(client, db_session: Session, seeded) -> None:
    _subscribe_pro(db_session, seeded)

    blank = client.post("/copilot", json={"message": "   "})
    oversized = client.post("/copilot", json={"message": "x" * 2_001})

    assert blank.status_code == 422
    assert oversized.status_code == 422
