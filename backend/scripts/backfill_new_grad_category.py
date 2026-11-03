"""Correct graduate/campus internships; dry run by default.

Usage:
    uv run python -m scripts.backfill_new_grad_category
    uv run python -m scripts.backfill_new_grad_category --apply
"""

import argparse
import json
import re
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from core import models
from core.db import make_engine
from crawlers.arbeitnow import _text_list as arbeitnow_job_types
from crawlers.himalayas import _job_seniority as himalayas_seniority
from crawlers.jobicy import _as_text as jobicy_level_text
from crawlers.student_relevance import classify_student_role
from pipeline.normalize import classify_category

BATCH_SIZE = 500
PREVIEW_LIMIT = 40
TITLE_SOURCES = {
    "greenhouse",
    "lever",
    "ashby",
    "smartrecruiters",
    "amazon",
    "keka",
    "recruitee",
    "workable",
    "remoteok",
}
RAW_SOURCES = {"arbeitnow", "himalayas", "jobicy"}
_REMOVED_SIGNAL_RE = re.compile(
    r"\b(new[ -]+(grad(uate)?s?|college[ -]+grad(uate)?)|graduate|campus)\b",
    re.IGNORECASE,
)


def is_candidate(current: dict[str, Any]) -> bool:
    return (
        current.get("category") == "internship"
        and current.get("primary_source") in TITLE_SOURCES | RAW_SOURCES
        and bool(_REMOVED_SIGNAL_RE.search(current.get("title") or ""))
    )


def transform_row(
    current: dict[str, Any], raw_payload: dict[str, Any] | None = None
) -> dict[str, str]:
    if not is_candidate(current):
        return {}
    title = current["title"]
    source = current["primary_source"]
    if source in TITLE_SOURCES:
        category = classify_category(title)
    else:
        if raw_payload is None:
            return {}
        if source == "arbeitnow":
            level = arbeitnow_job_types(raw_payload.get("job_types"))
        elif source == "himalayas":
            level = himalayas_seniority(raw_payload)
        else:
            level = jobicy_level_text(raw_payload.get("jobLevel")) or None
        category = classify_student_role(title, level)
    return {"category": "job"} if category == "job" else {}


def backfill_new_grad_category(session: Session, *, apply: bool = False) -> dict[str, Any]:
    counts = dict.fromkeys(("scanned", "would_change", "skipped_no_raw"), 0)
    by_source: dict[str, dict[str, int]] = {}
    last_id = 0
    samples = 0
    while True:
        rows = session.execute(
            select(
                models.Opportunity.id,
                models.Opportunity.title,
                models.Opportunity.category,
                models.Opportunity.primary_source,
            )
            .where(
                models.Opportunity.category == "internship",
                models.Opportunity.id > last_id,
            )
            .order_by(models.Opportunity.id)
            .limit(BATCH_SIZE)
        ).all()
        if not rows:
            break
        raw_ids = [
            row.id
            for row in rows
            if row.primary_source in RAW_SOURCES and is_candidate(dict(row._mapping))
        ]
        payloads: dict[tuple[int, str], dict[str, Any]] = {}
        if raw_ids:
            raw_rows = session.execute(
                select(
                    models.OpportunitySource.opportunity_id,
                    models.Source.slug,
                    models.RawListing.raw_payload,
                )
                .join(models.Source, models.Source.id == models.OpportunitySource.source_id)
                .join(
                    models.RawListing,
                    (models.RawListing.id == models.OpportunitySource.raw_listing_id)
                    & (models.RawListing.source_id == models.OpportunitySource.source_id),
                )
                .where(
                    models.OpportunitySource.opportunity_id.in_(raw_ids),
                    models.Source.slug.in_(RAW_SOURCES),
                )
                .order_by(
                    models.OpportunitySource.is_primary.desc(),
                    models.OpportunitySource.seen_at.desc(),
                    models.OpportunitySource.id.desc(),
                )
            ).all()
            for raw_row in raw_rows:
                if isinstance(raw_row.raw_payload, dict):
                    payloads.setdefault((raw_row.opportunity_id, raw_row.slug), raw_row.raw_payload)
        for row in rows:
            current = dict(row._mapping)
            source = row.primary_source or "unknown"
            source_counts = by_source.setdefault(
                source, dict.fromkeys(("scanned", "would_change", "skipped_no_raw"), 0)
            )
            counts["scanned"] += 1
            source_counts["scanned"] += 1
            if not is_candidate(current):
                continue
            payload = payloads.get((row.id, source))
            if source in RAW_SOURCES and payload is None:
                counts["skipped_no_raw"] += 1
                source_counts["skipped_no_raw"] += 1
                continue
            after = transform_row(current, payload)
            if not after:
                continue
            counts["would_change"] += 1
            source_counts["would_change"] += 1
            if samples < PREVIEW_LIMIT:
                print(json.dumps({"id": row.id, "source": source, "title": row.title}))
                samples += 1
            if apply:
                session.execute(
                    update(models.Opportunity)
                    .where(
                        models.Opportunity.id == row.id,
                        models.Opportunity.category == "internship",
                    )
                    .values(**after)
                )
        last_id = rows[-1].id
        if apply:
            session.commit()
    if not apply:
        session.rollback()
    result = {**counts, "by_source": by_source}
    print(json.dumps(result, sort_keys=True), flush=True)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Correct graduate/campus internship categories.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Preview only (default).")
    mode.add_argument("--apply", action="store_true", help="Write changes in batches of 500.")
    args = parser.parse_args()
    print(f"mode: {'apply' if args.apply else 'dry-run'}", flush=True)
    with Session(make_engine()) as session:
        backfill_new_grad_category(session, apply=args.apply)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
