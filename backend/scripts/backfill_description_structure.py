"""Restore line structure in active opportunity descriptions from stored payloads.

This script deliberately calls each registered crawler adapter's ``parse()``
method instead of duplicating source-specific extraction logic. It never calls
``fetch()``, so it does not make network requests.

Usage:
    uv run python -m scripts.backfill_description_structure
    uv run python -m scripts.backfill_description_structure --apply
"""

import argparse
from collections import Counter, defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, TypedDict

from sqlalchemy import select, text
from sqlalchemy.orm import Session, load_only

from core import models
from core.adapters import RawListing
from core.db import make_engine
from core.textclean import fix_multiline_text
from crawlers.runner import AGGREGATOR_ADAPTERS, ATS_ADAPTERS

BATCH_SIZE = 500
MAINTENANCE_STATEMENT_TIMEOUT = "120s"
PLACEHOLDER_BOARD_TOKEN = "__backfill__"
PLACEHOLDER_COMPANY_NAME = "Unknown company"


class BackfillResult(TypedDict):
    examined: int
    would_update: int
    skipped_no_gain: int
    errors_by_adapter: dict[str, int]
    error_kind_by_adapter: dict[str, str]
    placeholder_board_tokens_by_adapter: dict[str, int]


@dataclass(frozen=True)
class _AdapterInstance:
    adapter: Any
    used_placeholder_board_token: bool


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _adapter_label(source: models.Source) -> str:
    return source.adapter_key or source.slug or "<missing-adapter-key>"


def _has_newline(value: str | None) -> bool:
    return bool(value and ("\n" in value or "\r" in value))


def _adapter_cache_key(
    source: models.Source,
    company: models.Company | None,
) -> tuple[str, str | None, str | None]:
    """Key adapters by the values their constructors actually consume."""
    adapter_key = _adapter_label(source)
    if source.adapter_key in ATS_ADAPTERS:
        board_token = company.ats_board_id if company and company.ats_board_id else None
        company_name = company.name if company and company.name else PLACEHOLDER_COMPANY_NAME
        return (adapter_key, board_token or PLACEHOLDER_BOARD_TOKEN, company_name)
    return (adapter_key, None, None)


def _active_opportunity_batches(
    session: Session,
    *,
    limit: int | None,
    batch_size: int,
) -> Iterator[list[models.Opportunity]]:
    """Yield active opportunities once, in primary-key order."""
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
                        models.Opportunity.company_id,
                        models.Opportunity.description_raw,
                    )
                )
                .where(
                    models.Opportunity.status == "active",
                    models.Opportunity.id > last_id,
                )
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


def _raw_rows_by_opportunity(
    session: Session,
    opportunity_ids: list[int],
) -> dict[int, list[tuple[models.RawListing, models.Source]]]:
    rows_by_opportunity: dict[int, list[tuple[models.RawListing, models.Source]]] = defaultdict(
        list
    )
    rows = session.execute(
        select(models.RawListing, models.Source)
        .join(models.Source, models.Source.id == models.RawListing.source_id)
        .where(models.RawListing.opportunity_id.in_(opportunity_ids))
        .order_by(models.RawListing.opportunity_id, models.RawListing.id)
    ).all()
    for raw_row, source in rows:
        if raw_row.opportunity_id is not None:
            rows_by_opportunity[raw_row.opportunity_id].append((raw_row, source))
    return rows_by_opportunity


def _companies_by_id(
    session: Session,
    opportunities: list[models.Opportunity],
) -> dict[int, models.Company]:
    company_ids = {opportunity.company_id for opportunity in opportunities}
    company_ids.discard(None)
    if not company_ids:
        return {}

    companies = session.scalars(
        select(models.Company)
        .options(
            load_only(
                models.Company.id,
                models.Company.name,
                models.Company.ats_board_id,
            )
        )
        .where(models.Company.id.in_(company_ids))
    ).all()
    return {company.id: company for company in companies}


