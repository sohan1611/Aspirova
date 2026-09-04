"""Backfill deterministic extracted summaries for active opportunities.

Usage:
    uv run python -m scripts.backfill_summaries
    uv run python -m scripts.backfill_summaries --apply
"""

import argparse
from collections.abc import Iterator
from typing import TypedDict

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session, load_only
from sqlalchemy.sql.elements import ColumnElement

from core import models
from core.db import make_engine
from core.summarise import summarise_description

BATCH_SIZE = 500
MAINTENANCE_STATEMENT_TIMEOUT = "120s"
SAMPLE_SIZE = 10


class SummarySample(TypedDict):
    id: int
    title: str
    before: str | None
    after: str | None


class BackfillResult(TypedDict):
    matching: int
    examined: int
    would_update: int
    updated: int
    skipped_no_summary: int
    sample: list[SummarySample]


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _matching_filters() -> tuple[ColumnElement[bool], ...]:
    return (
        models.Opportunity.status == "active",
        or_(
            models.Opportunity.summary.is_(None),
            models.Opportunity.meta["summary_source"].as_string() == "extracted",
        ),
    )


def _matching_count(session: Session) -> int:
    count = session.scalar(
        select(func.count()).select_from(models.Opportunity).where(*_matching_filters())
    )
    return int(count or 0)


def _matching_batches(
    session: Session,
    *,
    limit: int | None,
    batch_size: int,
) -> Iterator[list[models.Opportunity]]:
    last_id = 0
    remaining = limit

    while remaining is None or remaining > 0:
        current_size = batch_size if remaining is None else min(batch_size, remaining)
        rows = list(
            session.scalars(
                select(models.Opportunity)
                .options(
                    load_only(
                        models.Opportunity.id,
                        models.Opportunity.title,
                        models.Opportunity.description_raw,
                        models.Opportunity.summary,
                        models.Opportunity.meta,
                    )
                )
                .where(models.Opportunity.id > last_id, *_matching_filters())
                .order_by(models.Opportunity.id)
                .limit(current_size)
            ).all()
        )
        if not rows:
            return

        last_id = rows[-1].id
        yield rows
        if remaining is not None:
            remaining -= len(rows)


def _copy_meta(meta: dict | None) -> dict:
    return dict(meta) if isinstance(meta, dict) else {}


def _meta_for_summary(meta: dict | None, summary: str | None) -> dict | None:
    next_meta = _copy_meta(meta)
    if summary is None:
        next_meta.pop("summary_source", None)
    else:
        next_meta["summary_source"] = "extracted"
    return next_meta or None


def _should_update(
    opportunity: models.Opportunity,
    *,
    summary: str | None,
    meta: dict | None,
) -> bool:
    current_meta = opportunity.meta or None
    return opportunity.summary != summary or current_meta != meta


def backfill_summaries(
    session: Session,
    *,
    apply: bool = False,
    limit: int | None = None,
    batch_size: int = BATCH_SIZE,
) -> BackfillResult:
    """Populate deterministic summaries without touching AI-authored rows."""
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")

    matching = _matching_count(session)
    examined = 0
    would_update = 0
    updated = 0
    skipped_no_summary = 0
    sample: list[SummarySample] = []

    for opportunities in _matching_batches(session, limit=limit, batch_size=batch_size):
        for opportunity in opportunities:
            examined += 1
            summary = summarise_description(
                opportunity.description_raw,
                title=opportunity.title,
            )
            meta = _meta_for_summary(opportunity.meta, summary)
            if summary is None:
                skipped_no_summary += 1

            if not _should_update(opportunity, summary=summary, meta=meta):
                continue

            would_update += 1
            if len(sample) < SAMPLE_SIZE:
                sample.append(
                    {
                        "id": opportunity.id,
                        "title": opportunity.title,
                        "before": opportunity.summary,
                        "after": summary,
                    }
                )

            if apply:
                opportunity.summary = summary
                opportunity.meta = meta
                updated += 1

        if apply:
            session.commit()

    if not apply:
        session.rollback()

    return {
        "matching": matching,
        "examined": examined,
        "would_update": would_update,
        "updated": updated,
        "skipped_no_summary": skipped_no_summary,
        "sample": sample,
    }


def _preview(value: str | None, *, max_length: int = 140) -> str:
    if value is None:
        return "<NULL>"

    single_line = " ".join(value.split())
    if len(single_line) <= max_length:
        return single_line
    return f"{single_line[: max_length - 3]}..."


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill deterministic extracted opportunity summaries."
    )
    parser.add_argument("--apply", action="store_true", help="Write changes and commit each batch.")
    parser.add_argument(
        "--limit",
        type=_positive_int,
        help="Maximum matching active opportunities to examine.",
    )
    parser.add_argument(
        "--batch-size",
        type=_positive_int,
        default=BATCH_SIZE,
        help=f"Matching opportunities per commit batch (default: {BATCH_SIZE}).",
    )
    args = parser.parse_args()

    engine = make_engine()
    with Session(engine) as session:
        session.execute(text(f"SET statement_timeout = '{MAINTENANCE_STATEMENT_TIMEOUT}'"))
        result = backfill_summaries(
            session,
            apply=args.apply,
            limit=args.limit,
            batch_size=args.batch_size,
        )

    print(f"mode: {'apply' if args.apply else 'dry-run'}", flush=True)
    print(f"matching rows: {result['matching']}", flush=True)
    print(f"examined: {result['examined']}", flush=True)
    print(f"would-update: {result['would_update']}", flush=True)
    print(f"updated: {result['updated']}", flush=True)
    print(f"skipped-no-usable-summary: {result['skipped_no_summary']}", flush=True)
    if result["sample"]:
        print("sample before/after:", flush=True)
        for row in result["sample"]:
            print(f"- {row['id']} | {_preview(row['title'], max_length=80)}", flush=True)
            print(f"  before: {_preview(row['before'])}", flush=True)
            print(f"  after: {_preview(row['after'])}", flush=True)

    if not args.apply:
        print("dry-run only; no rows updated", flush=True)


if __name__ == "__main__":
    main()
