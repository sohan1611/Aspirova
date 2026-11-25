"""Bounded selection and interleaving for the landing page."""

from collections import Counter
from collections.abc import Sequence
from itertools import zip_longest
from typing import Any

from sqlalchemy import Row, Select, case, func, literal, or_, select, union_all
from sqlalchemy.orm import Session
from sqlalchemy.sql import operators
from sqlalchemy.sql.elements import ColumnElement

from api.opportunity_loading import opportunity_list_load_options
from core import models


def famous_company_filter() -> ColumnElement[bool]:
    return or_(models.Company.prestige_rank.is_not(None), models.Company.global_rank.is_not(None))


def landing_feed_rows(
    db: Session,
    filters: Sequence[ColumnElement],
    ordering: Sequence[ColumnElement],
    limit: int,
) -> list[Row[Any]]:
    """Rank once on narrow rows; fetch at most 2 * limit candidate ids.

    Source ranks must include logoless companies. Freeze those ranks before
    excluding logoless rows, then apply the existing cap and famous quota.
    MATERIALIZED prevents the planner from inlining repeated window work.
    """
    candidates = (
        select(
            models.Opportunity.id,
            models.Opportunity.company_id,
            models.Company.logo_url.is_not(None).label("has_logo"),
            famous_company_filter().label("is_famous"),
            *(clause.element.label(f"sort_{i}") for i, clause in enumerate(ordering)),
        )
        .outerjoin(models.Company, models.Company.id == models.Opportunity.company_id)
        .where(*filters)
        .cte("landing_candidates")
        .prefix_with("MATERIALIZED")
    )
    narrow_order = [
        (
            candidates.c[f"sort_{i}"].desc()
            if clause.modifier is operators.desc_op
            else candidates.c[f"sort_{i}"].asc()
        )
        for i, clause in enumerate(ordering)
    ]
    ranked = (
        select(
            candidates.c.id,
            candidates.c.company_id,
            candidates.c.is_famous,
            func.row_number()
            .over(partition_by=candidates.c.company_id, order_by=narrow_order)
            .label("company_position"),
            func.row_number().over(order_by=narrow_order).label("landing_position"),
        )
        .where(candidates.c.has_logo)
        .cte("landing_ranked")
        .prefix_with("MATERIALIZED")
    )
    company_cap = min(2, (limit + 1) // 2)
    totals = select(
        func.count().label("total_count"),
        func.count().filter(ranked.c.company_position <= company_cap).label("capped_count"),
    ).cte("landing_totals")
    # With too few capped candidates, the old query relaxes the cap and orders
    # BOTH natural and famous pools by company position, then landing position.
    short = totals.c.capped_count < limit
    pool = (
        select(
            ranked,
            totals.c.total_count,
            case((short, ranked.c.company_position), else_=0).label("pool_position"),
        )
        .join(totals, literal(True))
        .where(or_(ranked.c.company_position <= company_cap, short))
        .order_by(case((short, ranked.c.company_position), else_=0), ranked.c.landing_position)
    )
    natural = pool.limit(limit).cte("landing_natural")
    famous = pool.where(ranked.c.is_famous).limit(limit).cte("landing_famous")
    combined = union_all(
        select(natural, literal(False).label("famous_pool")),
        select(famous, literal(True).label("famous_pool")),
    ).subquery()
    choices = db.execute(
        select(combined).order_by(
            combined.c.famous_pool, combined.c.pool_position, combined.c.landing_position
        )
    ).all()
    natural_rows = [row for row in choices if not row.famous_pool]
    famous_limit = max((limit + 1) // 2, sum(row.is_famous for row in natural_rows))
    famous_rows = [row for row in choices if row.famous_pool][:famous_limit]
    other_rows = [row for row in natural_rows if not row.is_famous][: limit - len(famous_rows)]
    selected = sorted(famous_rows + other_rows, key=lambda row: row.landing_position)
    if not selected:
        return []
    # Landing is exclusively the open, unfiltered student page: open == total.
    total = selected[0].total_count
    hydrated = (
        db.execute(
            select(
                models.Opportunity,
                literal(total).label("total_count"),
                literal(total).label("open_count"),
            )
            .options(*opportunity_list_load_options())
            .where(models.Opportunity.id.in_([row.id for row in selected]))
        )
        .unique()
        .all()
    )
    by_id = {row.Opportunity.id: row for row in hydrated}
    famous_rows = [by_id[row.id] for row in selected if row.is_famous]
    other_rows = [by_id[row.id] for row in selected if not row.is_famous]
    interleaved = [
        row for pair in zip_longest(famous_rows, other_rows) for row in pair if row is not None
    ]
    return _separate_companies(interleaved)


def landing_rows(
    db: Session,
    query: Select,
    famous: ColumnElement[bool],
    limit: int,
    *,
    listing_order: Sequence[ColumnElement] | None = None,
) -> list[Row[Any]]:
    query = query.add_columns(famous.label("is_famous"))
    if listing_order is not None:
        ranks = (
            query.with_only_columns(
                models.Opportunity.id,
                func.row_number()
                .over(partition_by=models.Opportunity.company_id, order_by=listing_order)
                .label("company_position"),
                func.row_number().over(order_by=listing_order).label("landing_position"),
            )
            .order_by(None)
            .subquery()
        )
        query = query.join_from(
            models.Opportunity, ranks, ranks.c.id == models.Opportunity.id
        ).add_columns(ranks.c.landing_position)
        company_cap = min(2, (limit + 1) // 2)
        capped_query = query.where(ranks.c.company_position <= company_cap)
        natural_rows = db.execute(capped_query.limit(limit)).unique().all()
        if len(natural_rows) < limit:
            # Relax the cap only after exhausting the capped candidate pool.
            query = query.order_by(None).order_by(
                ranks.c.company_position.asc(), ranks.c.landing_position.asc()
            )
            natural_rows = db.execute(query.limit(limit)).unique().all()
        else:
            query = capped_query
    else:
        natural_rows = db.execute(query.limit(limit)).unique().all()
    famous_limit = max((limit + 1) // 2, sum(row.is_famous for row in natural_rows))
    famous_rows = db.execute(query.where(famous).limit(famous_limit)).unique().all()
    other_rows = [row for row in natural_rows if not row.is_famous][: limit - len(famous_rows)]
    selected = famous_rows + other_rows
    if listing_order is not None:
        selected.sort(key=lambda row: row.landing_position)
    famous_rows = [row for row in selected if row.is_famous]
    other_rows = [row for row in selected if not row.is_famous]
    interleaved = [
        row for pair in zip_longest(famous_rows, other_rows) for row in pair if row is not None
    ]
    return _separate_companies(interleaved) if listing_order is not None else interleaved


def _separate_companies(rows: list[Row[Any]]) -> list[Row[Any]]:
    pending = list(rows)
    counts = Counter(row.Opportunity.company_id for row in pending)
    ordered = []
    previous = None
    while pending:
        choices = [
            index for index, row in enumerate(pending) if row.Opportunity.company_id != previous
        ]

        def priority(index: int) -> tuple[bool, int, int]:
            company_id = pending[index].Opportunity.company_id
            remaining = len(pending) - 1
            largest_other = max(
                (count for key, count in counts.items() if key != company_id), default=0
            )
            can_finish = (
                counts[company_id] - 1 <= remaining // 2 and largest_other <= (remaining + 1) // 2
            )
            return (not can_finish, 0 if can_finish else -counts[company_id], index)

        index = min(choices, key=priority) if choices else 0
        row = pending.pop(index)
        previous = row.Opportunity.company_id
        counts[previous] -= 1
        ordered.append(row)
    return ordered
