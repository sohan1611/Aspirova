"""Deterministic, cross-source email identities; no catalogue rows are merged.

Cities deliberately do not participate: the same title at one employer in two
cities of a country is one role for alerting. Countries remain distinct.
"""

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import DateTime, and_, cast, func, or_, select
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.orm.util import AliasedClass
from sqlalchemy.sql.elements import ColumnElement

from core import models
from core.destination import classify_destination
from pipeline.normalize import normalize_company_name, normalize_title

NEW_LISTING_EVENTS = frozenset({"digest", "instant_alert", "company_alert", "saved_search_alert"})


def _utc(value: datetime) -> datetime:
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )


def _meta(opportunity: models.Opportunity) -> dict:
    return opportunity.meta if isinstance(opportunity.meta, dict) else {}


def role_key(opportunity: models.Opportunity) -> str:
    """Use the exact normalization used to supply ingest's dedup matcher.

    Orphaned listings may retain company_name in metadata. Without any company
    evidence, keep the row's identity rather than merge unrelated employers.
    """
    if opportunity.company_id is not None:
        company = f"id:{opportunity.company_id}"
    else:
        name = _meta(opportunity).get("company_name")
        if not name and opportunity.company is not None:
            name = opportunity.company.name
        company = (
            f"name:{normalize_company_name(name)}"
            if isinstance(name, str) and name.strip()
            else f"unknown:{opportunity.id or opportunity.slug}"
        )
    title = normalize_title(opportunity.title_normalized or opportunity.title)
    country = (opportunity.country or "").strip().upper()
    country = country or ("remote" if opportunity.is_remote else "unknown")
    return json.dumps([company, title, country], ensure_ascii=False, separators=(",", ":"))


def _reopened_after(opportunity: models.Opportunity) -> datetime | None:
    value = _meta(opportunity).get("alert_reopened_after")
    if not isinstance(value, str):
        return None
    try:
        return _utc(datetime.fromisoformat(value))
    except ValueError:
        return None


def version_key(opportunity: models.Opportunity, event: str) -> str:
    """Announcements are fixed per lookback, except a confirmed reopen.

    A reopen retains the previous closure timestamp, never updated_at (which
    advances on ordinary crawls). Closing reminders version only by UTC date.
    """
    if event in NEW_LISTING_EVENTS:
        closed = _reopened_after(opportunity)
        return f"reopened:{closed.isoformat()}" if closed else "new"
    if event == "closing_soon":
        return _utc(opportunity.deadline).date().isoformat() if opportunity.deadline else "undated"
    raise ValueError(f"Unsupported alert event: {event}")


def announcement_meta(opportunities: Iterable[models.Opportunity], event: str) -> dict:
    opportunities = list(opportunities)
    return {
        "role_keys": {str(o.id): role_key(o) for o in opportunities},
        "version_keys": {str(o.id): version_key(o, event) for o in opportunities},
    }


def listing_window(
    since: datetime | ColumnElement[datetime], *, inclusive: bool = True
) -> ColumnElement[bool]:
    """A confirmed reopen can qualify for the same window as a new listing."""
    reopened = cast(models.Opportunity.meta["alert_reopened_at"].astext, DateTime(timezone=True))
    if inclusive:
        return or_(models.Opportunity.first_seen_at >= since, reopened >= since)
    return or_(models.Opportunity.first_seen_at > since, reopened > since)


def role_candidate_filter(
    opportunities: Iterable[models.Opportunity],
    entity: type[models.Opportunity] | AliasedClass = models.Opportunity,
) -> ColumnElement[bool]:
    """Narrow a selector's existing pool to copies of its chosen roles.

    Company-less names are checked by role_key in Python after this coarse
    filter. This never expands the pool beyond the caller's eligibility rules.
    """
    title = func.lower(
        func.trim(
            func.regexp_replace(
                func.coalesce(func.nullif(entity.title_normalized, ""), entity.title),
                r"\s+",
                " ",
                "g",
            )
        )
    )
    return or_(
        False,
        *(
            and_(
                entity.company_id == o.company_id,
                title == normalize_title(o.title_normalized or o.title),
                func.upper(func.trim(func.coalesce(entity.country, "")))
                == (o.country or "").strip().upper(),
                True if o.country else func.coalesce(entity.is_remote, False) == bool(o.is_remote),
            )
            for o in opportunities
        ),
    )


_SentRecord = tuple[str, str | None, datetime]


@dataclass
class SentAlertIndex:
    """One reader's sent identities; all candidate checks are in memory."""

    _by_id: dict[int, list[_SentRecord]] = field(default_factory=dict)
    _by_role: dict[str, list[_SentRecord]] = field(default_factory=dict)

    def _record(
        self,
        identity_id: int,
        role: str | None,
        event: str,
        version: str | None,
        sent_at: datetime,
    ) -> None:
        record = (event, version, _utc(sent_at))
        self._by_id.setdefault(identity_id, []).append(record)
        if role:
            self._by_role.setdefault(role, []).append(record)

    def record_sent(self, meta: dict, event: str, sent_at: datetime) -> None:
        """Add a committed send's snapshots without reloading expired ORM rows."""
        for identity, role in meta["role_keys"].items():
            self._record(int(identity), role, event, meta["version_keys"].get(identity), sent_at)

    def already_notified(self, opportunities: Iterable[models.Opportunity]) -> set[int]:
        alerted: set[int] = set()
        for candidate in opportunities:
            for event, version, sent_at in self._by_id.get(candidate.id, []) + self._by_role.get(
                role_key(candidate), []
            ):
                if event in NEW_LISTING_EVENTS:
                    boundary = _reopened_after(candidate)
                    # Duplicate crawlers can confirm the same reopening at different
                    # times. An announcement after the closure covers both copies.
                    if boundary is None or sent_at >= boundary:
                        alerted.add(candidate.id)
                        break
                elif version == version_key(candidate, event):
                    alerted.add(candidate.id)
                    break
        return alerted


