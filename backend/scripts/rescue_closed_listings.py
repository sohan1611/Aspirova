"""Bounded recent-closure rescue. Dry-run by default; counts only in logs."""

import argparse

from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from core.db import make_engine
from core.freshness import RESCUE_LIMIT, RESCUE_MAX_SECONDS
from pipeline.liveness import check_listing_liveness
from pipeline.revalidate import notify_changed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    changed_slugs: set[str] = set()
    try:
        with Session(make_engine()) as session:
            result = check_listing_liveness(
                session,
                apply=args.apply,
                rescue=True,
                limit=RESCUE_LIMIT,
                max_seconds=RESCUE_MAX_SECONDS,
                concurrency=1,
                batch_size=5,
                changed_slugs=changed_slugs,
            )
    except SQLAlchemyError:
        print("RESCUE: unavailable errors=1", flush=True)
        raise SystemExit(1) from None
    if args.apply:
        notify_changed(changed_slugs)
    print(
        f"RESCUE: scanned={result.scanned} alive={result.alive} gone={result.gone} "
        f"unknown={result.inconclusive} reopened={result.reopened} "
        f"timed_out={int(result.timed_out)} apply={int(args.apply)}",
        flush=True,
    )


if __name__ == "__main__":
    main()
