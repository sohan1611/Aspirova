"""Founder CLI: counts, retry due intents, and dry-run-first dead-letter recovery.

python -m scripts.delivery_health counts
python -m scripts.delivery_health requeue             # dry run
python -m scripts.delivery_health requeue --apply     # safe transient dead rows only
python -m scripts.delivery_health drain
"""

import argparse
import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core import models
from core.db import make_engine
from core.email_outbox import drain, requeue_dead


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["counts", "requeue", "drain"])
    parser.add_argument("--apply", action="store_true", help="Apply safe dead-letter recovery")
    args = parser.parse_args()
    with Session(make_engine()) as session:
        if args.command == "counts":
            rows = session.execute(
                select(models.EmailOutbox.status, models.EmailOutbox.kind, func.count())
                .group_by(models.EmailOutbox.status, models.EmailOutbox.kind)
                .order_by(models.EmailOutbox.kind, models.EmailOutbox.status)
            )
            print(json.dumps([{"status": s, "kind": k, "count": n} for s, k, n in rows]))
        elif args.command == "requeue":
            counts = requeue_dead(session, apply=args.apply)
            session.commit() if args.apply else session.rollback()
            print(json.dumps({"applied": args.apply, **counts}))
        else:
            counts = drain(session)
            print("email delivery: " + json.dumps(counts, sort_keys=True))
            if counts.get("dead", 0) + counts.get("failed", 0):
                raise SystemExit(1)


if __name__ == "__main__":
    main()
