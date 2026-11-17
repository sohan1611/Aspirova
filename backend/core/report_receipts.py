"""Opaque public receipts. No reporter identity is encoded in a reference."""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from core import models

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
REFERENCE_PATTERN = r"R-[ABCDEFGHJKLMNPQRSTUVWXYZ23456789]{6}"


def new_reference() -> str:
    return "R-" + "".join(secrets.choice(ALPHABET) for _ in range(6))


def store_report(session: Session, **values) -> models.BugReport:
    """Retry only receipt collisions, preserving the caller's transaction."""
    from core import models

    for _ in range(20):
        report = models.BugReport(reference=new_reference(), **values)
        try:
            with session.begin_nested():
                session.add(report)
                session.flush()
            return report
        except IntegrityError as exc:
            if getattr(getattr(exc.orig, "diag", None), "constraint_name", None) != (
                "uq_bug_reports_reference"
            ):
                raise
    raise RuntimeError("Could not allocate a report receipt")
