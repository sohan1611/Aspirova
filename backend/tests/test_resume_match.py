"""Integration tests for Pro-gated, zero-generation resume cosine matching."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import pipeline.resume_match as resume_match_module
from api.auth import get_current_user
from api.deps import get_db
from api.main import app
from core import models
from core.config import get_settings
from pipeline.resume_match import RESUME_TEXT_MAX_CHARS, match_for_user, save_resume


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
def seeded(db_session: Session):
    free_plan = db_session.scalar(select(models.Plan).where(models.Plan.key == "free"))
    if free_plan is None:
        free_plan = models.Plan(key="free", price_paise=0, billing=None, features={})
        db_session.add(free_plan)
        db_session.flush()
    free_plan.features = {"resume_match": False}

    suffix = str(uuid.uuid4())
    pro_plan = models.Plan(
        key=f"pro-resume-test-{suffix}",
        price_paise=4900,
        billing="monthly",
        features={"resume_match": True},
    )
    user = models.User(email=f"resume-match-test-{suffix}@example.com")
    company = models.Company(
        slug=f"resume-match-company-{suffix}",
        name="Resume Match Test Company",
        name_normalized="resume match test company",
    )
    opportunity = models.Opportunity(
        slug=f"resume-match-api-opportunity-{suffix}",
        company=company,
        title="Backend Engineering Internship",
        apply_url="https://example.com/resume-match-apply",
        embedding=[1.0] + [0.0] * 1535,
        embedding_model=get_settings().ai_embedding_model,
    )
    db_session.add_all([pro_plan, user, company, opportunity])
    db_session.flush()
    return {
        "free_plan": free_plan,
        "pro_plan": pro_plan,
        "user": user,
        "opportunity": opportunity,
    }


@pytest.fixture
def client(db_session, seeded):
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: seeded["user"]
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)


def test_save_resume_truncates_text_and_increments_version(
    db_session: Session, seeded, monkeypatch
) -> None:
    embedded_texts: list[str] = []

    def fake_embed(session, texts, *, feature):
        assert session is db_session
        assert feature == "resume.embed"
        embedded_texts.extend(texts)
        return [[1.0] + [0.0] * 1535]

    monkeypatch.setattr(resume_match_module.ai_client, "embed", fake_embed)

    first = save_resume(db_session, seeded["user"], "x" * (RESUME_TEXT_MAX_CHARS + 100))
    second = save_resume(db_session, seeded["user"], "updated resume")

    assert first.version == 1
    assert second.version == 2
    assert len(embedded_texts[0]) == RESUME_TEXT_MAX_CHARS
    assert embedded_texts[1] == "updated resume"


def test_match_orders_by_cosine_excludes_null_and_creates_no_generation_usage(
    db_session: Session, seeded
) -> None:
    baseline_usage_id = db_session.scalar(select(func.max(models.AiUsage.id))) or 0
    profile = save_resume(db_session, seeded["user"], "Python backend and distributed systems")
    resume_vector = list(profile.embedding)
    orthogonal_vector = [0.0] * 1536
    orthogonal_vector[0] = -resume_vector[1]
    orthogonal_vector[1] = resume_vector[0]

    suffix = str(uuid.uuid4())
    nearest = models.Opportunity(
        slug=f"resume-match-nearest-{suffix}",
        title="Nearest Resume Match",
        apply_url="https://example.com/nearest",
        embedding=resume_vector,
        embedding_model=get_settings().ai_embedding_model,
    )
    orthogonal = models.Opportunity(
        slug=f"resume-match-orthogonal-{suffix}",
        title="Orthogonal Resume Match",
        apply_url="https://example.com/orthogonal",
        embedding=orthogonal_vector,
        embedding_model=get_settings().ai_embedding_model,
    )
    farthest = models.Opportunity(
        slug=f"resume-match-farthest-{suffix}",
        title="Farthest Resume Match",
        apply_url="https://example.com/farthest",
        embedding=[-value for value in resume_vector],
        embedding_model=get_settings().ai_embedding_model,
    )
    missing_embedding = models.Opportunity(
        slug=f"resume-match-null-{suffix}",
        title="Missing Resume Embedding",
        apply_url="https://example.com/missing",
        embedding=None,
    )
    db_session.add_all([nearest, orthogonal, farthest, missing_embedding])
    db_session.flush()

    usage_after_embed = list(
        db_session.scalars(
            select(models.AiUsage).where(models.AiUsage.id > baseline_usage_id)
        ).all()
    )
    assert [row.feature for row in usage_after_embed] == ["resume.embed"]

    matches = match_for_user(db_session, seeded["user"], limit=100)

    assert matches[0][0].slug == nearest.slug
    assert matches[0][1] == pytest.approx(1.0)
    assert missing_embedding.slug not in {opportunity.slug for opportunity, _score in matches}
    usage_after_match = list(
        db_session.scalars(
            select(models.AiUsage).where(models.AiUsage.id > baseline_usage_id)
        ).all()
    )
    assert len(usage_after_match) == len(usage_after_embed)
    assert not [row for row in usage_after_match if row.feature != "resume.embed"]


def test_free_user_is_blocked_from_resume_endpoints(client, seeded, db_session) -> None:
    post_response = client.post("/resume", json={"resume_text": "My resume"})
    get_response = client.get("/resume/matches")

    assert post_response.status_code == 403
    assert post_response.json()["detail"] == "Resume Match is a Pro feature. Upgrade to use it."
    assert get_response.status_code == 403
    assert get_response.json()["detail"] == "Resume Match is a Pro feature. Upgrade to use it."
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(models.ResumeProfile)
            .where(models.ResumeProfile.user_id == seeded["user"].id)
        )
        == 0
    )


def test_pro_user_can_upload_resume_and_get_matches(client, seeded, db_session) -> None:
    db_session.add(
        models.Subscription(
            user_id=seeded["user"].id,
            plan_id=seeded["pro_plan"].id,
            status="active",
        )
    )
    db_session.flush()

    upload_response = client.post("/resume", json={"resume_text": "Backend engineering resume"})
    assert upload_response.status_code == 200
    assert upload_response.json() == {"version": 1}

    profile = db_session.scalar(
        select(models.ResumeProfile).where(models.ResumeProfile.user_id == seeded["user"].id)
    )
    seeded["opportunity"].embedding = list(profile.embedding)
    db_session.flush()

    matches_response = client.get("/resume/matches")

    assert matches_response.status_code == 200
    matches = matches_response.json()
    assert matches[0]["opportunity"]["slug"] == seeded["opportunity"].slug
    assert matches[0]["score"] == pytest.approx(1.0)
