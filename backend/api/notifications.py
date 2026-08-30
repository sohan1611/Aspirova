"""Authenticated in-app notification center endpoints."""

import uuid
from html import escape
from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import HTMLResponse
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from api.auth import get_current_user
from api.deps import get_db
from api.schemas import NotificationItem, NotificationsResponse
from core import models
from core.unsubscribe import verify_token

router = APIRouter()


def _notification_copy(
    notification_type: str,
    opportunity_title: str | None,
    company_name: str | None,
) -> tuple[str, str]:
    """Return client-ready copy so notification rendering stays server-side."""
    if notification_type == "closing_soon":
        title = opportunity_title or "An opportunity"
        return "Closing soon", f"‘{title}’ closes soon — don’t miss it."
    if notification_type == "instant_alert":
        title = opportunity_title or "An opportunity"
        company = company_name or "a dream company"
        return "New at a dream company", f"‘{title}’ just opened at {company}."
    # `digest` is the legacy type currently emitted by the notification
    # worker. Keep it readable alongside the specified `daily_digest` type.
    if notification_type in {"daily_digest", "digest"}:
        return "Your daily digest", "New opportunities matched your interests today."
    if notification_type == "weekly_report":
        return "Your weekly career report", "Your week in opportunities is ready."
    return notification_type.replace("_", " ").title(), ""


def _delivered_notification_filter():
    return or_(
        models.Notification.status == "sent",
        models.Notification.sent_at.is_not(None),
    )