def _construct_adapter(
    source: models.Source,
    company: models.Company | None,
) -> _AdapterInstance:
    """Construct a parser through the runner's source registries only.

    ATS ``parse()`` methods do not request the network, but their constructors
    still require board/company values. Stored company data is used when it is
    available; the explicit benign token is a fallback for legacy rows that no
    longer have it.
    """
    adapter_key = source.adapter_key
    if adapter_key in ATS_ADAPTERS:
        board_token = company.ats_board_id if company and company.ats_board_id else None
        company_name = company.name if company and company.name else PLACEHOLDER_COMPANY_NAME
        used_placeholder_board_token = board_token is None
        return _AdapterInstance(
            adapter=ATS_ADAPTERS[adapter_key](
                board_token=board_token or PLACEHOLDER_BOARD_TOKEN,
                company_name=company_name,
            ),
            used_placeholder_board_token=used_placeholder_board_token,
        )

    if adapter_key in AGGREGATOR_ADAPTERS:
        return _AdapterInstance(
            adapter=AGGREGATOR_ADAPTERS[adapter_key](),
            used_placeholder_board_token=False,
        )

    raise LookupError("adapter key is not registered by crawlers.runner")


def _raw_listing_for_parse(
    raw_row: models.RawListing,
    source: models.Source,
) -> RawListing:
    if not isinstance(raw_row.raw_payload, dict):
        raise ValueError("raw payload is not an object")

    return RawListing(
        source_slug=source.slug,
        external_id=raw_row.external_id,
        source_url=raw_row.source_url or "",
        content_hash=raw_row.content_hash or "",
        raw_payload=raw_row.raw_payload,
    )


def _close_adapter_clients(adapter_instances: Iterator[_AdapterInstance]) -> None:
    """Close constructor-created HTTP clients without assuming one adapter API."""
    closed_client_ids: set[int] = set()
    for instance in adapter_instances:
        for attribute in ("_client", "client"):
            client = getattr(instance.adapter, attribute, None)
            close = getattr(client, "close", None)
            if id(client) not in closed_client_ids and callable(close):
                close()
                closed_client_ids.add(id(client))


