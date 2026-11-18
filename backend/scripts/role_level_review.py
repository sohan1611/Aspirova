"""Read-only role-level review and student-search benchmark.

From backend/, with DATABASE_URL explicitly set to the database you choose:
    uv run python -m scripts.role_level_review review --csv role-level-review.csv
    uv run python -m scripts.role_level_review benchmark --csv role-level-benchmark.csv

Stdout contains counts only; employer text and benchmark exceptions go to CSV.
All database queries run in read-only transactions. No .env file is required.
"""

import argparse
import csv
import os
import re
from collections import Counter
from pathlib import Path
from typing import TextIO

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from core import models
from core.eligibility import (
    ELIGIBLE_EXPERIENCED_ONLY_META_KEY,
    STUDENT_FACING_ELIGIBILITY_TAGS,
    is_eligible_experienced_only,
)
from core.role_level import AMBIGUOUS_TITLE_PATTERN, classify_role_level

STUDENT_QUERIES = (
    "software engineer",
    "data analyst",
    "product",
    "marketing",
    "finance",
    "design",
    "research",
    "consulting",
    "sales",
    "operations",
    "mechanical",
    "civil",
    "electrical",
    "hr",
    "content",
    "cybersecurity",
    "cloud",
    "ml",
    "frontend",
    "business analyst",
)
CSV_FIELDS = ("slug", "title", "company", "level", "evidence")
STUDENT_LEVELS = {"internship", "apprenticeship", "graduate"}


def needs_review(title: str, category: str | None, meta: dict | None, slug: str) -> bool:
    meta = meta if isinstance(meta, dict) else {}
    result = classify_role_level(title, category, meta, slug)
    if result["level"] == "unknown" and re.search(AMBIGUOUS_TITLE_PATTERN, title, re.IGNORECASE):
        return True
    title_level = classify_role_level(title, overrides={})["level"]
    tags = meta.get("eligibility")
    clean_tags = [tag for tag in tags if isinstance(tag, str)] if isinstance(tags, list) else []
    student_tags = isinstance(tags, list) and any(
        isinstance(tag, str) and tag in STUDENT_FACING_ELIGIBILITY_TAGS for tag in tags
    )
    return (
        title_level in STUDENT_LEVELS
        and (
            meta.get(ELIGIBLE_EXPERIENCED_ONLY_META_KEY) is True
            or is_eligible_experienced_only(clean_tags)
        )
    ) or (title_level == "experienced" and student_tags)


def _csv_row(opportunity: models.Opportunity, company: str | None) -> dict:
    result = classify_role_level(
        opportunity.title, opportunity.category, opportunity.meta, opportunity.slug
    )
    return {
        "slug": opportunity.slug,
        "title": opportunity.title,
        "company": company or "",
        "level": result["level"],
        "evidence": result["evidence"],
    }


def write_review(db: Session, output: TextIO) -> dict[str, int]:
    writer = csv.DictWriter(output, fieldnames=CSV_FIELDS)
    writer.writeheader()
    counts = Counter(scanned=0, review=0)
    # Select only the columns needed for the report, in bounded batches.
    rows = db.execute(
        select(
            models.Opportunity.slug,
            models.Opportunity.title,
            models.Opportunity.category,
            models.Opportunity.meta,
            models.Company.name.label("company"),
        )
        .outerjoin(models.Company, models.Opportunity.company_id == models.Company.id)
        .order_by(models.Opportunity.id)
        .execution_options(yield_per=500)
    )
    for row in rows:
        counts["scanned"] += 1
        if needs_review(row.title, row.category, row.meta, row.slug):
            result = classify_role_level(row.title, row.category, row.meta, row.slug)
            writer.writerow(
                {
                    "slug": row.slug,
                    "title": row.title,
                    "company": row.company or "",
                    "level": result["level"],
                    "evidence": result["evidence"],
                }
            )
            counts["review"] += 1
    return dict(counts)


def write_benchmark(db: Session, output: TextIO) -> list[dict]:
    # Reuse the API's filters, FTS/trigram fallback and ordering; no HTTP/cache.
    from api.opportunity_loading import opportunity_list_load_options
    from api.search import _search_ordering, search_base_filters, search_predicate

    writer = csv.DictWriter(output, fieldnames=("query", *CSV_FIELDS))
    writer.writeheader()
    counts = []
    for query in STUDENT_QUERIES:
        filters = search_base_filters()
        predicate, relevance, _ = search_predicate(db, query, filters)
        rows = (
            db.scalars(
                select(models.Opportunity)
                .options(*opportunity_list_load_options())
                .where(*filters, predicate)
                .order_by(*_search_ordering("student", relevance, True))
                .limit(20)
            )
            .unique()
            .all()
        )
        experienced = 0
        for opportunity in rows:
            row = _csv_row(opportunity, opportunity.company.name if opportunity.company else None)
            if row["level"] == "experienced":
                writer.writerow({"query": query, **row})
                experienced += 1
        counts.append({"query": query, "top20": len(rows), "experienced": experienced})
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("review", "benchmark"))
    parser.add_argument("--csv", type=Path, required=True)
    args = parser.parse_args()
    if not os.environ.get("DATABASE_URL", "").strip():
        parser.error("Set DATABASE_URL explicitly to the database you choose")

    from core.config import get_settings
    from core.db import make_engine

    get_settings.cache_clear()
    engine = make_engine(execution_options={"postgresql_readonly": True})
    try:
        with Session(engine) as db, args.csv.open("w", newline="", encoding="utf-8") as output:
            if args.command == "review":
                counts = write_review(db, output)
                print(f"scanned={counts['scanned']} review={counts['review']}")
            else:
                for row in write_benchmark(db, output):
                    print(f"{row['query']}: top20={row['top20']} experienced={row['experienced']}")
    except SQLAlchemyError:
        # Database exceptions can contain connection credentials; do not echo them.
        parser.exit(1, "Database query failed; no database changes were made.\n")
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
