"""Backfill Unstop locations and countries from stored raw payloads.

This script reparses existing raw Unstop payloads through ``UnstopAdapter``.
It does not fetch from Unstop and does not trigger page revalidation.

Usage:
    uv run python -m scripts.backfill_unstop_location
    uv run python -m scripts.backfill_unstop_location --limit 20
    uv run python -m scripts.backfill_unstop_location --apply
"""

from __future__ import annotations

import argparse
from collections.abc import Iterator
from typing import TypedDict

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session, load_only

from core import models
from core.adapters import RawListing
from core.db import make_engine
from crawlers.unstop import UnstopAdapter
from pipeline.location_country import derive_country

BATCH_SIZE = 500
MAINTENANCE_STATEMENT_TIMEOUT = "120s"
BOGUS_MODALITY_LOCATIONS = frozenset({"offline", "online"})


class BackfillResult(TypedDict):
    examined: int
    would_update: int
    skipped: int
    errors: int


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    text_value = value.strip()
    return text_value or None


def _is_bogus_modality_location(value: str | None) -> bool:
    clean_value = _clean(value)
    return clean_value is not None and clean_value.casefold() in BOGUS_MODALITY_LOCATIONS


def _should_update_location(
    *,
    current_location: str | None,
    computed_location: str | None,
    current_country: str | None,
) -> bool:
    current_location = _clean(current_location)
    computed_location = _clean(computed_location)

    if current_location == computed_location:
        return False

    if computed_location is None:
        return _is_bogus_modality_location(current_location)

    if current_location is None or _is_bogus_modality_location(current_location):
        return True

    return _clean(current_country) is None and derive_country(computed_location) is not None


def _should_update_country(
    *,
    current_country: str | None,
    computed_country: str | None,
) -> bool:
    computed_country = _clean(computed_country)
    return computed_country is not None and _clean(current_country) != computed_country


def _raw_listing_for_parse(raw_row: models.RawListing) -> RawListing:
    if not isinstance(raw_row.raw_payload, dict):
        raise ValueError("raw payload is not an object")

    return RawListing(
        source_slug="unstop",
        external_id=raw_row.external_id,
        source_url=raw_row.source_url or "",
        content_hash=raw_row.content_hash or "",
        raw_payload=raw_row.raw_payload,
    )


def _unstop_opportunity_batches(
    session: Session,
    *,
    limit: int | None,
    batch_size: int,
) -> Iterator[list[tuple[models.Opportunity, models.RawListing]]]:
    raw_choice = (
        select(
            models.RawListing.opportunity_id.label("opportunity_id"),
            func.min(models.RawListing.id).label("raw_listing_id"),
        )
        .join(models.Source, models.Source.id == models.RawListing.source_id)
        .where(
            models.RawListing.opportunity_id.is_not(None),
            models.RawListing.raw_payload.is_not(None),
            or_(models.Source.slug == "unstop", models.Source.adapter_key == "unstop"),
        )
        .group_by(models.RawListing.opportunity_id)
        .subquery()
    )

    last_id = 0
    remaining = limit

    while remaining is None or remaining > 0:
        current_size = batch_size if remaining is None else min(batch_size, remaining)
        rows = list(
            session.execute(
                select(models.Opportunity, models.RawListing)
                .join(raw_choice, raw_choice.c.opportunity_id == models.Opportunity.id)
                .join(models.RawListing, models.RawListing.id == raw_choice.c.raw_listing_id)
                .options(
                    load_only(
                        models.Opportunity.id,
                        models.Opportunity.primary_source,
                        models.Opportunity.location,
                        models.Opportunity.country,
                    ),
                    load_only(
                        models.RawListing.id,
                        models.RawListing.external_id,
                        models.RawListing.source_url,
                        models.RawListing.content_hash,
                        models.RawListing.raw_payload,
                    ),
                )
                .where(
                    models.Opportunity.primary_source == "unstop",
                    models.Opportunity.id > last_id,
                )
                .order_by(models.Opportunity.id)
                .limit(current_size)
            ).all()
        )
        if not rows:
            return

        last_id = rows[-1][0].id
        yield rows
        if remaining is not None:
            remaining -= len(rows)


def backfill_unstop_location(
    session: Session,
    *,
    apply: bool = False,
    limit: int | None = None,
    batch_size: int = BATCH_SIZE,
) -> BackfillResult:
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")

    examined = 0
    would_update = 0
    skipped = 0
    errors = 0
    adapter = UnstopAdapter()

    try:
        for rows in _unstop_opportunity_batches(
            session,
            limit=limit,
            batch_size=batch_size,
        ):
            for opportunity, raw_row in rows:
                examined += 1
                try:
                    normalized = adapter.parse(_raw_listing_for_parse(raw_row))
                except Exception:
                    errors += 1
                    continue

                computed_location = _clean(normalized.location)
                computed_country = derive_country(computed_location)
                update_location = _should_update_location(
                    current_location=opportunity.location,
                    computed_location=computed_location,
                    current_country=opportunity.country,
                )
                update_country = _should_update_country(
                    current_country=opportunity.country,
                    computed_country=computed_country,
                )

                if not update_location and not update_country:
                    skipped += 1
                    continue

                would_update += 1
                if apply:
                    if update_location:
                        opportunity.location = computed_location
                    if update_country:
                        opportunity.country = computed_country

            if apply:
                session.commit()
    finally:
        adapter._client.close()

    if not apply:
        session.rollback()

    return {
        "examined": examined,
        "would_update": would_update,
        "skipped": skipped,
        "errors": errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill Unstop locations/countries from stored raw payloads."
    )
    parser.add_argument("--apply", action="store_true", help="Write changes and commit batches.")
    parser.add_argument(
        "--limit",
        type=_positive_int,
        help="Maximum Unstop opportunities to examine.",
    )
    args = parser.parse_args()

    engine = make_engine()
    with Session(engine) as session:
        session.execute(text(f"SET statement_timeout = '{MAINTENANCE_STATEMENT_TIMEOUT}'"))
        result = backfill_unstop_location(
            session,
            apply=args.apply,
            limit=args.limit,
        )

    print(f"mode: {'apply' if args.apply else 'dry-run'}", flush=True)
    print(f"examined: {result['examined']}", flush=True)
    print(f"would-update: {result['would_update']}", flush=True)
    print(f"skipped: {result['skipped']}", flush=True)
    print(f"errors: {result['errors']}", flush=True)
    if not args.apply:
        print("dry-run only; no rows updated", flush=True)


if __name__ == "__main__":
    main()
