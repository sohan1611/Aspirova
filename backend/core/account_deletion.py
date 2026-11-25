"""Transactional personal-data purge and retryable Supabase cleanup.

The tombstone is permanent: financial records keep referencing the same id.
External calls happen only after its transaction has committed.
"""

import logging
import uuid
from datetime import UTC, datetime

import httpx
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from core import models
from core.config import get_settings
from core.gating import active_subscription_filters

logger = logging.getLogger(__name__)

PERSONAL_COLUMNS = (
    "email",
    "invite_code",
    "display_name",
    "college",
    "graduation_year",
    "notification_prefs",
    "field_profile",
    "skills",
    "exposure",
    "resume",
    "referred_by",
    "created_at",
)
# No child table references these rows; keep this list explicit and reviewed
# whenever a new users.id FK is added. Billing tables are deliberately absent.
OWNED_MODELS = (
    models.Notification,
    models.EmailOutbox,
    models.ProgrammeWatch,
    models.SavedSearch,
    models.Bookmark,
    models.DreamCompany,
    models.ResumeProfile,
    models.BugReport,
)


def tombstone_account(db: Session, user_id: uuid.UUID) -> str | None:
    """Return the captured address; caller commits before sending confirmation.

    A repeated internal call is a no-op and returns no address.
    """
    user = db.scalar(
        select(models.User)
        .where(models.User.id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if user is None or user.deleted_at is not None:
        return
    if (
        db.scalar(
            select(models.Subscription.id).where(
                models.Subscription.user_id == user_id,
                *active_subscription_filters(),
                models.Subscription.razorpay_sub_id.isnot(None),
                models.Subscription.cancel_at_period_end.is_(False),
            )
        )
        is not None
    ):
        # Keep HTTP concerns in the route, but use one transaction/lock for the
        # subscription check and purge, also serializing checkout with deletion.
        raise ActiveSubscriptionError

    email = user.email
    for model in OWNED_MODELS:
        db.execute(delete(model).where(model.user_id == user_id))
    db.execute(
        update(models.User).where(models.User.referred_by == user_id).values(referred_by=None)
    )
    for column in PERSONAL_COLUMNS:
        setattr(user, column, None)
    user.deleted_at = datetime.now(UTC)
    user.deletion_pending = ["storage", "auth"]
    db.flush()
    return email


class ActiveSubscriptionError(Exception):
    pass


def _check(response: httpx.Response) -> None:
    if response.status_code != 404:
        response.raise_for_status()


def _delete_resume_folder(client: httpx.Client, user_id: uuid.UUID) -> None:
    """List all pages, including nested folders, before deleting any objects."""
    folders = [str(user_id)]
    while folders:
        folder = folders.pop()
        paths = []
        offset = 0
        while True:
            response = client.post(
                "/storage/v1/object/list/resumes",
                json={
                    "prefix": folder,
                    "limit": 100,
                    "offset": offset,
                    "sortBy": {"column": "name", "order": "asc"},
                },
            )
            _check(response)
            if response.status_code == 404:
                break
            entries = response.json()
            if not isinstance(entries, list):
                raise ValueError("Invalid storage listing")
            for entry in entries:
                name = entry["name"]
                if not isinstance(name, str) or not name or "/" in name or name in {".", ".."}:
                    raise ValueError("Invalid storage object name")
                path = f"{folder}/{name}"
                if entry.get("id") is None:
                    folders.append(path)
                else:
                    paths.append(path)
            if len(entries) < 100:
                break
            offset += len(entries)
        for start in range(0, len(paths), 100):
            _check(
                client.request(
                    "DELETE",
                    "/storage/v1/object/resumes",
                    json={"prefixes": paths[start : start + 100]},
                )
            )


def _admin_client() -> httpx.Client:
    settings = get_settings()
    return httpx.Client(
        base_url=settings.supabase_url.rstrip("/"),
        timeout=15.0,
        headers={
            "Authorization": f"Bearer {settings.supabase_service_key}",
            "apikey": settings.supabase_service_key,
        },
    )


def finish_external_cleanup(db: Session, user_id: uuid.UUID) -> bool:
    """Retry pending steps; persist each success so crashes are safe to retry.

    Auth follows Storage because Supabase refuses to delete an owner of objects.
    Never log HTTP exceptions: their bodies/headers may contain personal data.
    """
    user = db.scalar(
        select(models.User)
        .where(models.User.id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if user is None or user.deleted_at is None or not user.deletion_pending:
        db.commit()
        return True
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_service_key:
        db.rollback()
        logger.warning("Account cleanup pending: Supabase admin not configured")
        return False
    with _admin_client() as client:
        for step in ("storage", "auth"):
            if step not in user.deletion_pending:
                continue
            try:
                if step == "storage":
                    _delete_resume_folder(client, user_id)
                else:
                    _check(client.delete(f"/auth/v1/admin/users/{user_id}"))
            except Exception:
                logger.warning("Account cleanup pending for user %s step %s", user_id, step)
                # Keep Auth pending too if Storage still owns objects.
                break
            user.deletion_pending = [item for item in user.deletion_pending if item != step]
            db.commit()
            # Reacquire after committing; overlapping retry workers are harmless.
            db.refresh(user, with_for_update=True)
    complete = not user.deletion_pending
    db.commit()
    return complete
