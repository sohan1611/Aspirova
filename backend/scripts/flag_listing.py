"""Flag or clear a founder-reviewed listing. No schema changes; dry-run supported."""

import argparse
from datetime import datetime, timezone
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from core import models
from core.db import make_engine
from core.listing_safety import has_manual_closure, safety_flag
from pipeline.revalidate import (
    LOCAL_REVALIDATION_WARNING,
    notify_changed,
    refresh_api_details,
)


def https_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        if parsed.scheme == "https" and parsed.hostname and not parsed.username:
            return value
    except ValueError:
        pass
    raise argparse.ArgumentTypeError("--source-url must be an absolute https URL")


def flag_listing(
    session: Session,
    *,
    slug: str,
    kind: str | None = None,
    note: str | None = None,
    source_url: str | None = None,
    clear: bool = False,
    now: datetime | None = None,
) -> bool:
    """Mutate one locked row; caller commits or rolls back. Return whether changed."""
    if not clear:
        if kind not in {"scam", "recalled"} or not note or not note.strip():
            raise ValueError("A kind and non-blank note are required")
        if source_url:
            https_url(source_url)
    opportunity = session.scalar(
        select(models.Opportunity)
        .where(models.Opportunity.slug == slug)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if opportunity is None:
        raise ValueError(f"Listing not found: {slug}")
    previous = safety_flag(opportunity)
    meta = dict(opportunity.meta or {})
    if clear:
        if previous is None:
            return False
        opportunity.status = previous["prior_status"]
        # Only undo a closure owned by this flag, never an earlier source closure.
        if (
            previous.get("set_closed_at")
            and opportunity.closed_at is not None
            and not has_manual_closure(opportunity)
        ):
            if opportunity.closed_at == datetime.fromisoformat(previous["set_closed_at"]):
                opportunity.closed_at = None
        meta.pop("safety", None)
    else:
        note = note.strip()
        if (
            previous
            and opportunity.status == "withdrawn"
            and opportunity.closed_at is not None
            and all(
                previous.get(key) == value
                for key, value in (("kind", kind), ("note", note), ("source_url", source_url))
            )
        ):
            return False
        current = now or datetime.now(timezone.utc)
        flag = {
            "kind": kind,
            "note": note,
            "source_url": source_url,
            "flagged_at": current.isoformat(),
            "prior_status": previous["prior_status"] if previous else opportunity.status,
            "set_closed_at": previous.get("set_closed_at") if previous else None,
        }
        if opportunity.closed_at is None:
            opportunity.closed_at = current
            flag["set_closed_at"] = current.isoformat()
        opportunity.status = "withdrawn"
        meta["safety"] = flag
    opportunity.meta = meta or None
    return True


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--kind", choices=("scam", "recalled"))
    parser.add_argument("--note")
    parser.add_argument("--source-url", type=https_url)
    parser.add_argument("--clear", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.clear and (args.kind or args.note or args.source_url):
        parser.error("--clear cannot be combined with --kind, --note or --source-url")
    if not args.clear and (not args.kind or not args.note or not args.note.strip()):
        parser.error("--kind and a non-blank --note are required unless using --clear")
    engine = make_engine()
    try:
        with Session(engine) as session:
            try:
                changed = flag_listing(
                    session,
                    slug=args.slug,
                    kind=args.kind,
                    note=args.note,
                    source_url=args.source_url,
                    clear=args.clear,
                )
            except ValueError as exc:
                parser.error(str(exc))
            opportunity = session.scalar(
                select(models.Opportunity).where(models.Opportunity.slug == args.slug)
            )
            state = f"status={opportunity.status}; closed_at={opportunity.closed_at}"
            action = (
                f"{state}; removed safety flag"
                if args.clear
                else (
                    f"{state}; safety.kind={args.kind}; note={args.note!r}; "
                    f"source_url={args.source_url or 'Aspirova listing page'}"
                )
            )
            print(
                f"{args.slug}: {action if changed else 'unchanged'}"
                f"{' (dry run, rolled back)' if args.dry_run else ''}"
            )
            if args.dry_run:
                session.rollback()
            else:
                session.commit()
                # Retry cache invalidation even for an idempotent repeat command.
                refresh = refresh_api_details([args.slug])
                print(f"API refresh: {refresh}")
                result = notify_changed([args.slug], landing=False)
                print(f"Frontend revalidation: {result}")
                if result["status"] == "unconfigured":
                    print(LOCAL_REVALIDATION_WARNING)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
