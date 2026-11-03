"""Backfill explicit role signals; dry run by default.

Usage:
    uv run python -m scripts.backfill_role_signals
    uv run python -m scripts.backfill_role_signals --apply
"""

import argparse
import json
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from api.filters import open_opportunity_filters
from core import models
from core.db import make_engine
from pipeline.role_signals import merge_role_signals

BATCH_SIZE = 500
PREVIEW_LIMIT = 15
SIGNAL_KEYS = ("compensation", "duration_months", "part_time", "job_offer")


def transform_row(current: dict[str, Any]) -> dict[str, Any]:
    """Return only the metadata update, preserving every unrelated key."""
    return {
        "meta": merge_role_signals(
            current.get("meta"),
            current.get("title"),
            current.get("description_raw"),
            current.get("category"),
            current.get("country"),
        )
        or current.get("meta")
    }


def backfill_role_signals(session: Session, *, apply: bool = False) -> dict[str, int]:
    counts = dict.fromkeys(("scanned", "would_change", *SIGNAL_KEYS), 0)
    last_id = 0
    samples = 0
    while True:
        rows = session.execute(
            select(
                models.Opportunity.id,
                models.Opportunity.title,
                models.Opportunity.description_raw,
                models.Opportunity.category,
                models.Opportunity.country,
                models.Opportunity.meta,
            )
            .where(
                *open_opportunity_filters(),
                models.Opportunity.category.in_(("internship", "job")),
                models.Opportunity.id > last_id,
            )
            .order_by(models.Opportunity.id)
            .limit(BATCH_SIZE)
        ).all()
        if not rows:
            break
        for row in rows:
            counts["scanned"] += 1
            before = {"meta": row.meta}
            after = transform_row(dict(row._mapping))
            if before == after:
                continue
            counts["would_change"] += 1
            for key in SIGNAL_KEYS:
                counts[key] += int((row.meta or {}).get(key) != (after["meta"] or {}).get(key))
            if samples < PREVIEW_LIMIT:
                print(json.dumps({"id": row.id, "before": before, "after": after}))
                samples += 1
            if apply:
                session.execute(
                    update(models.Opportunity)
                    .where(models.Opportunity.id == row.id)
                    .values(**after)
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
    parser = argparse.ArgumentParser(description="Backfill explicit role signals.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Preview only (default).")
    mode.add_argument("--apply", action="store_true", help="Write changes in batches of 500.")
    args = parser.parse_args()
    print(f"mode: {'apply' if args.apply else 'dry-run'}", flush=True)
    with Session(make_engine()) as session:
        backfill_role_signals(session, apply=args.apply)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
