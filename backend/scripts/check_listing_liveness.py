"""Check stale undated listings and mark confirmed removed listings closed.

Usage:
    uv run python -m scripts.check_listing_liveness
    uv run python -m scripts.check_listing_liveness --apply
"""

import argparse

from sqlalchemy import text
from sqlalchemy.orm import Session

from core.db import make_engine
from pipeline.liveness import DEFAULT_LIMIT, DEFAULT_MAX_SECONDS, check_listing_liveness

MAINTENANCE_STATEMENT_TIMEOUT = "120s"


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check stale undated listing URLs for conservative liveness."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Preview only (default).")
    mode.add_argument("--apply", action="store_true", help="Mark confirmed closed rows.")
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
    with Session(engine) as session:
        session.execute(text(f"SET statement_timeout = '{MAINTENANCE_STATEMENT_TIMEOUT}'"))
        result = check_listing_liveness(
            session,
            apply=args.apply,
            limit=args.limit,
            max_seconds=args.max_seconds,
        )

    print(f"mode: {'apply' if args.apply else 'dry-run'}", flush=True)
    print(f"listings scanned: {result.scanned}", flush=True)
    print(f"listings closed: {result.closed}", flush=True)
    print(f"listings alive: {result.alive}", flush=True)
    print(f"listings inconclusive: {result.inconclusive}", flush=True)
    print(f"time budget exhausted: {'yes' if result.timed_out else 'no'}", flush=True)
    if not args.apply:
        print("dry-run only; no rows updated", flush=True)


if __name__ == "__main__":
    main()
