"""POST /waitlist - the honest Razorpay dummy for the pricing page (Doc
handoffs/PHASE-2.5-HANDOFF.md sec 3.7): no checkout, just a founder
notification via the existing Resend seam (core/email_client.py). No new
schema/table - the simplest honest mechanism the handoff calls for.

Rate-limited per-IP as a route dependency (not the ASGI middleware, which
only covers GET - Doc handoffs/PHASE-2-HANDOFF.md sec 11.3), the same
pattern api/bookmarks.py uses for its per-user write limit."""

import re
from html import escape

from fastapi import APIRouter, Depends, HTTPException, Request

from api.middleware import client_ip
from api.schemas import WaitlistSignupRequest, WaitlistSignupResponse
from core.config import get_settings
from core.email_client import send_email
from core.ratelimit import check_rate_limit
from core.redis_client import get_redis

router = APIRouter()

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


async def enforce_waitlist_rate_limit(request: Request) -> None:
    settings = get_settings()
    result = await check_rate_limit(
        get_redis(),
        bucket="waitlist",
        identifier=client_ip(request),
        max_requests=settings.rate_limit_ip_waitlist_per_minute,
        window_seconds=60,
    )
    if not result.allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many requests",
            headers={"Retry-After": str(result.retry_after_seconds)},
        )


@router.post(
    "/waitlist",
    response_model=WaitlistSignupResponse,
    dependencies=[Depends(enforce_waitlist_rate_limit)],
)
def join_waitlist(body: WaitlistSignupRequest) -> WaitlistSignupResponse:
    if not _EMAIL_RE.match(body.email):
        raise HTTPException(status_code=422, detail="Invalid email address")

    settings = get_settings()
    if settings.waitlist_notify_email:
        send_email(
            to=settings.waitlist_notify_email,
            subject="Aspirova pricing waitlist signup",
            html=f"<p>New waitlist signup: {escape(body.email, quote=True)}</p>",
            text=f"New waitlist signup: {body.email}",
        )
    # Always ok=True regardless of email delivery - a public marketing
    # page should never surface an internal notification failure to the
    # visitor (same fail-open spirit as core/email_client.py itself).
    return WaitlistSignupResponse()
