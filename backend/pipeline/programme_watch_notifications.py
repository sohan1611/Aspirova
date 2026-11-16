"""Calendar changes delivered in-app and through the existing daily digest.

The watch row is the change-detection cursor. Its cursor and in-app notification
are saved together, while the notification's email_pending flag is consumed only
after a successful digest. A failed email therefore never loses an in-app update
or creates a second notification when retried.
"""

import calendar
from dataclasses import dataclass, field
from datetime import date, datetime
from html import escape
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from core import models
from core.config import get_settings
from core.email_components import BODY_FONT, BORDER, BRAND, INK, MUTED, TABLE, section
from core.programme_watches import programme_change, programme_signature, programme_state

EVENT_LABELS = {
    "announced": "Official dates announced",
    "open": "Applications open",
    "deadline_set": "Official deadline published",
    "deadline_changed": "Official deadline changed",
    "closed": "Applications closed",
}


def _email_enabled(user: models.User) -> bool:
    prefs = user.notification_prefs
    return not isinstance(prefs, dict) or prefs.get("daily_digest") is not False


def _watches(session: Session, user_id, *, lock: bool = False):
    query = (
        select(models.ProgrammeWatch)
        .options(
            selectinload(models.ProgrammeWatch.programme).selectinload(models.Programme.editions)
        )
        .where(models.ProgrammeWatch.user_id == user_id)
        .order_by(models.ProgrammeWatch.id)
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return list(session.scalars(query))


def collect_programme_watch_changes(session: Session, user: models.User, now: datetime) -> int:
    """Save new in-app events atomically; caller owns the transaction/user lock."""
    enabled = _email_enabled(user)
    count = 0
    watches = _watches(session, user.id, lock=True)
    programmes, windows = _current_programmes(watches, now)
    for watch in watches:
        programme = watch.programme
        if not programme.is_active:
            continue
        change = programme_change(watch.notified_signature, programme, now=now)
        if change:
            session.add(
                models.Notification(
                    user_id=user.id,
                    type="programme_watch",
                    channel="in_app",
                    status="sent",
                    sent_at=now,
                    meta={
                        **change,
                        "programme_id": programme.id,
                        "email_pending": enabled,
                    },
                )
            )
            watch.notified_at = now
            count += 1
        watch.notified_signature = (
            change["signature"] if change else programme_signature(programme, now=now)
        )
    for notification in _pending_notifications(session, user.id):
        programme_id = notification.meta.get("programme_id")
        if (
            not enabled
            or _live_pending_meta(
                notification.meta, programmes.get(programme_id), windows.get(programme_id, {})
            )
            is None
        ):
            # Retain the in-app history, but cancel email whose official basis
            # was withdrawn (or whose reader opted out) before delivery.
            notification.meta = {**notification.meta, "email_pending": False}
    session.flush()
    return count


def _pending_notifications(session: Session, user_id) -> list[models.Notification]:
    return list(
        session.scalars(
            select(models.Notification)
            .where(
                models.Notification.user_id == user_id,
                models.Notification.type == "programme_watch",
                models.Notification.status == "sent",
                models.Notification.meta["email_pending"].as_boolean().is_(True),
            )
            .order_by(models.Notification.sent_at, models.Notification.id)
        )
    )


@dataclass
class ProgrammeWatchUpdate:
    meta: dict
    notification_ids: list[int] = field(default_factory=list)


def _current_programmes(watches: list[models.ProgrammeWatch], now: datetime) -> tuple[dict, dict]:
    programmes = {
        watch.programme_id: watch.programme for watch in watches if watch.programme.is_active
    }
    windows = {
        programme_id: {
            window["key"]: window for window in programme_state(programme, now=now)["windows"]
        }
        for programme_id, programme in programmes.items()
    }
    return programmes, windows


def _live_pending_meta(
    meta: dict, programme: models.Programme | None, windows: dict
) -> dict | None:
    """Queue email only while its window retains official evidence.

    In-app rows remain historical snapshots. Retried emails use current official
    boundaries, including corrections that did not create another event.
    """
    window = windows.get(meta.get("key"))
    if programme is None or window is None or window["basis"] != "official":
        return None
    event = meta.get("event")
    if (
        event in {"deadline_set", "deadline_changed"}
        and meta.get("closes_at") is not None
        and window["closes_at"] is None
    ):
        return None
    if window["status"] != meta.get("status"):
        event = window["status"]
    return {
        **meta,
        **window,
        "event": event,
        "programme_slug": programme.slug,
        "programme_name": programme.name,
        "programme_url": programme.url,
    }


def programme_watch_updates(
    session: Session, user: models.User, now: datetime
) -> list[ProgrammeWatchUpdate]:
    """Read pending events plus current changes; also used by the pure preview.

    Multiple changes before the next daily email collapse to one current entry
    per programme, while the separate in-app events remain in the history.
    """
    if not _email_enabled(user):
        return []
    watches = _watches(session, user.id)
    programmes, windows = _current_programmes(watches, now)
    updates: dict[int, ProgrammeWatchUpdate] = {}
    for notification in _pending_notifications(session, user.id):
        programme_id = notification.meta.get("programme_id")
        meta = _live_pending_meta(
            notification.meta, programmes.get(programme_id), windows.get(programme_id, {})
        )
        if meta is None:
            continue
        previous = updates.get(programme_id)
        ids = [*(previous.notification_ids if previous else []), notification.id]
        updates[programme_id] = ProgrammeWatchUpdate(meta, ids)
    for watch in watches:
        if watch.programme_id not in programmes:
            continue
        change = programme_change(watch.notified_signature, watch.programme, now=now)
        if change:
            previous = updates.get(watch.programme_id)
            updates[watch.programme_id] = ProgrammeWatchUpdate(
                {**change, "programme_id": watch.programme_id},
                previous.notification_ids if previous else [],
            )
    return sorted(updates.values(), key=lambda update: update.meta["programme_name"].casefold())


def mark_programme_watch_updates_emailed(
    session: Session, updates: list[ProgrammeWatchUpdate], now: datetime
) -> None:
    ids = [notification_id for update in updates for notification_id in update.notification_ids]
    if not ids:
        return
    for notification in session.scalars(
        select(models.Notification).where(models.Notification.id.in_(ids))
    ):
        notification.meta = {
            **notification.meta,
            "email_pending": False,
            "emailed_at": now.isoformat(),
        }


def programme_watch_copy(meta: dict) -> tuple[str, str]:
    label = EVENT_LABELS.get(meta.get("event"), "Programme window updated")
    name = meta.get("programme_name") or "A programme you watch"
    return label, f"{name}: {label.lower()}. Check the official page for details."


def _date_label(value: str | None, precision: str | None) -> str | None:
    if not value:
        return None
    if precision == "month":
        year, month = value.split("-")[:2]
        return f"{calendar.month_abbr[int(month)]} {year}"
    if precision == "day":
        parsed = date.fromisoformat(value)
        return f"{parsed.day} {parsed:%b %Y}"
    return "Date not confirmed"


def render_programme_watch_updates(updates: list[ProgrammeWatchUpdate]) -> tuple[str, str]:
    """Render source precision faithfully; month bounds never become exact days."""
    if not updates:
        return "", ""
    site = get_settings().site_url.rstrip("/")
    cards, plain = [], []
    for update in updates:
        meta = update.meta
        _, message = programme_watch_copy(meta)
        dates = []
        for key, label in (("opens_at", "Opens"), ("closes_at", "Deadline")):
            value = _date_label(meta.get(key), meta.get(key.replace("_at", "_precision")))
            if value:
                dates.append(f"{label}: {value}")
        if meta.get("event") == "deadline_changed" and meta.get("closes_at") is None:
            dates.append("Deadline: Not announced")
        dates_text = " · ".join(dates)
        url = f"{site}/programme/{quote(meta['programme_slug'], safe='')}"
        official_url = meta["programme_url"]
        cards.append(
            f'<table {TABLE} width="100%" style="border:1px solid {BORDER};'
            'border-radius:10px;margin:0 0 12px"><tr><td style="padding:18px;'
            f'{BODY_FONT}color:{INK};font-size:14px;line-height:21px">'
            f'<a href="{escape(url, quote=True)}" style="color:{BRAND};font-weight:700">'
            f'{escape(meta["programme_name"])}</a>'
            f'<p style="margin:8px 0">{escape(message)}</p>'
            f'<p style="color:{MUTED};margin:8px 0">{escape(dates_text)}</p>'
            f'<a href="{escape(official_url, quote=True)}" style="color:{BRAND}">'
            "Check the official page</a></td></tr></table>"
        )
        plain.append("\n".join(part for part in (message, dates_text, url, official_url) if part))
    return (
        section(
            "Programmes you watch", len(updates), "".join(cards), see_all_url=f"{site}/calendar"
        ),
        "Programmes you watch\n\n" + "\n\n".join(plain),
    )
