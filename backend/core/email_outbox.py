"""Postgres email queue. Commit an intent and a budgeted lease BEFORE any HTTP.

Only this module may authorize the email_client transport. The optional legacy
sender seam keeps offline rendering/worker tests independent of a provider SDK.
Receipts and cursor effects commit with acceptance, including on crash recovery.
"""

import hashlib
import json
import math
import random
import uuid
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from sqlalchemy import func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from core import models
from core.config import get_settings
from core.email_budget import sent_today, utc_midnight

SAFE_RETRY_WINDOW = timedelta(hours=23)  # Resend expires keys at 24 h; allow clock margin.
Sender = Callable[..., bool]


@dataclass
class ProviderResult:
    code: int | None = None
    message: str = "Provider response unavailable; acceptance uncertain"
    provider_id: str | None = None
    retry_after: str | None = None


@dataclass
class Submission:
    key: str
    payload: dict
    result: ProviderResult | None = None


current_submission: ContextVar[Submission | None] = ContextVar("email_submission", default=None)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def dedupe_key(recipient: str, kind: str, identity: object) -> str:
    value = json.dumps([recipient.strip().lower(), kind, identity], sort_keys=True, default=str)
    return "email/" + hashlib.sha256(value.encode()).hexdigest()


def _address_lock(session: Session, address: str) -> None:
    # Same lock order in workers and webhooks. Serializes suppression with HTTP,
    # so after a suppression commits no subsequent request can start for this address.
    session.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(address, 702))))


