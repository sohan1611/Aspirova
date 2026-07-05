"""Notification worker entrypoint (Doc handoffs/PHASE-2-HANDOFF.md sec
5). Runs on GitHub Actions cron, never the Render web dyno (Doc 02 sec
3.3's "crawler never runs on the API process" principle, extended here).

Usage:
  uv run python -m scripts.notification_worker --digest
  uv run python -m scripts.notification_worker --instant-alerts
"""

import argparse

from sqlalchemy.orm import Session

from core.db import make_engine
from pipeline.notifications import send_daily_digests, send_instant_alerts


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--digest", action="store_true", help="Send daily digest emails")
    group.add_argument(
        "--instant-alerts", action="store_true", help="Send instant dream-company alerts"
    )
    args = parser.parse_args()

    engine = make_engine()
    with Session(engine) as session:
        if args.digest:
            result = send_daily_digests(session)
            print(f"daily digests: {result}", flush=True)
        else:
            result = send_instant_alerts(session)
            print(f"instant alerts: {result}", flush=True)


if __name__ == "__main__":
    main()
