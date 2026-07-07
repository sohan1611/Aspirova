"""Idempotent, post-dedup opportunity enrichment (Doc 05 Shape A)."""

import json
import re

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from core import ai_client, models
from core.ai_budget import is_over_budget
from core.config import get_settings


def _parse_tags(raw_tags: str) -> list[str]:
    """Accept a short JSON list or comma-separated list; reject anything else."""
    if not isinstance(raw_tags, str):
        return []

    try:
        value = raw_tags.strip()
        if value.startswith("["):
            parsed = json.loads(value)
            if not isinstance(parsed, list):
                return []
            candidates = parsed
        elif "," in value and not value.startswith(("{", "```")):
            candidates = value.split(",")
        else:
            return []

        if not candidates or len(candidates) > 10:
            return []

        tags: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            if not isinstance(candidate, str):
                return []
            name = candidate.strip()
            if not name or len(name) > 80 or "\n" in name:
                return []
            key = name.casefold()
            if key not in seen:
                tags.append(name)
                seen.add(key)
        return tags
    except (json.JSONDecodeError, TypeError, ValueError):
        return []


def _tag_slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.casefold())
    return re.sub(r"-+", "-", slug).strip("-")


def _replace_tags(session: Session, opportunity_id: int, tag_names: list[str]) -> None:
    session.execute(
        delete(models.OpportunityTag).where(models.OpportunityTag.opportunity_id == opportunity_id)
    )

    names_by_slug = {slug: name for name in tag_names if (slug := _tag_slug(name))}
    if not names_by_slug:
        return

    existing_tags = session.scalars(
        select(models.Tag).where(models.Tag.slug.in_(names_by_slug))
    ).all()
    tags_by_slug = {tag.slug: tag for tag in existing_tags}

    for slug, name in names_by_slug.items():
        if slug not in tags_by_slug:
            tag = models.Tag(slug=slug, label=name)
            session.add(tag)
            tags_by_slug[slug] = tag

    session.flush()
    session.add_all(
        models.OpportunityTag(opportunity_id=opportunity_id, tag_id=tag.id)
        for tag in tags_by_slug.values()
    )


def enrich_opportunity(session: Session, opportunity: models.Opportunity) -> bool:
    """Set reusable summary, tags, and embedding for one canonical opportunity."""
    if opportunity.summary is not None and opportunity.embedding is not None:
        return False

    description = opportunity.description_raw or ""
    summary_result = ai_client.generate(
        session,
        feature="enrich.summary",
        system="Write a concise, factual opportunity summary. Return only the summary.",
        prompt=f"Title: {opportunity.title}\nDescription:\n{description}",
    )
    summary = summary_result.text.strip()

    tags_result = ai_client.generate(
        session,
        feature="enrich.tags",
        system=(
            "Extract up to 10 concise opportunity tags. Return only a JSON list "
            "or a comma-separated list."
        ),
        prompt=(
            f"Title: {opportunity.title}\n" f"Summary: {summary}\n" f"Description:\n{description}"
        ),
    )
    tag_names = _parse_tags(tags_result.text)

    embedding_text = opportunity.title + "\n" + (summary or description)
    embedding = ai_client.embed(
        session,
        [embedding_text],
        feature="enrich.embedding",
    )[0]

    opportunity.summary = summary or None
    opportunity.embedding = embedding
    opportunity.embedding_model = get_settings().ai_embedding_model
    session.flush()
    _replace_tags(session, opportunity.id, tag_names)
    return True


def enrich_pending(session: Session, *, limit: int) -> dict[str, object]:
    """Enrich a bounded backlog safely; blank generation keys are a hard no-op."""
    if not get_settings().anthropic_api_key:
        return {"skipped": True, "enriched": 0, "reason": "no provider key"}

    opportunities = session.scalars(
        select(models.Opportunity)
        .where(
            or_(
                models.Opportunity.summary.is_(None),
                models.Opportunity.embedding.is_(None),
            )
        )
        .order_by(models.Opportunity.id)
        .limit(max(limit, 0))
    ).all()

    enriched = 0
    stopped_over_budget = False
    for opportunity in opportunities:
        if is_over_budget(session):
            stopped_over_budget = True
            break
        try:
            if enrich_opportunity(session, opportunity):
                enriched += 1
            session.commit()
        except Exception:
            session.rollback()
            raise

    return {
        "skipped": False,
        "enriched": enriched,
        "stopped_over_budget": stopped_over_budget,
    }


def backfill_embeddings(session: Session, *, limit: int) -> dict[str, object]:
    """Embed a bounded backlog without running generation enrichment."""
    settings = get_settings()
    if not settings.openai_api_key:
        return {"skipped": True, "embedded": 0, "reason": "no embedding key"}

    opportunities = session.scalars(
        select(models.Opportunity)
        .where(models.Opportunity.embedding.is_(None))
        .order_by(models.Opportunity.id)
        .limit(max(limit, 0))
    ).all()

    embedded = 0
    stopped_over_budget = False
    for opportunity in opportunities:
        if is_over_budget(session):
            stopped_over_budget = True
            break
        try:
            text = ((opportunity.title or "") + "\n" + (opportunity.description_raw or ""))[:28000]
            vector = ai_client.embed(session, [text], feature="backfill.embedding")[0]
            opportunity.embedding = vector
            opportunity.embedding_model = settings.ai_embedding_model
            session.commit()
            embedded += 1
        except Exception:
            session.rollback()
            raise

    return {
        "skipped": False,
        "embedded": embedded,
        "stopped_over_budget": stopped_over_budget,
    }
