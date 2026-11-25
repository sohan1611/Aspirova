"""Founder delivery health (no recipient data) and signed Resend webhooks."""

import hmac
import json
from datetime import timedelta

import resend
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.deps import get_db
from core import models
from core.config import get_settings
from core.email_budget import sent_today
from core.email_events import apply_event
from core.email_outbox import utcnow

router = APIRouter()


def require_admin(authorization: str | None = Header(None)) -> None:
    token = get_settings().delivery_admin_token
    if not token:
        raise HTTPException(503, "Delivery admin is not configured")
    if not hmac.compare_digest(authorization or "", "Bearer " + token):
        raise HTTPException(401, "Admin authorization required")


@router.get("/admin/delivery", dependencies=[Depends(require_admin)])
def delivery_health(response: Response, db: Session = Depends(get_db)) -> dict:
    response.headers["Cache-Control"] = "no-store"
    now = utcnow()
    counts = [
        {"status": status, "kind": kind, "count": count}
        for status, kind, count in db.execute(
            select(models.EmailOutbox.status, models.EmailOutbox.kind, func.count())
            .where(models.EmailOutbox.created_at >= now - timedelta(days=7))
            .group_by(models.EmailOutbox.status, models.EmailOutbox.kind)
            .order_by(models.EmailOutbox.kind, models.EmailOutbox.status)
        )
    ]
    errors = [
        {"kind": kind, "code": code, "message": message, "time": at.isoformat()}
        for kind, code, message, at in db.execute(
            select(
                models.EmailOutbox.kind,
                models.EmailOutbox.last_code,
                models.EmailOutbox.last_error,
                models.EmailOutbox.updated_at,
            )
            .where(
                models.EmailOutbox.last_error.is_not(None),
                models.EmailOutbox.updated_at >= now - timedelta(days=7),
            )
            .order_by(models.EmailOutbox.updated_at.desc())
            .limit(30)
        )
    ]
    delivery = dict(
        db.execute(
            select(models.EmailOutbox.delivery_status, func.count())
            .where(
                models.EmailOutbox.created_at >= now - timedelta(days=7),
                models.EmailOutbox.delivery_status.is_not(None),
            )
            .group_by(models.EmailOutbox.delivery_status)
        ).all()
    )
    settings = get_settings()
    return {
        "counts": counts,
        "errors": errors,
        "delivery": delivery,
        "suppression_count": db.scalar(select(func.count()).select_from(models.EmailSuppression)),
        "budget_used_today": sent_today(db, now),
        "budget": settings.email_daily_budget,
        "digest_reserve": settings.email_digest_reserve,
    }


@router.post("/email/webhook")
async def resend_webhook(request: Request, db: Session = Depends(get_db)) -> dict:
    secret = get_settings().resend_webhook_secret
    if not secret:
        raise HTTPException(503, "Resend webhook secret is not configured")
    raw = await request.body()
    if len(raw) > 131072:
        raise HTTPException(413, "Webhook too large")
    try:
        body = raw.decode("utf-8")
        resend.Webhooks.verify(
            {
                "payload": body,
                "headers": {
                    "id": request.headers.get("svix-id", ""),
                    "timestamp": request.headers.get("svix-timestamp", ""),
                    "signature": request.headers.get("svix-signature", ""),
                },
                "webhook_secret": secret,
            }
        )
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise ValueError("Invalid event")
    except (ValueError, UnicodeError):
        raise HTTPException(400, "Invalid webhook signature or payload") from None
    try:
        apply_event(db, request.headers["svix-id"], payload)
        db.commit()
    except (ValueError, TypeError, AttributeError):
        db.rollback()
        raise HTTPException(400, "Invalid webhook event") from None
    return {"ok": True}


# There is no existing admin UI/auth role. A plain same-origin page asks for
# the server-configured token in memory; no URL parameter, cookie or storage.
@router.get("/admin/delivery/view", response_class=HTMLResponse, include_in_schema=False)
def delivery_page() -> HTMLResponse:
    return HTMLResponse(
        """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width"><title>Email delivery health</title>
<style>body{font:16px system-ui;max-width:960px;margin:3rem auto;padding:1rem}
table{border-collapse:collapse;width:100%;margin:1rem 0}td,th{text-align:left;padding:.5rem;
border-bottom:1px solid #ddd}input,button{font:inherit;padding:.5rem}pre{white-space:pre-wrap}</style>
<h1>Email delivery health</h1><p>Last 7 days. Counts and safe provider errors only.</p>
<form id="login"><label>Admin token <input id="token" type="password" autocomplete="off" required></label>
<button>Load / refresh</button></form><p id="summary" role="status"></p>
<h2>Status by kind</h2><table><thead><tr><th>Kind</th><th>Status</th><th>Count</th></tr></thead>
<tbody id="counts"></tbody></table><h2>Latest errors</h2>
<table><thead><tr><th>Kind</th><th>Vendor code</th><th>Message</th><th>Time</th></tr></thead>
<tbody id="errors"></tbody></table><pre id="delivery"></pre>
<script>
function rows(id,values){const body=document.getElementById(id);body.replaceChildren();
for(const valuesRow of values){const tr=document.createElement('tr');
for(const value of valuesRow){const td=document.createElement('td');td.textContent=value??'';
tr.append(td)}body.append(tr)}}
document.getElementById('login').addEventListener('submit',async event=>{event.preventDefault();
const status=document.getElementById('summary');
try{const response=await fetch('/admin/delivery',{cache:'no-store',headers:{
Authorization:'Bearer '+document.getElementById('token').value}});
if(!response.ok)throw new Error('Request failed ('+response.status+')');const data=await response.json();
status.textContent='Budget today: '+data.budget_used_today+' / '+data.budget+
'; digest reserve: '+data.digest_reserve+'; suppressed addresses: '+data.suppression_count;
rows('counts',data.counts.map(r=>[r.kind,r.status,r.count]));
rows('errors',data.errors.map(r=>[r.kind,r.code,r.message,r.time]));
document.getElementById('delivery').textContent='Provider events: '+JSON.stringify(data.delivery);
}catch(error){status.textContent=error.message;rows('counts',[]);rows('errors',[])}});
</script></html>""",
        headers={
            "Cache-Control": "no-store",
            "X-Robots-Tag": "noindex",
            "Referrer-Policy": "no-referrer",
        },
    )
