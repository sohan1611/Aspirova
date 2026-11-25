"""POST /reports - durable, signed-out-friendly issue reporting."""

from html import escape
import logging
import re

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.auth import get_current_user
from api.deps import get_db
from api.middleware import client_ip
from api.schemas import BugReportRequest, BugReportResponse, ReportStatusResponse
from core import models
from core.config import get_settings
from core.email_client import send_email
from core.ratelimit import check_rate_limit
from core.redis_client import get_redis
from core.report_receipts import REFERENCE_PATTERN, store_report

router = APIRouter()
logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_VALID_CATEGORIES = {
    "dead_link",
    "wrong_info",
    "bug",
    "other",
    "scam",
    "wrong_deadline",
    "wrong_company",
    "duplicate",
}


async def enforce_report_rate_limit(request: Request) -> None:
    settings = get_settings()
    result = await check_rate_limit(
        get_redis(),
        bucket="bug_report",
        identifier=client_ip(request),
        max_requests=settings.rate_limit_ip_report_per_minute,
        window_seconds=60,
    )
    if not result.allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many requests",
            headers={"Retry-After": str(result.retry_after_seconds)},
        )


def get_optional_current_user(
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
) -> models.User | None:
    """Resolve a valid bearer token when present, never blocking a report on auth."""
    if not authorization:
        return None

    try:
        return get_current_user(authorization=authorization, db=db)
    except Exception:
        # get_current_user may have opened a transaction before failing (for
        # example, while mirroring a newly authenticated user). Clear it so
        # the independently valuable report can still be committed.
        try:
            db.rollback()
        except Exception:
            logger.warning("Optional report authentication rollback failed", exc_info=True)
        logger.warning("Optional report authentication failed; storing report anonymously")
        return None


def _validated_fields(
    body: BugReportRequest,
) -> tuple[str, str, str | None, str | None, str | None]:
    category = body.category.strip()
    if category not in _VALID_CATEGORIES:
        raise HTTPException(status_code=422, detail="Invalid report category")

    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=422, detail="Report message must not be blank")
    if len(message) > 2_000:
        raise HTTPException(
            status_code=422,
            detail="Report message must be at most 2000 characters",
        )

    opportunity_slug = body.opportunity_slug.strip() if body.opportunity_slug else None
    page_url = body.page_url.strip() if body.page_url else None
    contact_email = body.contact_email.strip() if body.contact_email else None
    if contact_email and not _EMAIL_RE.fullmatch(contact_email):
        raise HTTPException(status_code=422, detail="Invalid email address")

    return category, message, opportunity_slug, page_url, contact_email


def _notify_founder(
    report: models.BugReport,
    *,
    opportunity: models.Opportunity | None,
    open_reports: int,
) -> None:
    """Best-effort only: persistence is already committed before this runs."""
    settings = get_settings()
    if not settings.waitlist_notify_email:
        logger.warning("Bug report %s recorded but founder notification is unconfigured", report.id)
        return

    slug = opportunity.slug if opportunity else "None"
    title = opportunity.title if opportunity else "None"
    command = f"uv run python -m scripts.reports show {report.reference}"
    page_url = report.page_url or "None"
    contact_email = report.contact_email or "None"
    text_body = (
        f"Reference: {report.reference}\n"
        f"Category: {report.category}\n"
        f"Message:\n{report.message}\n\n"
        f"Listing: {title}\nOpportunity slug: {slug}\n"
        f"Open reports for listing: {open_reports}\n"
        f"Triage: {command}\n"
        f"Page URL: {page_url}\n"
        f"Contact email: {contact_email}\n"
    )
    html_body = (
        f"<p><strong>Reference:</strong> {escape(report.reference)}</p>"
        f"<p><strong>Category:</strong> {escape(report.category)}</p>"
        f"<p><strong>Message:</strong></p><pre>{escape(report.message)}</pre>"
        f"<p><strong>Listing:</strong> {escape(title)} ({escape(slug)})</p>"
        f"<p>Open reports for listing: {open_reports}</p><pre>{escape(command)}</pre>"
        f"<p><strong>Page URL:</strong> {escape(page_url)}</p>"
        f"<p><strong>Contact email:</strong> {escape(contact_email)}</p>"
    )
    try:
        sent = send_email(
            to=settings.waitlist_notify_email,
            subject=(
                "Aspirova report: possible scam"
                if report.category == "scam"
                else f"Aspirova bug report: {report.category}"
            ),
            html=html_body,
            text=text_body,
            kind="report_intake",
            identity=report.reference,
            user_id=report.user_id,
        )
        if not sent:
            logger.warning(
                "Bug report %s was saved but founder notification was not sent",
                report.id,
            )
    except Exception:
        logger.warning(
            "Bug report %s was saved but founder notification raised an error",
            report.id,
            exc_info=True,
        )


@router.post(
    "/reports",
    response_model=BugReportResponse,
    dependencies=[Depends(enforce_report_rate_limit)],
)
def create_bug_report(
    body: BugReportRequest,
    db: Session = Depends(get_db),
    user: models.User | None = Depends(get_optional_current_user),
) -> BugReportResponse:
    category, message, opportunity_slug, page_url, contact_email = _validated_fields(body)

    opportunity = None
    if opportunity_slug:
        opportunity = db.scalar(
            select(models.Opportunity).where(models.Opportunity.slug == opportunity_slug)
        )
    report = store_report(
        db,
        user_id=user.id if user is not None else None,
        opportunity_id=opportunity.id if opportunity else None,
        category=category,
        message=message,
        page_url=page_url,
        contact_email=contact_email,
    )
    db.commit()
    open_reports = (
        db.scalar(
            select(func.count(models.BugReport.id)).where(
                models.BugReport.opportunity_id == opportunity.id,
                models.BugReport.status.in_(("open", "triaged")),
            )
        )
        if opportunity
        else 0
    )
    _notify_founder(report, opportunity=opportunity, open_reports=open_reports or 0)
    return BugReportResponse(reference=report.reference)


@router.get(
    "/reports/status/{reference}",
    response_model=ReportStatusResponse,
    dependencies=[Depends(enforce_report_rate_limit)],
)
def report_status(reference: str, db: Session = Depends(get_db)) -> ReportStatusResponse:
    reference = reference.strip().upper()
    if not re.fullmatch(REFERENCE_PATTERN, reference):
        raise HTTPException(status_code=404, detail="Report not found")
    row = db.execute(
        select(models.BugReport, models.Opportunity.slug, models.Opportunity.title)
        .outerjoin(models.Opportunity, models.Opportunity.id == models.BugReport.opportunity_id)
        .where(models.BugReport.reference == reference)
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Report not found")
    report, slug, title = row
    # Explicit allowlist: never serialize the ORM report or its free-text message.
    return ReportStatusResponse(
        reference=report.reference,
        category=report.category,
        status=report.status,
        created_at=report.created_at,
        triaged_at=report.triaged_at,
        resolved_at=report.resolved_at,
        resolution=report.resolution,
        resolution_note=report.resolution_note,
        listing_slug=slug,
        listing_title=title,
    )
