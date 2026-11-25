"""Handle VERIFIED Resend receipts. Signature verification lives at the API boundary."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from core import models
from core.email_outbox import _accepted, _address_lock, _receipt_status, utcnow

DELIVERY_PRIORITY = {
    "sent": 0,
    "delivered": 1,
    "failed": 2,
    "suppressed": 2,
    "bounced": 3,
    "complained": 4,
}


def apply_event(
    session: Session, event_id: str, payload: dict, *, now: datetime | None = None
) -> bool:
    now = now or utcnow()
    event = payload.get("type", "").removeprefix("email.")
    if event not in DELIVERY_PRIORITY:
        return False
    data = payload.get("data", {})
    provider_id = data.get("email_id")
    if not isinstance(provider_id, str) or not provider_id:
        raise ValueError("Missing provider message id")
    recipients = data.get("to", [])
    if not isinstance(recipients, list) or any(not isinstance(a, str) for a in recipients):
        raise ValueError("Invalid recipient list")
    tags = data.get("tags") or {}
    if isinstance(tags, list):
        tags = {t.get("name"): t.get("value") for t in tags if isinstance(t, dict)}
    tag_key = tags.get("outbox_key") if isinstance(tags, dict) else None
    row = session.scalar(
        select(models.EmailOutbox).where(models.EmailOutbox.provider_id == provider_id)
    )
    if row is None and isinstance(tag_key, str):
        row = session.scalar(
            select(models.EmailOutbox).where(models.EmailOutbox.dedupe_key == "email/" + tag_key)
        )
    addresses = sorted(
        {a.strip().lower() for a in recipients} | ({row.recipient} if row else set())
    )
    for address in addresses:
        _address_lock(session, address)
    inserted = session.scalar(
        insert(models.EmailWebhookEvent)
        .values(event_id=event_id, provider_id=provider_id, event_type=event, created_at=now)
        .on_conflict_do_nothing(index_elements=["event_id"])
        .returning(models.EmailWebhookEvent.event_id)
    )
    if inserted is None:
        return False
    if row is not None:
        row = session.scalar(
            select(models.EmailOutbox)
            .where(models.EmailOutbox.id == row.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        _accepted(session, row, provider_id, now)
        previous = row.delivery_status or "sent"
        if DELIVERY_PRIORITY[event] >= DELIVERY_PRIORITY[previous]:
            row.delivery_status = event
            if event in {"failed", "suppressed", "bounced", "complained"}:
                row.last_error = f"Provider reported email {event}"
        if row.delivery_status in {"failed", "suppressed", "bounced", "complained"}:
            # Acceptance is permanent (ledger remains sent), delivery failed.
            # Never submit an already accepted email again; surface it to operators.
            row.status = "failed"
            row.retryable = False
    bounce = data.get("bounce") or {}
    hard_bounce = event == "bounced" and (
        not isinstance(bounce, dict)
        or str(bounce.get("type", "Permanent")).lower() in {"permanent", "hard"}
    )
    if event in {"complained", "suppressed"} or hard_bounce:
        for address in addresses:
            session.execute(
                insert(models.EmailSuppression)
                .values(address=address, reason=event, created_at=now)
                .on_conflict_do_nothing(index_elements=["address"])
            )
            for pending in session.scalars(
                select(models.EmailOutbox)
                .where(
                    models.EmailOutbox.recipient == address,
                    models.EmailOutbox.provider_id.is_(None),
                    models.EmailOutbox.status.in_(["queued", "sending", "failed", "dead"]),
                )
                .with_for_update()
            ):
                pending.status = "suppressed"
                pending.updated_at = now
                _receipt_status(session, pending, "suppressed")
    return True