@router.get("/notifications", response_model=NotificationsResponse)
def list_notifications(
    limit: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> NotificationsResponse:
    delivered = _delivered_notification_filter()
    # A distinct label: the joined opportunities/companies rows also expose a
    # `created_at`, so an unqualified `created_at` in ORDER BY is ambiguous.
    created_at = func.coalesce(models.Notification.sent_at, func.now()).label(
        "notification_created_at"
    )
    rows = db.execute(
        select(models.Notification, models.Opportunity, models.Company, created_at)
        .select_from(models.Notification)
        .outerjoin(
            models.Opportunity,
            models.Notification.opportunity_id == models.Opportunity.id,
        )
        .outerjoin(models.Company, models.Opportunity.company_id == models.Company.id)
        .where(models.Notification.user_id == user.id, delivered)
        .order_by(created_at.desc(), models.Notification.id.desc())
        .limit(limit)
    ).all()
    unread = db.scalar(
        select(func.count(models.Notification.id)).where(
            models.Notification.user_id == user.id,
            delivered,
            models.Notification.read_at.is_(None),
        )
    )

    items = []
    for notification, opportunity, company, notification_created_at in rows:
        opportunity_title = opportunity.title if opportunity else None
        company_name = company.name if company else None
        title, body = _notification_copy(notification.type, opportunity_title, company_name)
        items.append(
            NotificationItem(
                id=notification.id,
                type=notification.type,
                title=title,
                body=body,
                opportunity_slug=opportunity.slug if opportunity else None,
                opportunity_title=opportunity_title,
                company_name=company_name,
                created_at=notification_created_at,
                read=notification.read_at is not None,
            )
        )

    return NotificationsResponse(items=items, unread=unread or 0)


@router.get("/notifications/unread-count", response_model=dict[str, int])
def get_unread_count(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> dict[str, int]:
    unread = db.scalar(
        select(func.count(models.Notification.id)).where(
            models.Notification.user_id == user.id,
            _delivered_notification_filter(),
            models.Notification.read_at.is_(None),
        )
    )
    return {"unread": unread or 0}


@router.post("/notifications/read", response_model=dict[str, int])
def mark_notifications_read(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> dict[str, int]:
    db.execute(
        update(models.Notification)
        .where(
            models.Notification.user_id == user.id,
            models.Notification.read_at.is_(None),
        )
        .values(read_at=func.now())
    )
    db.commit()
    return {"unread": 0}


_UNSUB_DONE = "You have been unsubscribed."
_UNSUB_DETAIL = "You can re-enable this any time in your Aspirova account settings."
_UNSUB_CONFIRM = "Stop receiving these emails?"


def _unsub_page(heading: str, detail: str, confirm_token: str | None = None) -> Response:
    """Minimal self-contained HTML. No external assets - this is read by people
    who have just left, on unknown clients, and must render everywhere."""
    button = ""
    if confirm_token is not None:
        # Token stays in the query string, not a form field: Gmail's one-click
        # POST puts it there, so the endpoint reads it from there, and this form
        # must post the same shape.
        action = escape(f"/notifications/unsubscribe?token={quote_plus(confirm_token)}", quote=True)
        button = (
            f'<form method="post" action="{action}" style="margin:22px 0 0">'
            '<button type="submit" style="background:#5e2b47;border:0;border-radius:8px;'
            "color:#fff;cursor:pointer;font-family:Arial,Helvetica,sans-serif;font-size:15px;"
            'font-weight:700;padding:12px 22px">Yes, unsubscribe</button>'
            "</form>"
        )
    return HTMLResponse(
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>Aspirova</title></head>"
        '<body style="background:#faf7f0;margin:0;padding:48px 16px">'
        '<div style="background:#fff;border:1px solid #e7e0d4;border-radius:12px;'
        'margin:0 auto;max-width:520px;padding:32px 28px">'
        "<p style=\"color:#5e2b47;font-family:Georgia,'Times New Roman',serif;font-size:22px;"
        'font-weight:700;margin:0 0 18px">Aspirova</p>'
        "<p style=\"color:#2b2620;font-family:Georgia,'Times New Roman',serif;font-size:20px;"
        f'line-height:28px;margin:0 0 10px">{escape(heading)}</p>'
        '<p style="color:#6b6259;font-family:Arial,Helvetica,sans-serif;font-size:14px;'
        f'line-height:21px;margin:0">{escape(detail)}</p>'
        f"{button}"
        "</div></body></html>"
    )


def _apply_unsubscribe(token: str, db: Session) -> None:
    """Turn off exactly the one preference the token names. Silent on every
    failure path: an anonymous caller must not learn whether a user exists."""
    verified = verify_token(token)
    if verified is None:
        return

    user_id, preference_key = verified
    try:
        user = db.get(models.User, uuid.UUID(user_id))
    except (ValueError, AttributeError, TypeError):
        return
    if user is None:
        return

    # Merge rather than replace: this turns off exactly the one list the reader
    # clicked from, and leaves every other preference untouched.
    user.notification_prefs = {**(user.notification_prefs or {}), preference_key: False}
    db.commit()


@router.post("/notifications/unsubscribe")
def unsubscribe_post(token: str = Query(...), db: Session = Depends(get_db)) -> Response:
    """One-click unsubscribe. Deliberately unauthenticated.

    Gmail POSTs here itself, on the reader's behalf, with no session and no
    chance to confirm - that is what List-Unsubscribe-Post means. The token is
    the authorisation: it is signed, names exactly one user and one preference,
    and can do nothing else.

    Always answers 200. A bad or expired token must not tell an anonymous caller
    whether a user exists, and Gmail treats a non-2xx as a broken unsubscribe.
    """
    _apply_unsubscribe(token, db)
    return _unsub_page(_UNSUB_DONE, _UNSUB_DETAIL)


@router.get("/notifications/unsubscribe")
def unsubscribe_get(token: str = Query(...), db: Session = Depends(get_db)) -> Response:
    """GET only ASKS. It must never change anything.

    This is the difference between the header and the visible footer link.
    List-Unsubscribe is fetched by machines: Gmail POSTs it, but security
    scanners, link previewers and corporate mail gateways issue GETs on every
    URL they find in a message - including this one, without a human involved.
    While GET unsubscribed, any such prefetch silently opted a reader out of
    mail they never asked to stop.

    So GET renders a confirmation with a button that POSTs. RFC 8058 one-click
    is unaffected because it is defined as a POST, and a human who pastes the
    link still gets somewhere sensible.
    """
    return _unsub_page(_UNSUB_CONFIRM, _UNSUB_DETAIL, confirm_token=token)
