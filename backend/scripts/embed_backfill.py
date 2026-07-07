"""Bounded opportunity-embedding backfill worker for scheduled batch execution."""

import argparse

from sqlalchemy.orm import Session

from core.db import make_engine
from pipeline.enrich import backfill_embeddings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100, help="Maximum opportunities to embed")
    args = parser.parse_args()

    engine = make_engine()
    with Session(engine) as session:
        result = backfill_embeddings(session, limit=args.limit)
        print(f"opportunity embedding backfill: {result}", flush=True)


if __name__ == "__main__":
    main()
