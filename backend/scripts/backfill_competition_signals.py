"""Backfill competition prizes and Unstop teams; dry run by default.

Usage:
    uv run python -m scripts.backfill_competition_signals
    uv run python -m scripts.backfill_competition_signals --apply
"""

import argparse
import json
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from core import models
from core.db import make_engine
from crawlers.unstop import unstop_team_fields
from pipeline.competition_signals import merge_competition_signals

BATCH_SIZE = 500
PREVIEW_LIMIT = 10


def transform_meta(
    meta: dict[str, Any] | None,
    category: str,
    source: str | None,
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    result = merge_competition_signals(meta, category)
    if source == "unstop" and isinstance(payload, dict):
        result.pop("team_min", None)
        result.pop("team_size", None)
        result.update(unstop_team_fields(payload))
    return result


def backfill_competition_signals(session: Session, *, apply: bool = False) -> dict[str, int]:
    counts = dict.fromkeys(("scanned", "would_change", "prize_changed", "team_changed"), 0)
    latest_payload = (
        select(models.RawListing.raw_payload)
        .join(models.Source, models.Source.id == models.RawListing.source_id)
        .where(
            models.RawListing.opportunity_id == models.Opportunity.id,
            or_(models.Source.adapter_key == "unstop", models.Source.slug == "unstop"),
        )
        .order_by(models.RawListing.crawled_at.desc().nullslast(), models.RawListing.id.desc())
        .limit(1)
        .correlate(models.Opportunity)
        .scalar_subquery()
    )
    last_id = 0
    samples = 0
    while True:
        rows = session.execute(
            select(
                models.Opportunity.id,
                models.Opportunity.slug,
                models.Opportunity.category,
                models.Opportunity.primary_source,
                models.Opportunity.meta,
                latest_payload.label("payload"),
            )
            .where(
                models.Opportunity.category.in_(("hackathon", "competition", "scholarship")),
                models.Opportunity.id > last_id,
            )
            .order_by(models.Opportunity.id)
            .limit(BATCH_SIZE)
        ).all()
        if not rows:
            break
        for row in rows:
            counts["scanned"] += 1
            before = row.meta or {}
            after = transform_meta(before, row.category, row.primary_source, row.payload)
            if before == after:
                continue
            counts["would_change"] += 1
            counts["prize_changed"] += int(
                any(before.get(key) != after.get(key) for key in ("prize_inr", "prize_text"))
            )
            counts["team_changed"] += int(
                any(before.get(key) != after.get(key) for key in ("team_min", "team_size"))
            )
            if samples < PREVIEW_LIMIT:
                print(json.dumps({"slug": row.slug, "before": before, "after": after}))
                samples += 1
            if apply:
                session.execute(
                    update(models.Opportunity)
                    .where(models.Opportunity.id == row.id)
                    .values(meta=after)
                )
        last_id = rows[-1].id
        if apply:
            session.commit()
    if not apply:
        session.rollback()
    for name, count in counts.items():
        print(f"{name.replace('_', ' ')}: {count}", flush=True)
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill competition prizes and Unstop teams.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Preview only (default).")
    mode.add_argument("--apply", action="store_true", help="Write changes in batches of 500.")
    args = parser.parse_args()
    print(f"mode: {'apply' if args.apply else 'dry-run'}", flush=True)
    with Session(make_engine()) as session:
        backfill_competition_signals(session, apply=args.apply)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
