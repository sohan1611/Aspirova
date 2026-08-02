"""Verify the curated programmes registry and print the needs-review report.

Usage:
    uv run python -m scripts.verify_programmes
    uv run python -m scripts.verify_programmes --apply
"""

import argparse

from sqlalchemy import text
from sqlalchemy.orm import Session

from core.db import make_engine
from pipeline.programme_verification import (
    DEFAULT_PROGRAMME_LIMIT,
    DEFAULT_PROGRAMME_MAX_SECONDS,
    ProgrammeEditionReviewItem,
    ProgrammeReviewItem,
    ProgrammeReviewReport,
    verify_programmes,
)

MAINTENANCE_STATEMENT_TIMEOUT = "120s"


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _format_item(item: ProgrammeReviewItem | ProgrammeEditionReviewItem) -> str:
    parts = [item.programme_slug, item.programme_name, item.reason]
    if isinstance(item, ProgrammeEditionReviewItem):
        parts.append(f"edition={item.year}")
        parts.append(f"status={item.status}")
        if item.source_url:
            parts.append(f"source_url={item.source_url}")
    elif item.programme_url:
        parts.append(f"url={item.programme_url}")
    return "- " + " | ".join(parts)


def _print_bucket(
    title: str, items: list[ProgrammeReviewItem] | list[ProgrammeEditionReviewItem]
) -> None:
    print(f"{title} ({len(items)})", flush=True)
    if not items:
        print("- none", flush=True)
        return
    for item in items:
        print(_format_item(item), flush=True)


def _print_report(report: ProgrammeReviewReport) -> None:
    _print_bucket("dead_urls", report.dead_urls)
    _print_bucket("window_arrived", report.window_arrived)
    _print_bucket("stale_verification", report.stale_verification)
    _print_bucket("overdue_close", report.overdue_close)
    _print_bucket("missing_current_year_edition", report.missing_current_year_edition)
    print(
        "summary: "
        f"total_flags={report.total_flags}, "
        f"dead_urls={len(report.dead_urls)}, "
        f"window_arrived={len(report.window_arrived)}, "
        f"stale_verification={len(report.stale_verification)}, "
        f"overdue_close={len(report.overdue_close)}, "
        f"missing_current_year_edition={len(report.missing_current_year_edition)}, "
        f"liveness_scanned={report.liveness_scanned}, "
        f"liveness_alive={report.liveness_alive}, "
        f"liveness_inconclusive={report.liveness_inconclusive}, "
        f"liveness_timed_out={'yes' if report.liveness_timed_out else 'no'}, "
        f"editions_closed={report.closed_updated}",
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify programme URLs and report editions needing human review."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Preview only (default).")
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Close overdue open/announced editions with past closes_at.",
    )
    parser.add_argument(
        "--limit",
        type=_positive_int,
        default=DEFAULT_PROGRAMME_LIMIT,
        help=f"Maximum programme URLs to scan (default: {DEFAULT_PROGRAMME_LIMIT}).",
    )
    parser.add_argument(
        "--max-seconds",
        type=_positive_int,
        default=DEFAULT_PROGRAMME_MAX_SECONDS,
        help=(
            "Wall-clock budget in seconds for HTTP liveness "
            f"(default: {DEFAULT_PROGRAMME_MAX_SECONDS})."
        ),
    )
    args = parser.parse_args()

    engine = make_engine()
    with Session(engine) as session:
        session.execute(text(f"SET statement_timeout = '{MAINTENANCE_STATEMENT_TIMEOUT}'"))
        report = verify_programmes(
            session,
            apply=args.apply,
            limit=args.limit,
            max_seconds=args.max_seconds,
        )
        if args.apply:
            session.commit()
        else:
            session.rollback()

    print(f"mode: {'apply' if args.apply else 'dry-run'}", flush=True)
    _print_report(report)
    if not args.apply:
        print("dry-run only; no rows updated", flush=True)


if __name__ == "__main__":
    main()