def load_sent_alert_index(
    session: Session,
    user_id: UUID,
    *,
    events: Iterable[str],
    channel: str = "email",
    since: datetime,
) -> SentAlertIndex:
    """Read sent identities in two queries at most, including legacy batches.

    New metadata maps opportunity IDs to immutable role/version snapshots. Old
    single-item rows join their opportunity; old digest/search arrays are loaded
    together in a second query. No per-item reads or cross-channel suppression.
    """
    rows = session.execute(
        select(models.Notification, models.Opportunity, models.EmailOutbox.created_at)
        .outerjoin(models.EmailOutbox, models.EmailOutbox.id == models.Notification.outbox_id)
        .outerjoin(models.Opportunity, models.Opportunity.id == models.Notification.opportunity_id)
        .options(joinedload(models.Opportunity.company))
        .where(
            models.Notification.user_id == user_id,
            models.Notification.type.in_(events),
            models.Notification.channel == channel,
            or_(
                and_(models.Notification.status == "sent", models.Notification.sent_at >= since),
                # Outstanding intents reserve exactly the same role/version identities.
                # A fresh composition must not duplicate an uncertain accepted send.
                and_(
                    models.Notification.outbox_id.is_not(None),
                    models.EmailOutbox.created_at >= since,
                    or_(
                        models.EmailOutbox.status.in_(["queued", "sending"]),
                        models.EmailOutbox.uncertain_since.is_not(None),
                    ),
                ),
            ),
        )
    ).all()
    legacy_ids: set[int] = set()
    records = []
    for row, opportunity, intended_at in rows:
        meta = row.meta if isinstance(row.meta, dict) else {}
        roles = meta.get("role_keys")
        roles = roles if isinstance(roles, dict) else {}
        versions = meta.get("version_keys")
        versions = versions if isinstance(versions, dict) else {}
        ids = {row.opportunity_id} if row.opportunity_id is not None else set()
        for key in ("opportunity_ids", "hackathon_ids"):
            values = meta.get(key)
            if isinstance(values, list):
                ids.update(i for i in values if isinstance(i, int))
        ids.update(int(i) for i in roles if i.isdecimal())
        legacy_ids.update(i for i in ids if str(i) not in roles and i != row.opportunity_id)
        records.append((row, opportunity, ids, roles, versions, intended_at))
    legacy = {}
    if legacy_ids:
        legacy = {
            o.id: o
            for o in session.scalars(
                select(models.Opportunity)
                .options(joinedload(models.Opportunity.company))
                .where(models.Opportunity.id.in_(legacy_ids))
            ).all()
        }

    index = SentAlertIndex()
    for row, joined, ids, roles, versions, intended_at in records:
        for identity_id in ids:
            stored = joined if identity_id == row.opportunity_id else legacy.get(identity_id)
            role = roles.get(str(identity_id))
            if not role and stored is not None:
                role = role_key(stored)
            version = versions.get(str(identity_id))
            if version is None and row.type == "closing_soon" and stored is not None:
                # A legacy reminder never snapshotted its date. The current
                # joined deadline is the only available historical evidence.
                version = version_key(stored, row.type)
            # An intent reserves identities without advancing successful history.
            at = row.sent_at or intended_at
            index._record(identity_id, role, row.type, version, at)
    return index


def already_notified(
    session: Session,
    user_id: UUID,
    opportunities: Iterable[models.Opportunity],
    *,
    events: Iterable[str],
    channel: str = "email",
    since: datetime,
) -> set[int]:
    """One-shot lookup; senders with multiple checks reuse load_sent_alert_index."""
    candidates = list(opportunities)
    if not candidates:
        return set()
    return load_sent_alert_index(
        session,
        user_id,
        events=events,
        channel=channel,
        since=since,
    ).already_notified(candidates)


def collapse_duplicates(opportunities: Iterable[models.Opportunity]) -> list[models.Opportunity]:
    """Keep each role's original slot, replacing its row only for a better source.

    Company and ATS destinations both represent the employer's own listing.
    Within that tier prefer a dated, still-open listing, then oldest first seen.
    Callers supply open candidates; no wall-clock-dependent ranking is used.
    """

    def preference(opportunity: models.Opportunity) -> tuple:
        company = opportunity.company
        destination = classify_destination(
            opportunity.apply_url, company.domain if company else None
        )
        return (
            0 if destination.kind in {"company", "ats"} else 1,
            (
                _utc(opportunity.deadline)
                if opportunity.deadline
                else datetime.max.replace(tzinfo=timezone.utc)
            ),
            (
                _utc(opportunity.first_seen_at)
                if opportunity.first_seen_at
                else datetime.max.replace(tzinfo=timezone.utc)
            ),
        )

    chosen: dict[str, models.Opportunity] = {}
    for opportunity in opportunities:
        key = role_key(opportunity)
        if key not in chosen or preference(opportunity) < preference(chosen[key]):
            chosen[key] = opportunity
    return list(chosen.values())
