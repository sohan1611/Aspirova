"""Bounded opportunity-enrichment worker for scheduled batch execution."""

import argparse

from sqlalchemy.orm import Session

from core.db import make_engine
from pipeline.enrich import enrich_pending


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100, help="Maximum opportunities to enrich")
    args = parser.parse_args()

    engine = make_engine()
    with Session(engine) as session:
        result = enrich_pending(session, limit=args.limit)
        print(f"opportunity enrichment: {result}", flush=True)


if __name__ == "__main__":
    main()
