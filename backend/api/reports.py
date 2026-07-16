"""POST /reports - durable, signed-out-friendly issue reporting."""

from html import escape
import logging
import re

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.auth import get_current_user
from api.deps import get_db
from api.middleware import client_ip
from api.schemas import BugReportRequest, BugReportResponse
from core import models
from core.config import get_settings
from core.email_client import send_email
from core.ratelimit import check_rate_limit
from core.redis_client import get_redis

router = APIRouter()
logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_VALID_CATEGORIES = {"dead_link", "wrong_info", "bug", "other"}


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
    opportunity_slug: str | None,
) -> None:
    """Best-effort only: persistence is already committed before this runs."""
    settings = get_settings()
    if not settings.waitlist_notify_email:
        logger.warning("Bug report %s recorded but founder notification is unconfigured", report.id)
        return

    opportunity = opportunity_slug or "None"
    page_url = report.page_url or "None"
    contact_email = report.contact_email or "None"
    text_body = (
        f"Category: {report.category}\n"
        f"Message:\n{report.message}\n\n"
        f"Opportunity slug: {opportunity}\n"
        f"Page URL: {page_url}\n"
        f"Contact email: {contact_email}\n"
    )
    html_body = (
        f"<p><strong>Category:</strong> {escape(report.category)}</p>"
        f"<p><strong>Message:</strong></p><pre>{escape(report.message)}</pre>"
        f"<p><strong>Opportunity slug:</strong> {escape(opportunity)}</p>"
        f"<p><strong>Page URL:</strong> {escape(page_url)}</p>"
        f"<p><strong>Contact email:</strong> {escape(contact_email)}</p>"
    )
    try:
        sent = send_email(
            to=settings.waitlist_notify_email,
            subject=f"Aspirova bug report: {report.category}",
            html=html_body,
            text=text_body,
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

    opportunity_id = None
    if opportunity_slug:
        opportunity_id = db.scalar(
            select(models.Opportunity.id).where(models.Opportunity.slug == opportunity_slug)
        )

    report = models.BugReport(
        user_id=user.id if user is not None else None,
        opportunity_id=opportunity_id,
        category=category,
        message=message,
        page_url=page_url,
        contact_email=contact_email,
    )
    db.add(report)
    db.commit()

    _notify_founder(report, opportunity_slug=opportunity_slug)
    return BugReportResponse()
