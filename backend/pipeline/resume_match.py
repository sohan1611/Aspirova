"""Resume embedding and pure pgvector cosine matching (Doc 05 sec 2.2)."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from core import ai_client, models
from core.config import get_settings

RESUME_TEXT_MAX_CHARS = 8_000


def save_resume(session: Session, user: models.User, resume_text: str) -> models.ResumeProfile:
    """Embed and store one immutable, incremented version of a user's resume."""
    truncated_text = resume_text[:RESUME_TEXT_MAX_CHARS]
    embedding = ai_client.embed(
        session,
        [truncated_text],
        feature="resume.embed",
    )[0]
    latest_version = session.scalar(
        select(func.max(models.ResumeProfile.version)).where(
            models.ResumeProfile.user_id == user.id
        )
    )
    profile = models.ResumeProfile(
        user_id=user.id,
        version=(latest_version or 0) + 1,
        embedding=embedding,
        embedding_model=get_settings().ai_embedding_model,
    )
    session.add(profile)
    session.flush()
    return profile


def match_for_user(
    session: Session, user: models.User, *, limit: int
) -> list[tuple[models.Opportunity, float]]:
    """Rank embedded opportunities by cosine similarity without any LLM call."""
    resume = session.scalar(
        select(models.ResumeProfile)
        .where(models.ResumeProfile.user_id == user.id)
        .order_by(models.ResumeProfile.version.desc())
        .limit(1)
    )
    if resume is None:
        return []

    cosine_distance = models.Opportunity.embedding.cosine_distance(resume.embedding).label(
        "cosine_distance"
    )
    rows = session.execute(
        select(models.Opportunity, cosine_distance)
        .options(joinedload(models.Opportunity.company))
        .where(models.Opportunity.embedding.is_not(None))
        .order_by(cosine_distance.asc(), models.Opportunity.id.asc())
        .limit(max(limit, 0))
    ).unique()

    return [
        (opportunity, max(0.0, min(1.0, 1.0 - float(distance)))) for opportunity, distance in rows
    ]
