"""Repair mojibake in canonical opportunity and company text."""

import argparse
from collections.abc import Iterator
from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session, load_only
from sqlalchemy.orm.attributes import InstrumentedAttribute

from core import models
from core.db import make_engine
from core.textclean import fix_text

BATCH_SIZE = 500
ModelT = TypeVar("ModelT", models.Opportunity, models.Company)


def _batches(
    session: Session,
    model: type[ModelT],
    *,
    columns: tuple[InstrumentedAttribute, ...],
    limit: int | None,
    batch_size: int,
) -> Iterator[list[ModelT]]:
    last_id = 0
    remaining = limit
    while remaining is None or remaining > 0:
        current_size = batch_size if remaining is None else min(batch_size, remaining)
        rows = list(
            session.scalars(
                select(model)
                .options(load_only(model.id, *columns))
                .where(model.id > last_id)
                .order_by(model.id)
                .limit(current_size)
            ).all()
        )
        if not rows:
            return
        batch_last_id = rows[-1].id
        yield rows
        last_id = batch_last_id
        if remaining is not None:
            remaining -= len(rows)


def _fix_opportunities(rows: list[models.Opportunity], *, dry_run: bool) -> int:
    fixed = 0
    for row in rows:
        changes = {
            field: cleaned
            for field in ("title", "location", "description_raw")
            if (cleaned := fix_text(getattr(row, field))) != getattr(row, field)
        }
        if not changes:
            continue
        fixed += 1
        if not dry_run:
            for field, value in changes.items():
                setattr(row, field, value)
    return fixed


def _fix_companies(rows: list[models.Company], *, dry_run: bool) -> int:
    fixed = 0
    for row in rows:
        changes = {
            field: cleaned
            for field in ("name", "name_normalized")
            if (cleaned := fix_text(getattr(row, field))) != getattr(row, field)
        }
        if not changes:
            continue
        fixed += 1
        if not dry_run:
            for field, value in changes.items():
                setattr(row, field, value)
    return fixed


def fix_encoding(
    session: Session,
    *,
    limit: int | None = None,
    batch_size: int = BATCH_SIZE,
    dry_run: bool = False,
) -> int:
    """Fix up to ``limit`` rows from each table."""
    fixed = 0
    targets = (
        (
            models.Opportunity,
            (
                models.Opportunity.title,
                models.Opportunity.location,
                models.Opportunity.description_raw,
            ),
            _fix_opportunities,
        ),
        (
            models.Company,
            (models.Company.name, models.Company.name_normalized),
            _fix_companies,
        ),
    )
    for model, columns, fixer in targets:
        for rows in _batches(
            session,
            model,
            columns=columns,
            limit=limit,
            batch_size=batch_size,
        ):
            fixed += fixer(rows, dry_run=dry_run)
            if not dry_run:
                session.commit()
    if dry_run:
        session.rollback()
    return fixed


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=_positive_int, help="Maximum rows per table to scan")
    parser.add_argument("--dry-run", action="store_true", help="Report changes without writing")
    args = parser.parse_args()

    engine = make_engine()
    with Session(engine) as session:
        fixed = fix_encoding(session, limit=args.limit, dry_run=args.dry_run)
    action = "would fix" if args.dry_run else "fixed"
    print(f"encoding backfill: {action} {fixed} rows", flush=True)


if __name__ == "__main__":
    main()
