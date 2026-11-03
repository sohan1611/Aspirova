"""Backfill Unstop role fields from stored payloads; dry run by default.

Usage:
    uv run python -m scripts.backfill_unstop_fields
    uv run python -m scripts.backfill_unstop_fields --apply
"""

import argparse
import json
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from core import models
from core.db import make_engine
from crawlers.unstop import unstop_role_fields
from pipeline.location_country import derive_country

BATCH_SIZE = 500
PREVIEW_LIMIT = 10
ROLE_META_KEYS = ("work_mode", "timing", "compensation")


def transform_row(current: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """Recompute only the role fields, preserving unrelated metadata."""
    fields = unstop_role_fields(payload)
    meta = dict(current.get("meta") or {})
    old_pay = meta.get("compensation")
    for key in ROLE_META_KEYS:
        meta.pop(key, None)
    meta.update(fields["meta"])
    # Pay parsed from the listing's text isn't in Unstop's fields, so recomputing
    # those fields must not erase it.
    if "compensation" not in meta and isinstance(old_pay, dict) and old_pay.get("source") == "text":
        meta["compensation"] = old_pay
    return {
        "location": fields["location"],
        "country": fields["country"] or derive_country(fields["location"]),
        "is_remote": fields["is_remote"],
        "meta": meta,
    }


def backfill_unstop_fields(session: Session, *, apply: bool = False) -> dict[str, int]:
    counts = dict.fromkeys(
        (
            "scanned",
            "would_change",
            "location_changed",
            "country_changed",
            "remote_changed",
            "pay_added",
        ),
        0,
    )
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
                models.Opportunity.location,
                models.Opportunity.country,
                models.Opportunity.is_remote,
                models.Opportunity.meta,
                latest_payload.label("payload"),
            )
            .where(
                models.Opportunity.primary_source == "unstop",
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
            if not isinstance(row.payload, dict):
                continue
            before = {
                "location": row.location,
                "country": row.country,
                "is_remote": row.is_remote,
                "meta": row.meta,
            }
            after = transform_row(before, row.payload)
            if before == after:
                continue
            counts["would_change"] += 1
            for field, counter in (
                ("location", "location_changed"),
                ("country", "country_changed"),
                ("is_remote", "remote_changed"),
            ):
                counts[counter] += int(before[field] != after[field])
            counts["pay_added"] += int(
                "compensation" not in (row.meta or {}) and "compensation" in after["meta"]
            )
            if samples < PREVIEW_LIMIT:
                print(json.dumps({"slug": row.slug, "before": before, "after": after}))
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
    parser = argparse.ArgumentParser(
        description="Backfill Unstop role fields from stored payloads."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Preview only (default).")
    mode.add_argument("--apply", action="store_true", help="Write changes in batches of 500.")
    args = parser.parse_args()
    print(f"mode: {'apply' if args.apply else 'dry-run'}", flush=True)
    with Session(make_engine()) as session:
        backfill_unstop_fields(session, apply=args.apply)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