def enqueue(
    session: Session,
    *,
    to: str,
    kind: str,
    identity: object,
    payload: dict,
    user_id: uuid.UUID | None = None,
    receipts: list[dict] | None = None,
    effects: dict | None = None,
    now: datetime | None = None,
) -> models.EmailOutbox:
    now = now or utcnow()
    address = to.strip().lower()
    key = dedupe_key(address, kind, identity)
    # Resend echoes tags in delivery webhooks, including when HTTP acceptance
    # was lost. Only a non-PII key is added; rendered email content is unchanged.
    payload = {**payload, "tags": [{"name": "outbox_key", "value": key.removeprefix("email/")}]}
    _address_lock(session, address)
    suppressed = session.get(models.EmailSuppression, address) is not None
    row_id = session.scalar(
        insert(models.EmailOutbox)
        .values(
            user_id=user_id,
            recipient=address,
            kind=kind,
            dedupe_key=key,
            payload=payload,
            effects=effects or {},
            status="suppressed" if suppressed else "queued",
            attempts=0,
            next_attempt_at=now,
            retryable=True,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_nothing(index_elements=["dedupe_key"])
        .returning(models.EmailOutbox.id)
    )
    if row_id is None:
        return session.scalar(
            select(models.EmailOutbox).where(models.EmailOutbox.dedupe_key == key)
        )
    row = session.get(models.EmailOutbox, row_id)
    for receipt in receipts or []:
        session.add(
            models.Notification(
                user_id=user_id,
                outbox_id=row.id,
                type=receipt.get("type", kind),
                opportunity_id=receipt.get("opportunity_id"),
                channel="email",
                status="suppressed" if suppressed else "queued",
                meta=receipt.get("meta"),
            )
        )
    session.flush()
    return row


def _receipt_status(session: Session, row: models.EmailOutbox, status: str) -> None:
    session.execute(
        update(models.Notification)
        .where(models.Notification.outbox_id == row.id)
        .values(status=status, sent_at=row.sent_at if status == "sent" else None)
    )


def reserved_notification_ids(session: Session, user_id: uuid.UUID) -> set[int]:
    """In-app notices already owned by an immutable intent must not be recomposed."""
    return {
        identity
        for effects in session.scalars(
            select(models.EmailOutbox.effects).where(
                models.EmailOutbox.user_id == user_id,
                or_(
                    models.EmailOutbox.status != "suppressed",
                    models.EmailOutbox.uncertain_since.is_not(None),
                ),
            )
        )
        for identity in effects.get("emailed_notification_ids", [])
    }


def _notices_cancelled(session: Session, row: models.EmailOutbox, now: datetime) -> bool:
    """Retain existing opt-out/unwatch/cleared-warning gates on queued payloads.

    A payload cannot be edited after an uncertain attempt. Cancel the intent
    instead of sending a notice that the original selector would now withhold.
    """
    from core.programme_watches import programme_state

    notice_ids = row.effects.get("emailed_notification_ids", [])
    if not notice_ids:
        return False
    cancelled = False
    for notice in session.scalars(
        select(models.Notification).where(
            models.Notification.id.in_(notice_ids),
            models.Notification.user_id == row.user_id,
        )
    ):
        meta = notice.meta or {}
        valid = meta.get("email_pending") is not False
        if notice.type == "programme_watch":
            programme_id = meta.get("programme_id")
            watch = session.scalar(
                select(models.ProgrammeWatch.id).where(
                    models.ProgrammeWatch.user_id == row.user_id,
                    models.ProgrammeWatch.programme_id == programme_id,
                )
            )
            programme = session.get(models.Programme, programme_id) if programme_id else None
            state = programme_state(programme, now=now) if programme is not None else {}
            window = next((w for w in state.get("windows", []) if w["key"] == meta.get("key")), {})
            valid = bool(
                valid
                and watch
                and programme
                and programme.is_active
                and window.get("basis") == "official"
            )
        elif notice.type in {"saved_closed", "saved_safety"}:
            bookmark = session.scalar(
                select(models.Bookmark).where(
                    models.Bookmark.user_id == row.user_id,
                    models.Bookmark.opportunity_id == notice.opportunity_id,
                )
            )
            opportunity = session.get(models.Opportunity, notice.opportunity_id)
            valid = bool(valid and bookmark and opportunity)
            if valid and notice.type == "saved_safety":
                valid = opportunity.status == "withdrawn"
            elif valid:
                valid = (
                    bookmark.status == "saved"
                    and opportunity.closed_at is not None
                    and opportunity.status != "withdrawn"
                )
        if not valid:
            cancelled = True
            notice.meta = {**meta, "email_pending": False}
    return cancelled


def _accepted(session: Session, row: models.EmailOutbox, provider_id: str, now: datetime) -> None:
    # All callers hold the row lock. Redelivery/replayed webhooks never add receipts.
    first_acceptance = row.sent_at is None
    row.status = "sent"
    row.provider_id = provider_id
    row.sent_at = row.sent_at or now
    row.delivery_status = row.delivery_status or "sent"
    if row.delivery_status in {"sent", "delivered"}:
        row.last_error = None
    row.updated_at = now
    row.lease_until = None
    row.lease_token = None
    _receipt_status(session, row, "sent")
    if not first_acceptance:
        return
    effects = row.effects
    for receipt in session.scalars(
        select(models.Notification).where(
            models.Notification.user_id == row.user_id,
            models.Notification.id.in_(effects.get("emailed_notification_ids", [])),
        )
    ):
        receipt.meta = {
            **(receipt.meta or {}),
            "email_pending": False,
            "emailed_at": now.isoformat(),
        }
    search_id = effects.get("saved_search_id")
    if search_id:
        search = session.get(models.SavedSearch, search_id)
        if search is not None and search.user_id == row.user_id:
            # Selection covered only through this cutoff, not through the later
            # outage recovery/webhook time. Never skip matches created meanwhile.
            cutoff = datetime.fromisoformat(
                effects.get("saved_search_cutoff", row.created_at.isoformat())
            )
            search.last_alerted_at = max(search.last_alerted_at or cutoff, cutoff)


def backoff(number: int, retry_after: str | None, now: datetime) -> timedelta:
    seconds = min(3600, 30 * 2 ** min(number - 1, 8)) + random.uniform(0, 15)
    if retry_after:
        try:
            delay = float(retry_after)
        except ValueError:
            try:
                delay = (parsedate_to_datetime(retry_after) - now).total_seconds()
            except (ValueError, TypeError, OverflowError):
                delay = 0
        seconds = max(seconds, delay) if math.isfinite(delay) else seconds
    return timedelta(seconds=seconds)


def retry_is_safe(row: models.EmailOutbox, now: datetime) -> bool:
    return row.uncertain_since is None or now < row.uncertain_since + SAFE_RETRY_WINDOW


def attempt_delivery(
    session: Session,
    row_id: int,
    *,
    sender: Sender | None = None,
    now: datetime | None = None,
) -> bool:
    """One attempt, no sleeping. A committed lease counts even if the process dies."""
    from core.email_client import send_email

    now = now or utcnow()
    settings = get_settings()
    address = session.scalar(
        select(models.EmailOutbox.recipient).where(models.EmailOutbox.id == row_id)
    )
    if address is None:
        return False
    _address_lock(session, address)
    row = session.scalar(
        select(models.EmailOutbox)
        .where(models.EmailOutbox.id == row_id)
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    )
    if row is None:
        session.commit()
        return False
    if row.provider_id is not None:
        # A recovered webhook/response is definitive even if an operator raced
        # with it while requeueing. Never submit an accepted message again.
        row.status = (
            "failed"
            if row.delivery_status in {"bounced", "complained", "failed", "suppressed"}
            else "sent"
        )
        session.commit()
        return row.status == "sent"
    if row.status in {"sent", "dead", "failed", "suppressed"}:
        session.commit()
        return row.status == "sent"
    if row.status == "sending" and row.lease_until and row.lease_until > now:
        session.commit()
        return False
    if row.next_attempt_at > now:
        session.commit()
        return False
    if _notices_cancelled(session, row, now):
        row.status = "suppressed"
        row.updated_at = now
        row.last_error = "Cancelled because a notice was withdrawn or unwatched"
        _receipt_status(session, row, "suppressed")
        session.commit()
        return False
    if session.get(models.EmailSuppression, address):
        row.status = "suppressed"
        row.updated_at = now
        _receipt_status(session, row, "suppressed")
        session.commit()
        return False
    if row.user_id is not None and row.kind != "account_deleted":
        user = session.get(models.User, row.user_id)
        preference = row.effects.get("preference_key")
        opted_out = (
            user is not None
            and preference
            and isinstance(user.notification_prefs, dict)
            and user.notification_prefs.get(preference) is False
        )
        search_id = row.effects.get("saved_search_id")
        search = session.get(models.SavedSearch, search_id) if search_id else None
        search_removed = search_id and (search is None or not search.alerts_enabled)
        if user is None or user.deleted_at is not None or opted_out or search_removed:
            row.status = "suppressed"
            _receipt_status(session, row, "suppressed")
            session.commit()
            return False
    if row.status == "sending":
        previous = session.get(models.EmailAttempt, (row.id, row.attempts))
        if previous and previous.finished_at is None:
            previous.finished_at = now
            previous.outcome = "unknown"
            previous.message = "Worker lease expired; acceptance uncertain"
    attempt_limit = settings.email_max_attempts + row.effects.get("recovery_attempts", 0)
    if not retry_is_safe(row, now) or row.attempts >= attempt_limit:
        row.status = "dead"
        row.last_error = (
            "Idempotency window exhausted; reconcile with provider before recovery"
            if not retry_is_safe(row, now)
            else "Maximum delivery attempts exhausted"
        )
        row.updated_at = now
        _receipt_status(session, row, "failed")
        session.commit()
        return False
    # Serialize the cap across every worker AND API process. Recompute under
    # this lock; a per-step budget snapshot alone cannot enforce a global cap.
    session.execute(text("SELECT pg_advisory_xact_lock(702, 85)"))
    reserve = settings.email_digest_reserve if row.kind == "digest" else 0
    used = sent_today(session, now)
    if used >= max(0, settings.email_daily_budget - reserve):
        row.status = "queued"
        row.next_attempt_at = utc_midnight(now) + timedelta(days=1)
        row.updated_at = now
        # Keep the historical deferral marker used by digest fairness ranking.
        for receipt in session.scalars(
            select(models.Notification).where(models.Notification.outbox_id == row.id)
        ):
            receipt.status = "deferred"
            receipt.meta = {
                **(receipt.meta or {}),
                "reason": "budget",
                "deferred_at": now.isoformat(),
            }
        session.commit()
        return False
    session.execute(
        insert(models.EmailBudgetDay)
        .values(day=utc_midnight(now).date(), used=used + 1)
        .on_conflict_do_update(index_elements=["day"], set_={"used": used + 1})
    )
    prior_uncertainty = row.uncertain_since
    row.uncertain_since = prior_uncertainty or now
    row.attempts += 1
    row.status = "sending"
    row.lease_token = uuid.uuid4().hex
    row.lease_until = now + timedelta(seconds=settings.email_lease_seconds)
    row.updated_at = now
    token, number, payload, key = row.lease_token, row.attempts, row.payload, row.dedupe_key
    session.add(models.EmailAttempt(outbox_id=row.id, number=number, started_at=now))
    session.commit()  # durability boundary: no provider call before this commit

    _address_lock(session, address)
    # Deletion waits for this lock through the HTTP call and acceptance commit.
    if row.user_id is not None:
        user = session.scalar(
            select(models.User)
            .where(models.User.id == row.user_id)
            .with_for_update(read=True, key_share=True)
            .execution_options(populate_existing=True)
        )
        if user is None or (user.deleted_at is not None and row.kind != "account_deleted"):
            session.rollback()
            return False
    row = session.scalar(
        select(models.EmailOutbox)
        .where(models.EmailOutbox.id == row_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None or row.lease_token != token or row.status != "sending":
        session.commit()
        return False
    if session.get(models.EmailSuppression, address):
        row.status = "suppressed"
        _receipt_status(session, row, "suppressed")
        session.commit()
        return False
    submission = Submission(key, payload)
    context_token = current_submission.set(submission)
    try:
        ok = (sender or send_email)(
            payload["to"][0],
            payload["subject"],
            payload.get("html", ""),
            payload["text"],
            **({"headers": payload["headers"]} if payload.get("headers") else {}),
        )
        # A boolean-only injected sender is supported for existing worker tests.
        result = submission.result or ProviderResult(
            code=200 if ok else 503, provider_id=f"fake-{key}" if ok else None
        )
    except Exception:
        # Never log exception text: provider errors can embed bodies/addresses/keys.
        result = ProviderResult()
    finally:
        current_submission.reset(context_token)
    attempt = session.get(models.EmailAttempt, (row.id, number))
    attempt.finished_at = now
    attempt.vendor_code = row.last_code = result.code
    row.last_error = None if result.provider_id else result.message
    row.updated_at = now
    row.lease_token = None
    row.lease_until = None
    if result.provider_id:
        attempt.outcome = "sent"
        _accepted(session, row, result.provider_id, now)
    else:
        transient = (
            result.code is None
            or result.code < 400
            or result.code in {408, 429}
            or result.code >= 500
            or (result.code == 409 and result.message.startswith("concurrent_idempotent_requests:"))
        )
        row.retryable = transient
        # A definitive rejection cannot have accepted THIS request. Preserve
        # uncertainty from any earlier request whose response was lost.
        if result.code is not None and 400 <= result.code < 500 and result.code != 408:
            row.uncertain_since = prior_uncertainty
        attempt.message = result.message
        attempt.outcome = "transient" if transient else "permanent"
        row.status = "failed" if not transient else "dead" if number >= attempt_limit else "queued"
        row.next_attempt_at = now + backoff(number, result.retry_after, now)
        _receipt_status(session, row, "failed")
    session.commit()
    return row.status == "sent"


def send(
    session: Session,
    sender: Sender,
    to: str,
    subject: str,
    html: str,
    body_text: str,
    *,
    kind: str,
    identity: object,
    user_id: uuid.UUID | None = None,
    headers: dict[str, str] | None = None,
    receipts: list[dict] | None = None,
    effects: dict | None = None,
    now: datetime | None = None,
) -> bool:
    from core.email_client import _format_from

    settings = get_settings()
    effects = dict(effects or {})
    preference = {
        "digest": "daily_digest",
        "instant_alert": "instant_alerts",
        "closing_soon": "closing_soon",
        "weekly_report": "weekly_report",
    }.get(kind)
    if kind == "saved_search_alert" and effects.get("saved_search_id"):
        preference = f"saved_search:{effects['saved_search_id']}"
    if preference:
        effects["preference_key"] = preference
    payload = {
        "from": _format_from(settings.resend_from_name, settings.resend_from_email),
        "to": [to],
        "subject": subject,
        "text": body_text,
        **({"html": html} if html else {}),
        **({"headers": headers} if headers else {}),
    }
    row = enqueue(
        session,
        to=to,
        kind=kind,
        identity=identity,
        payload=payload,
        user_id=user_id,
        receipts=receipts,
        effects=effects,
        now=now,
    )
    row_id = row.id
    session.commit()
    return attempt_delivery(session, row_id, sender=sender, now=now)


def drain(
    session: Session, *, now: datetime | None = None, limit: int = 200, sender: Sender | None = None
) -> dict[str, int]:
    delivery_now = now
    now = now or utcnow()
    ids = list(
        session.scalars(
            select(models.EmailOutbox.id)
            .where(
                or_(
                    (models.EmailOutbox.status == "queued")
                    & (models.EmailOutbox.next_attempt_at <= now),
                    (models.EmailOutbox.status == "sending")
                    & (models.EmailOutbox.lease_until <= now),
                )
            )
            .order_by(models.EmailOutbox.created_at, models.EmailOutbox.id)
            .limit(limit)
        )
    )
    for row_id in ids:
        attempt_delivery(session, row_id, now=delivery_now, sender=sender)
    return status_counts(session)


def status_counts(session: Session) -> dict[str, int]:
    return dict(
        session.execute(
            select(models.EmailOutbox.status, func.count()).group_by(models.EmailOutbox.status)
        ).all()
    )


def requeue_dead(
    session: Session, *, apply: bool = False, now: datetime | None = None
) -> dict[str, int]:
    now = now or utcnow()
    counts = {"eligible": 0, "blocked": 0}
    query = select(models.EmailOutbox).where(models.EmailOutbox.status == "dead")
    if apply:
        query = query.with_for_update(skip_locked=True).execution_options(populate_existing=True)
    for row in session.scalars(query):
        if not row.retryable or not retry_is_safe(row, now):
            counts["blocked"] += 1
            continue
        counts["eligible"] += 1
        if apply:
            row.status = "queued"
            row.next_attempt_at = now
            row.updated_at = now
            # Recovery grants another bounded set of attempts; attempt numbers
            # remain monotonic so history and daily budget can never be erased.
            row.effects = {**row.effects, "recovery_attempts": row.attempts}
    return counts
