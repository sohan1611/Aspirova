"""Refresh text pay and explicit role signals, including closed/hidden rows.

Dry run by default. Structured compensation is preserved.

Usage:
    uv run python -m scripts.backfill_role_signals
    uv run python -m scripts.backfill_role_signals --apply
"""

import argparse
import json
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from core import models
from core.db import make_engine
from pipeline.role_signals import merge_role_signals

BATCH_SIZE = 500
PREVIEW_LIMIT = 15
SIGNAL_KEYS = ("compensation", "duration_months", "part_time", "job_offer")


def transform_row(current: dict[str, Any]) -> dict[str, Any]:
    """Return only the metadata update, preserving every unrelated key."""
    meta = merge_role_signals(
        current.get("meta"),
        current.get("title"),
        current.get("description_raw"),
        current.get("category"),
        current.get("country"),
    )
    return {"meta": None if not meta and current.get("meta") is None else meta}


def backfill_role_signals(session: Session, *, apply: bool = False) -> dict[str, int]:
    counts = dict.fromkeys(
        ("scanned", "would_change", "amounts_removed", "period_changes", *SIGNAL_KEYS), 0
    )
    last_id = 0
    samples = 0
    while True:
        query = (
            select(
                models.Opportunity.id,
                models.Opportunity.title,
                models.Opportunity.description_raw,
                models.Opportunity.category,
                models.Opportunity.country,
                models.Opportunity.meta,
            )
            .where(
                models.Opportunity.category.in_(("internship", "job")),
                models.Opportunity.id > last_id,
            )
            .order_by(models.Opportunity.id)
            .limit(BATCH_SIZE)
        )
        # Lock each write batch so a concurrent crawl cannot replace text pay
        # with structured pay between this read and the metadata update.
        if apply:
            query = query.with_for_update()
        rows = session.execute(query).all()
        if not rows:
            break
        for row in rows:
            counts["scanned"] += 1
            before = {"meta": row.meta}
            after = transform_row(dict(row._mapping))
            if before == after:
                continue
            counts["would_change"] += 1
            old_pay = (row.meta or {}).get("compensation") or {}
            new_pay = (after["meta"] or {}).get("compensation") or {}
            if not isinstance(old_pay, dict):
                old_pay = {}
            if not isinstance(new_pay, dict):
                new_pay = {}
            counts["amounts_removed"] += int(
                any(old_pay.get(key) is not None for key in ("min", "max"))
                and not any(new_pay.get(key) is not None for key in ("min", "max"))
            )
            counts["period_changes"] += int(
                old_pay.get("period") is not None
                and new_pay.get("period") is not None
                and old_pay["period"] != new_pay["period"]
            )
            for key in SIGNAL_KEYS:
                counts[key] += int((row.meta or {}).get(key) != (after["meta"] or {}).get(key))
            if samples < PREVIEW_LIMIT:
                print(
                    json.dumps(
                        {"id": row.id, "before": old_pay, "after": new_pay}, ensure_ascii=True
                    )
                )
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
        label = {"scanned": "total checked", "would_change": "changed" if apply else "would change"}
        print(f"{label.get(name, name.replace('_', ' '))}: {count}", flush=True)
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
