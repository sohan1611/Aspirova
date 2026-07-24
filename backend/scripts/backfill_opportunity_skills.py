"""Backfill deterministic opportunity skills.

Usage:
    uv run python -m scripts.backfill_opportunity_skills
    uv run python -m scripts.backfill_opportunity_skills --apply
"""

import argparse
from typing import TypedDict

from sqlalchemy import select, text
from sqlalchemy.orm import Session, load_only

from core import models
from core.db import make_engine
from pipeline.skills import extract_opportunity_skills

BATCH_SIZE = 500
MAINTENANCE_STATEMENT_TIMEOUT = "120s"
SAMPLE_SIZE = 10


class BackfillResult(TypedDict):
    scanned: int
    changed: int
    samples: list[str]


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _format_title(title: str) -> str:
    if len(title) > 80:
        return f"{title[:77]}..."
    return title


def _format_skills(skills: list[str]) -> str:
    if not skills:
        return "[]"
    return "[" + ", ".join(skills) + "]"


def backfill_opportunity_skills(
    session: Session,
    *,
    apply: bool = False,
    batch_size: int = BATCH_SIZE,
) -> BackfillResult:
    """Recompute skills for all opportunities, writing only changed rows."""
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")

    scanned_count = 0
    changed_count = 0
    samples: list[str] = []
    last_id = 0

    while True:
        rows = list(
            session.execute(
                select(models.Opportunity)
                .add_columns(models.Company.name)
                .outerjoin(models.Company, models.Company.id == models.Opportunity.company_id)
                .options(
                    load_only(
                        models.Opportunity.id,
                        models.Opportunity.title,
                        models.Opportunity.description_raw,
                        models.Opportunity.skills,
                    )
                )
                .where(models.Opportunity.id > last_id)
                .order_by(models.Opportunity.id)
                .limit(batch_size)
            ).all()
        )
        if not rows:
            break

        for opportunity, company_name in rows:
            scanned_count += 1
            current_skills = list(opportunity.skills or [])
            computed_skills = extract_opportunity_skills(
                opportunity.title,
                opportunity.description_raw or "",
                company_name=company_name or "",
            )
            if current_skills == computed_skills:
                continue

            changed_count += 1
            if len(samples) < SAMPLE_SIZE:
                samples.append(
                    f"- {opportunity.id} | {_format_title(opportunity.title)} | "
                    f"{_format_skills(current_skills)} -> {_format_skills(computed_skills)}"
                )
            if apply:
                opportunity.skills = computed_skills

        last_id = rows[-1][0].id
        if apply:
            session.commit()

    if not apply:
        session.rollback()

    return {"scanned": scanned_count, "changed": changed_count, "samples": samples}


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill deterministic opportunity skills.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Preview only (default).")
    mode.add_argument("--apply", action="store_true", help="Apply backfill and commit.")
    parser.add_argument(
        "--batch-size",
        type=_positive_int,
        default=BATCH_SIZE,
        help=f"Opportunities to scan per batch (default: {BATCH_SIZE}).",
    )
    args = parser.parse_args()

    engine = make_engine()
    with Session(engine) as session:
        session.execute(text(f"SET statement_timeout = '{MAINTENANCE_STATEMENT_TIMEOUT}'"))
        result = backfill_opportunity_skills(
            session,
            apply=args.apply,
            batch_size=args.batch_size,
        )

    action = "updated" if args.apply else "would change"
    print(f"mode: {'apply' if args.apply else 'dry-run'}", flush=True)
    print(f"opportunities scanned: {result['scanned']}", flush=True)
    print(f"opportunities {action}: {result['changed']}", flush=True)
    if result["samples"]:
        print("sample:", flush=True)
        for row in result["samples"]:
            print(row, flush=True)
    if not args.apply:
        print("dry-run only; no rows updated", flush=True)


if __name__ == "__main__":
    main()
