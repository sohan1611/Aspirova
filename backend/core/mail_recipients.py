"""Query-level suppression and a user lock shared with account deletion."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from core import models


def recipient_filters():
    return (models.User.deleted_at.is_(None), models.User.email.is_not(None))


def lock_recipient(
    session: Session, user_id: uuid.UUID, *, skip_locked: bool = True
) -> models.User | None:
    # Hold through the outbound submission and delivery record commit. A
    # deletion waiting for this lock then purges that record in its transaction.
    # FOR KEY SHARE, like get_current_user: only deletion's FOR UPDATE conflicts,
    # so skip_locked skips users being deleted, never users who are browsing.
    user = session.scalar(
        select(models.User)
        .where(models.User.id == user_id, *recipient_filters())
        .with_for_update(read=True, key_share=True, skip_locked=skip_locked)
        .execution_options(populate_existing=True)
    )
    if user is not None:
        from core.email_outbox import _address_lock

        # Serialize email selection across kinds, without blocking ordinary
        # authenticated browsing. The outbox commit releases this reservation.
        _address_lock(session, user.email.strip().lower())
    return user
