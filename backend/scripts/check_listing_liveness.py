"""Check destinations on source cadence and close confirmed removed listings.

Usage:
    uv run python -m scripts.check_listing_liveness
    uv run python -m scripts.check_listing_liveness --apply
"""

import argparse

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from core.db import make_engine
from pipeline.liveness import (
    DEFAULT_LIMIT,
    DEFAULT_MAX_SECONDS,
    INCONCLUSIVE_REASONS,
    SKIP_REASONS,
    check_listing_liveness,
)
from pipeline.revalidate import notify_changed

MAINTENANCE_STATEMENT_TIMEOUT = "120s"


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Refresh listing verification on source cadence with conservative closure."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Preview only (default).")
    mode.add_argument(
        "--apply", action="store_true", help="Record checks and apply proven closure/reopen."
    )
    parser.add_argument(
        "--limit",
        type=_positive_int,
        default=DEFAULT_LIMIT,
        help=f"Maximum listings to scan (default: {DEFAULT_LIMIT}).",
    )
    parser.add_argument(
        "--max-seconds",
        type=_positive_int,
        default=DEFAULT_MAX_SECONDS,
        help=f"Wall-clock budget in seconds (default: {DEFAULT_MAX_SECONDS}).",
    )
    args = parser.parse_args()

    engine = make_engine()
    changed_slugs: set[str] = set()
    with Session(engine) as session:
        session.execute(text(f"SET statement_timeout = '{MAINTENANCE_STATEMENT_TIMEOUT}'"))
        result = check_listing_liveness(
            session,
            apply=args.apply,
            limit=args.limit,
            max_seconds=args.max_seconds,
            freshness_mode=True,
            changed_slugs=changed_slugs if args.apply else None,
        )

    if args.apply:
        notify_changed(changed_slugs)
    print(f"mode: {'apply' if args.apply else 'dry-run'}", flush=True)
    print(f"listings scanned: {result.scanned}", flush=True)
    print(f"listings closed: {result.closed}", flush=True)
    print(f"listings alive: {result.alive}", flush=True)
    print(f"listings reopened: {result.reopened}", flush=True)
    print(f"listings inconclusive: {result.inconclusive}", flush=True)
    print(f"time budget exhausted: {'yes' if result.timed_out else 'no'}", flush=True)
    if not args.apply:
        print("dry-run only; no rows updated", flush=True)
    for source, counts in sorted(result.by_source.items()):
        print(
            f"LIVENESS SOURCE {source}: scanned={counts.scanned} alive={counts.alive} "
            f"closed={counts.closed} reopened={counts.reopened} inconclusive={counts.inconclusive}",
            flush=True,
        )
        reasons = " ".join(f"{reason}={counts.reasons[reason]}" for reason in INCONCLUSIVE_REASONS)
        print(f"LIVENESS INCONCLUSIVE {source}: {reasons}", flush=True)
        if counts.skipped:
            skips = " ".join(f"{reason}={counts.reasons[reason]}" for reason in SKIP_REASONS)
            print(f"LIVENESS SKIPPED {source}: total={counts.skipped} {skips}", flush=True)
    if result.workday_list:
        counters = ("requests", "pages", "verified", *INCONCLUSIVE_REASONS, "404", "410")
        details = " ".join(f"{key}={result.workday_list[key]}" for key in counters)
        print(f"LIVENESS WORKDAY LIST: {details}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except SQLAlchemyError:
        print("LIVENESS: unavailable errors=1", flush=True)
        raise SystemExit(1) from None
