"""Founder-only report queue. All mutation helpers leave the transaction to the caller."""

import argparse
import json
import logging
import math
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from html import escape
from statistics import median

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from core import models
from core.config import get_settings
from core.db import make_engine
from core.email_client import send_email
from core.email_components import status_panel
from core.email_templates import email_layout
from core.mail_recipients import lock_recipient
from pipeline.revalidate import (
    LOCAL_REVALIDATION_WARNING,
    notify_changed,
    refresh_api_details,
)
from scripts.flag_listing import flag_listing

logger = logging.getLogger(__name__)
# Date-only cutoffs follow the government adapters: 23:59:59 Asia/Kolkata.
INDIA_TIME = timezone(timedelta(hours=5, minutes=30))
RESOLUTIONS = (
    "corrected",
    "closed_listing",
    "withdrawn",
    "duplicate",
    "no_change",
    "not_reproducible",
    "spam",
)
CATEGORIES = (
    "dead_link",
    "wrong_deadline",
    "wrong_company",
    "duplicate",
    "wrong_info",
    "scam",
    "bug",
    "other",
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def overdue(report: models.BugReport, now: datetime) -> bool:
    age = now - report.created_at
    return (report.status == "open" and age > timedelta(hours=48)) or (
        report.status == "triaged" and age > timedelta(days=7)
    )


def list_reports(
    session: Session,
    *,
    status: str = "open",
    category: str | None = None,
    limit: int = 50,
    now: datetime | None = None,
) -> list[dict]:
    if status not in {"open", "triaged", "resolved", "all"} or limit < 1:
        raise ValueError("Invalid status or limit")
    query = select(models.BugReport, models.Opportunity.slug).outerjoin(
        models.Opportunity, models.Opportunity.id == models.BugReport.opportunity_id
    )
    if status != "all":
        query = query.where(models.BugReport.status == status)
    if category:
        query = query.where(models.BugReport.category == category)
    current = now or utcnow()
    return [
        {
            "reference": report.reference,
            "age_hours": round((current - report.created_at).total_seconds() / 3600, 1),
            "category": report.category,
            "status": report.status,
            "listing": slug,
            "message": report.message[:80],
            "sla": "OVERDUE" if overdue(report, current) else "",
        }
        for report, slug in session.execute(
            query.order_by(models.BugReport.created_at).limit(limit)
        )
    ]


def get_report(session: Session, reference: str, *, lock: bool = False) -> models.BugReport:
    query = select(models.BugReport).where(models.BugReport.reference == reference.upper())
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    report = session.scalar(query)
    if report is None:
        raise ValueError(f"Report not found: {reference}")
    return report


def show_report(session: Session, reference: str) -> dict:
    report = get_report(session, reference)
    result = {
        column.key: getattr(report, column.key) for column in inspect(models.BugReport).columns
    }
    opportunity = (
        session.get(models.Opportunity, report.opportunity_id) if report.opportunity_id else None
    )
    result["listing"] = None
    result["other_reports"] = []
    if opportunity:
        meta = opportunity.meta or {}
        result["listing"] = {
            "slug": opportunity.slug,
            "title": opportunity.title,
            "status": opportunity.status,
            "apply_url": opportunity.apply_url,
            "deadline": opportunity.deadline,
            "deadline_confidence": opportunity.deadline_confidence,
            "closed_at": opportunity.closed_at,
            "closed_reason": meta.get("closed_reason"),
            "safety": meta.get("safety"),
            "company": opportunity.company.slug if opportunity.company else None,
        }
        result["other_reports"] = [
            {
                "reference": other.reference,
                "status": other.status,
                "category": other.category,
                "created_at": other.created_at,
                "message": other.message,
            }
            for other in session.scalars(
                select(models.BugReport)
                .where(
                    models.BugReport.opportunity_id == opportunity.id,
                    models.BugReport.id != report.id,
                )
                .order_by(models.BugReport.created_at)
            )
        ]
    return result


def triage_report(
    session: Session,
    reference: str,
    *,
    note: str | None = None,
    now: datetime | None = None,
) -> bool:
    report = get_report(session, reference, lock=True)
    if report.status == "resolved":
        raise ValueError("A resolved report cannot be triaged again")
    if report.status == "triaged":
        return False
    report.triaged_at = now or utcnow()
    report.status = "triaged"
    if note:
        report.resolution_note = note.strip()
    session.flush()
    return True


def deadline_at_end_of_day(value: str) -> datetime:
    day = date.fromisoformat(value)
    if day.isoformat() != value:
        raise ValueError("--set-deadline must be YYYY-MM-DD")
    return datetime.combine(day, time(23, 59, 59), INDIA_TIME).astimezone(timezone.utc)


def _json_value(value):
    return value.isoformat() if isinstance(value, datetime) else value


def resolve_report(
    session: Session,
    reference: str,
    *,
    resolution: str,
    note: str,
    close_listing: bool = False,
    set_deadline: str | None = None,
    withdraw: bool = False,
    kind: str | None = None,
    duplicate_of: str | None = None,
    company: str | None = None,
    now: datetime | None = None,
) -> tuple[models.BugReport, str | None, bool]:
    if resolution not in RESOLUTIONS or not note.strip():
        raise ValueError("A valid resolution and a non-blank public note are required")
    if (
        sum(
            (
                close_listing,
                set_deadline is not None,
                withdraw,
                duplicate_of is not None,
                company is not None,
            )
        )
        > 1
    ):
        raise ValueError("Choose at most one listing action")
    if withdraw != (kind is not None) or (kind is not None and kind not in {"scam", "recalled"}):
        raise ValueError("--withdraw requires --kind scam|recalled")
    # Match deletion's lock order: user first, then owned report. A deletion that
    # wins removes the report; it must never be recreated or emailed afterwards.
    snapshot = get_report(session, reference)
    user = (
        lock_recipient(session, snapshot.user_id, skip_locked=False) if snapshot.user_id else None
    )
    report = get_report(session, reference, lock=True)
    opportunity = (
        session.scalar(
            select(models.Opportunity)
            .where(models.Opportunity.id == report.opportunity_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if report.opportunity_id
        else None
    )
    slug = opportunity.slug if opportunity else None
    if report.status == "resolved":
        if report.resolution != resolution or report.resolution_note != note.strip():
            raise ValueError("Report is already resolved; its published outcome is immutable")
        return report, slug, False
    action = close_listing or set_deadline is not None or withdraw or duplicate_of or company
    if action and opportunity is None:
        raise ValueError("This report has no listing")
    current = now or utcnow()
    diffs = []

    def record(field, old, new):
        diffs.append(
            {
                "at": current.isoformat(),
                "field": field,
                "old": _json_value(old),
                "new": _json_value(new),
                "report": report.reference,
            }
        )

    meta = dict(opportunity.meta or {}) if opportunity else {}
    if close_listing:
        old = opportunity.closed_at
        opportunity.closed_at = current
        meta["closed_reason"] = "user_report"
        record("closed_at", old, opportunity.closed_at)
    elif set_deadline is not None:
        deadline = deadline_at_end_of_day(set_deadline)
        record("deadline", opportunity.deadline, deadline)
        opportunity.deadline = deadline
        opportunity.deadline_confidence = "explicit"
        meta["deadline_override"] = {
            "value": deadline.isoformat(),
            "report": report.reference,
            "at": current.isoformat(),
        }
    elif withdraw:
        old = meta.get("safety")
        flag_listing(session, slug=slug, kind=kind, note=note.strip(), now=current)
        meta = dict(opportunity.meta or {})
        record("safety", old, meta.get("safety"))
    elif duplicate_of:
        original = session.scalar(
            select(models.Opportunity).where(models.Opportunity.slug == duplicate_of)
        )
        if original is None or original.id == opportunity.id:
            raise ValueError("The original listing must exist and differ from this listing")
        old = opportunity.closed_at
        opportunity.closed_at = current
        record("closed_at", old, opportunity.closed_at)
        record("duplicate_of", meta.get("duplicate_of"), original.slug)
        meta.update(closed_reason="duplicate", duplicate_of=original.slug)
    elif company:
        target = session.scalar(select(models.Company).where(models.Company.slug == company))
        if target is None:
            raise ValueError(f"Company not found: {company}")
        old_company = opportunity.company.slug if opportunity.company else None
        record("company_id", opportunity.company_id, target.id)
        opportunity.company_id = target.id
        meta["company_override"] = {
            "from": old_company,
            "to": target.slug,
            "report": report.reference,
            "at": current.isoformat(),
        }
    if diffs:
        history = meta.get("corrections")
        meta["corrections"] = [*(history if isinstance(history, list) else []), *diffs]
        opportunity.meta = meta
    report.triaged_at = report.triaged_at or current
    report.resolved_at = current
    report.resolution = resolution
    report.resolution_note = note.strip()
    report.correction = diffs
    report.status = "resolved"
    if user:
        session.add(
            models.Notification(
                user_id=user.id,
                type="report_resolved",
                opportunity_id=report.opportunity_id,
                channel="in_app",
                status="sent",
                sent_at=current,
                meta={
                    "reference": report.reference,
                    "resolution": resolution,
                    "note": note.strip(),
                    "slug": slug,
                },
            )
        )
    session.flush()
    return report, slug, True


def send_resolution_email(session: Session, reference: str) -> bool:
    """Called once after a newly resolved report commits; never email on intake/triage."""
    report = session.scalar(
        select(models.BugReport).where(models.BugReport.reference == reference.upper())
    )
    if report is None or not report.contact_email or report.status != "resolved":
        return False
    if report.user_id and lock_recipient(session, report.user_id, skip_locked=False) is None:
        return False
    # Re-read after the user lock in case deletion committed between these reads.
    report = session.scalar(
        select(models.BugReport)
        .where(models.BugReport.reference == reference)
        .execution_options(populate_existing=True)
    )
    if report is None or not report.contact_email:
        return False
    url = f"{get_settings().site_url.rstrip('/')}/report/status?ref={report.reference}"
    lines = [f"{report.reference}: {report.resolution_note}"]
    try:
        return send_email(
            to=report.contact_email,
            subject="Your Aspirova report was resolved",
            html=email_layout(
                title="Your report was resolved",
                body_html=status_panel("success", lines),
                cta_label="View report status",
                cta_url=url,
                variant="transactional",
                receiving_note="You're receiving this because you requested an update on your report.",
                show_preferences=False,
            ),
            text=f"Your report was resolved\n\n{lines[0]}\n\nView report status: {url}",
        )
    except Exception:
        logger.warning("Resolution email failed for %s", reference, exc_info=True)
        return False


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lo, hi = math.floor(position), math.ceil(position)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (position - lo)


def report_stats(session: Session, *, days: int = 30, now: datetime | None = None) -> dict:
    if days < 1:
        raise ValueError("days must be positive")
    current = now or utcnow()
    reports = list(
        session.scalars(
            select(models.BugReport).where(
                models.BugReport.created_at >= current - timedelta(days=days),
                models.BugReport.created_at <= current,
            )
        )
    )
    result = {"days": days, "total": len(reports)}
    for field in ("status", "category", "resolution"):
        result[f"by_{field}"] = dict(
            Counter(getattr(r, field) for r in reports if getattr(r, field))
        )
    for field, target in (("triaged_at", 48), ("resolved_at", 7 * 24)):
        elapsed = [
            (getattr(r, field) - r.created_at).total_seconds() / 3600
            for r in reports
            if getattr(r, field) is not None
        ]
        eligible = sum(
            getattr(r, field) is not None or current - r.created_at > timedelta(hours=target)
            for r in reports
        )
        result[field] = {
            "median_hours": median(elapsed) if elapsed else None,
            "p90_hours": _percentile(elapsed, 0.9),
            "measured": len(elapsed),
            "sla_eligible": eligible,
            "within_sla_percent": (
                100 * sum(v <= target for v in elapsed) / eligible if eligible else None
            ),
        }
    # The operational backlog is all ages, even outside the reporting cohort.
    pending = session.scalars(select(models.BugReport).where(models.BugReport.status != "resolved"))
    result["open_overdue"] = sum(overdue(r, current) for r in pending)
    return result


def remind(session: Session, *, now: datetime | None = None) -> bool:
    current = now or utcnow()
    reports = [
        r
        for r in session.scalars(
            select(models.BugReport)
            .where(models.BugReport.status.in_(("open", "triaged")))
            .order_by(models.BugReport.created_at)
        )
        if overdue(r, current)
    ]
    if not reports:
        return False
    if not get_settings().waitlist_notify_email:
        # Actions logs are public: a count only, never report details.
        logger.warning(
            "%d overdue reports, but WAITLIST_NOTIFY_EMAIL is not set; no reminder sent",
            len(reports),
        )
        return False
    text = "Overdue Aspirova reports\n\n" + "\n".join(
        f"{r.reference} | {r.status} | {r.category} | "
        f"{(current - r.created_at).total_seconds() / 3600:.1f}h | "
        f"uv run python -m scripts.reports show {r.reference}"
        for r in reports
    )
    return send_email(
        to=get_settings().waitlist_notify_email,
        subject=f"Aspirova: {len(reports)} overdue reports",
        html=f"<pre>{escape(text)}</pre>",
        text=text,
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    queue = commands.add_parser("list")
    queue.add_argument("--status", choices=("open", "triaged", "resolved", "all"), default="open")
    queue.add_argument("--category", choices=CATEGORIES)
    queue.add_argument("--limit", type=int, default=50)
    show = commands.add_parser("show")
    show.add_argument("reference")
    triage = commands.add_parser("triage")
    triage.add_argument("reference")
    triage.add_argument("--note")
    triage.add_argument("--dry-run", action="store_true")
    resolve = commands.add_parser("resolve")
    resolve.add_argument("reference")
    resolve.add_argument("--resolution", choices=RESOLUTIONS, required=True)
    resolve.add_argument("--note", required=True, help="Public-safe note; no reporter details")
    actions = resolve.add_mutually_exclusive_group()
    actions.add_argument("--close-listing", action="store_true")
    actions.add_argument("--set-deadline")
    actions.add_argument("--withdraw", action="store_true")
    actions.add_argument("--duplicate-of")
    actions.add_argument("--company")
    resolve.add_argument("--kind", choices=("scam", "recalled"))
    resolve.add_argument("--dry-run", action="store_true")
    stats = commands.add_parser("stats")
    stats.add_argument("--days", type=int, default=30)
    commands.add_parser("remind")
    args = parser.parse_args(argv)
    engine = make_engine()
    try:
        with Session(engine) as session:
            try:
                if args.command == "list":
                    result = list_reports(
                        session, status=args.status, category=args.category, limit=args.limit
                    )
                elif args.command == "show":
                    result = show_report(session, args.reference)
                elif args.command == "stats":
                    result = report_stats(session, days=args.days)
                elif args.command == "remind":
                    result = {"sent": remind(session)}
                else:
                    slug, changed = None, False
                    if args.command == "triage":
                        changed = triage_report(session, args.reference, note=args.note)
                    else:
                        report, slug, changed = resolve_report(
                            session,
                            args.reference,
                            resolution=args.resolution,
                            note=args.note,
                            close_listing=args.close_listing,
                            set_deadline=args.set_deadline,
                            withdraw=args.withdraw,
                            kind=args.kind,
                            duplicate_of=args.duplicate_of,
                            company=args.company,
                        )
                    result = {
                        "reference": args.reference,
                        "changed": changed,
                        "dry_run": args.dry_run,
                    }
                    if args.dry_run:
                        session.rollback()
                    else:
                        session.commit()
                        if slug and any(
                            (
                                args.close_listing,
                                args.set_deadline,
                                args.withdraw,
                                args.duplicate_of,
                                args.company,
                            )
                        ):
                            result["api_refresh"] = refresh_api_details([slug])
                            result["revalidation"] = notify_changed([slug], landing=False)
                            if result["revalidation"]["status"] == "unconfigured":
                                print(LOCAL_REVALIDATION_WARNING)
                        if args.command == "resolve" and changed:
                            result["resolution_email_sent"] = send_resolution_email(
                                session, args.reference.upper()
                            )
                            session.commit()  # release the recipient lock only after delivery
                print(json.dumps(result, default=str, indent=2))
            except ValueError as exc:
                session.rollback()
                parser.error(str(exc))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
