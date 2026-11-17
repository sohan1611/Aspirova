"""Shared query-time ranking for /for-you and deterministic digest picks."""

from sqlalchemy import Text, any_, bindparam, case, cast, func, select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.sql import Select
from sqlalchemy.sql.elements import ColumnElement

from api.filters import listing_closed
from core import models


def fts_ranking(keywords: list[str]) -> tuple[ColumnElement[bool], ColumnElement[float]]:
    tsquery = func.websearch_to_tsquery("english", " OR ".join(keywords))
    return (
        models.Opportunity.search_tsv.op("@@")(tsquery),
        func.ts_rank(models.Opportunity.search_tsv, tsquery),
    )


def rank_profile_query(
    query: Select,
    keywords: list[str],
    user_skills: list[str] | None = None,
    *,
    tie_breakers: list | None = None,
) -> Select:
    """Preserve /for-you's skill precedence, rank and default ordering exactly."""
    tail = (
        tie_breakers
        if tie_breakers is not None
        else [
            models.Opportunity.last_seen_at.desc(),
            models.Opportunity.id.desc(),
        ]
    )
    if user_skills:
        skill_values = cast(
            bindparam("user_skills", value=user_skills, type_=ARRAY(Text())), ARRAY(Text())
        )
        skill_element = (
            func.jsonb_array_elements_text(models.Opportunity.skills)
            .table_valued("skill")
            .render_derived(name="skill")
        )
        overlap_count = (
            select(func.count())
            .select_from(skill_element)
            .where(skill_element.c.skill == any_(skill_values))
            .correlate(models.Opportunity.__table__)
            .scalar_subquery()
        )
        return query.where(models.Opportunity.skills.op("?|")(skill_values)).order_by(
            overlap_count.desc(), *tail
        )
    if keywords:
        matches, rank = fts_ranking(keywords)
        return query.where(matches).order_by(rank.desc(), *tail)
    return query.order_by(case((listing_closed(), 1), else_=0).asc(), *tail)