def backfill_description_structure(
    session: Session,
    *,
    apply: bool = False,
    limit: int | None = None,
    batch_size: int = BATCH_SIZE,
) -> BackfillResult:
    """Reparse active stored listings and write only genuinely structured text."""
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")

    examined = 0
    would_update = 0
    skipped_no_gain = 0
    errors_by_adapter: Counter[str] = Counter()
    error_kind_by_adapter: dict[str, str] = {}
    placeholder_board_tokens_by_adapter: Counter[str] = Counter()
    adapter_cache: dict[tuple[str, str | None, str | None], _AdapterInstance] = {}
    adapter_construction_errors: dict[tuple[str, str | None, str | None], str] = {}

    try:
        for opportunities in _active_opportunity_batches(
            session,
            limit=limit,
            batch_size=batch_size,
        ):
            opportunity_ids = [opportunity.id for opportunity in opportunities]
            raw_rows_by_opportunity = _raw_rows_by_opportunity(session, opportunity_ids)
            companies_by_id = _companies_by_id(session, opportunities)

            for opportunity in opportunities:
                examined += 1
                current_description = opportunity.description_raw
                # The backfill is exclusively for already-flat rows. This
                # avoids replacing any existing structured description with a
                # different (and potentially flatter) source representation.
                if _has_newline(current_description):
                    skipped_no_gain += 1
                    continue

                candidates: list[str] = []
                company = companies_by_id.get(opportunity.company_id)
                for raw_row, source in raw_rows_by_opportunity.get(opportunity.id, []):
                    adapter_label = _adapter_label(source)
                    cache_key = _adapter_cache_key(source, company)
                    construction_error = adapter_construction_errors.get(cache_key)
                    if construction_error is not None:
                        errors_by_adapter[adapter_label] += 1
                        error_kind_by_adapter.setdefault(adapter_label, construction_error)
                        continue

                    instance = adapter_cache.get(cache_key)
                    if instance is None:
                        try:
                            instance = _construct_adapter(source, company)
                        except Exception as exc:
                            construction_error = type(exc).__name__
                            adapter_construction_errors[cache_key] = construction_error
                            errors_by_adapter[adapter_label] += 1
                            error_kind_by_adapter.setdefault(adapter_label, construction_error)
                            continue

                        adapter_cache[cache_key] = instance
                        if instance.used_placeholder_board_token:
                            placeholder_board_tokens_by_adapter[adapter_label] += 1

                    try:
                        normalized = instance.adapter.parse(_raw_listing_for_parse(raw_row, source))
                        candidate = fix_multiline_text(normalized.description_raw)
                    except Exception as exc:
                        errors_by_adapter[adapter_label] += 1
                        error_kind_by_adapter.setdefault(adapter_label, type(exc).__name__)
                        continue

                    if (
                        candidate is not None
                        and candidate != current_description
                        and _has_newline(candidate)
                    ):
                        candidates.append(candidate)

                if not candidates:
                    skipped_no_gain += 1
                    continue

                # This mirrors ingest's preference for retaining the fullest
                # available description when a canonical opportunity has more
                # than one source listing.
                replacement = max(candidates, key=len)
                would_update += 1
                if apply:
                    opportunity.description_raw = replacement

            if apply:
                session.commit()
    finally:
        _close_adapter_clients(iter(adapter_cache.values()))

    if not apply:
        session.rollback()

    return {
        "examined": examined,
        "would_update": would_update,
        "skipped_no_gain": skipped_no_gain,
        "errors_by_adapter": dict(sorted(errors_by_adapter.items())),
        "error_kind_by_adapter": dict(sorted(error_kind_by_adapter.items())),
        "placeholder_board_tokens_by_adapter": dict(
            sorted(placeholder_board_tokens_by_adapter.items())
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Restore stored description line structure without fetching the network."
    )
    parser.add_argument("--apply", action="store_true", help="Write changes and commit each batch.")
    parser.add_argument(
        "--limit",
        type=_positive_int,
        help="Maximum active opportunities to examine.",
    )
    parser.add_argument(
        "--batch-size",
        type=_positive_int,
        default=BATCH_SIZE,
        help=f"Active opportunities per commit batch (default: {BATCH_SIZE}).",
    )
    args = parser.parse_args()

    engine = make_engine()
    with Session(engine) as session:
        session.execute(text(f"SET statement_timeout = '{MAINTENANCE_STATEMENT_TIMEOUT}'"))
        result = backfill_description_structure(
            session,
            apply=args.apply,
            limit=args.limit,
            batch_size=args.batch_size,
        )

    print(f"mode: {'apply' if args.apply else 'dry-run'}", flush=True)
    print(f"examined: {result['examined']}", flush=True)
    print(f"would-update: {result['would_update']}", flush=True)
    print(f"skipped-no-gain: {result['skipped_no_gain']}", flush=True)
    if result["errors_by_adapter"]:
        print("errors-by-adapter:", flush=True)
        for adapter_key, count in result["errors_by_adapter"].items():
            print(
                f"  {adapter_key}: {count} ({result['error_kind_by_adapter'][adapter_key]})",
                flush=True,
            )
    else:
        print("errors-by-adapter: none", flush=True)

    if result["placeholder_board_tokens_by_adapter"]:
        print(
            f"placeholder board token ({PLACEHOLDER_BOARD_TOKEN!r}) used by adapter:",
            flush=True,
        )
        for adapter_key, count in result["placeholder_board_tokens_by_adapter"].items():
            print(f"  {adapter_key}: {count}", flush=True)

    if not args.apply:
        print("dry-run only; no rows updated", flush=True)


if __name__ == "__main__":
    main()
