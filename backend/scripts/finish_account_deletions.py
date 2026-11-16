"""Retry committed tombstones: uv run python -m scripts.finish_account_deletions.

No personal data or credentials are printed. Safe to rerun after partial failure.
"""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from core import models
from core.account_deletion import finish_external_cleanup
from core.db import make_engine

logger = logging.getLogger(__name__)


def finish_account_deletions(db: Session) -> int:
    ids = db.scalars(
        select(models.User.id).where(
            models.User.deleted_at.is_not(None),
            models.User.deletion_pending.is_not(None),
            models.User.deletion_pending != [],
        )
    ).all()
    failures = 0
    for user_id in ids:
        try:
            if not finish_external_cleanup(db, user_id):
                failures += 1
        except Exception:
            db.rollback()
            failures += 1
            logger.warning("Account cleanup retry failed for user %s", user_id)
    return failures


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    engine = make_engine()
    try:
        with Session(engine) as db:
            return 1 if finish_account_deletions(db) else 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
