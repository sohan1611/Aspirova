"""Daily email alerts for new opportunities matching saved searches."""

import logging
from datetime import datetime, timezone
from urllib.parse import urlencode

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from api.filters import saved_search_base_filters
from core import models
from core.config import get_settings
from core.email_components import greeting, grouped_cards
from core.email_templates import email_layout, text_footer
from core.unsubscribe import list_unsubscribe_headers, unsubscribe_url
from pipeline.notifications import send_email

logger = logging.getLogger(__name__)


def _filter_summary(params: dict) -> str:
    parts: list[str] = []
    query = params.get("q")
    if isinstance(query, str) and query.strip():
        parts.append(query.strip())

    for key in ("category", "kind", "source", "experience"):
        value = params.get(key)
        if value:
            parts.append(str(value).replace("_", " "))

    if params.get("remote") is True:
        parts.append("remote")
    elif params.get("remote") is False:
        parts.append("on-site")

    country = params.get("country")
    if country:
        parts.append(str(country).upper())

    if not country and params.get("scope") in {"abroad", "domestic"}:
        parts.append(params["scope"])
    for key in ("role", "status"):
        if params.get(key):
            parts.append(params[key])
    for key in ("location", "comp_type", "organiser_type", "mode"):
        parts.extend(value.replace("_", " ") for value in params.get(key, []) or [])
    if params.get("paid") is True:
        parts.append("paid")
    elif params.get("paid") is False:
        parts.append("unpaid or pay not stated")
    if params.get("min_stipend") is not None:
        parts.append(f"at least ₹{params['min_stipend']:,}/month")
    if params.get("part_time") is True:
        parts.append("part-time")
    if params.get("max_duration") is not None:
        parts.append(f"up to {params['max_duration']} months")
    if params.get("job_offer") is True:
        parts.append("job offer possible")
    if params.get("registration"):
        parts.append(f"{params['registration']} registration")
    if params.get("deadline_within") is not None:
        parts.append(f"closing within {params['deadline_within']} days")
    if params.get("prize_min") is not None:
        parts.append(f"prize at least ₹{params['prize_min']:,}")

    return " · ".join(parts) or "your saved filters"


def _saved_search_url(params: dict) -> str:
    path = "/competitions" if params.get("kind") == "competitions" else "/"
    base_url = f"{get_settings().site_url.rstrip('/')}{path}"
    values = [
        (key, str(value).lower() if isinstance(value, bool) else value)
        for key, value in params.items()
        if value is not None
    ]
    query = urlencode(values, doseq=True)
    return f"{base_url}?{query}" if query else base_url


def _render_saved_search_alert(
    saved_search: models.SavedSearch,
    opportunities: list[models.Opportunity],
    unsub_url: str | None = None,
    *,
    display_name: str | None = None,
    now: datetime | None = None,
) -> tuple[str, str]:
    params = saved_search.params
    label = (
        saved_search.name.strip()
        if saved_search.name and saved_search.name.strip()
        else _filter_summary(params)
    )
    count = len(opportunities)
    summary = f"{count} new {'match' if count == 1 else 'matches'} for ‘{label}’"
    body, cards_text, _ = grouped_cards(opportunities, now=now or datetime.now(timezone.utc))
    html = email_layout(
        title="New matches for your saved search",
        kind_label="Saved search",
        unsubscribe_url=unsub_url,
        greeting=greeting(display_name),
        summary=summary,
        preheader=summary,
        body_html=body,
        cta_label="See all matches",
        cta_url=_saved_search_url(params),
    )
    return html, "\n\n".join([greeting(display_name), summary, cards_text, text_footer(unsub_url)])


def send_saved_search_alerts(
    session: Session,
    *,
    now: datetime | None = None,
) -> dict[str, int]:
    """Send each enabled saved search a one-time list of newly seen matches."""

    now = now or datetime.now(timezone.utc)
    result = {"searches": 0, "emailed": 0, "skipped_empty": 0}
    saved_searches = session.execute(
        select(models.SavedSearch, models.User)
        .join(models.User, models.User.id == models.SavedSearch.user_id)
        .where(models.SavedSearch.alerts_enabled.is_(True))
    ).all()

    for saved_search, user in saved_searches:
        result["searches"] += 1
        try:
            if not user.email:
                continue

            params = saved_search.params
            filters = saved_search_base_filters(params)
            new_since = saved_search.last_alerted_at or saved_search.created_at
            filters.append(models.Opportunity.first_seen_at > new_since)
            filters.append(models.Opportunity.first_seen_at <= now)

            query = params.get("q")
            if isinstance(query, str) and (query := query.strip()):
                filters.append(
                    models.Opportunity.search_tsv.op("@@")(
                        func.websearch_to_tsquery("english", query)
                    )
                )

            opportunities = list(
                session.scalars(
                    select(models.Opportunity)
                    .options(joinedload(models.Opportunity.company))
                    .where(*filters)
                    .order_by(models.Opportunity.first_seen_at.desc())
                    .limit(10)
                )
                .unique()
                .all()
            )
            if not opportunities:
                result["skipped_empty"] += 1
                continue

            preference_key = f"saved_search:{saved_search.id}"
            html, text = _render_saved_search_alert(
                saved_search,
                opportunities,
                unsubscribe_url(user.id, preference_key),
                display_name=user.display_name,
                now=now,
            )
            subject = (
                f"{len(opportunities)} new match"
                f"{'es' if len(opportunities) > 1 else ''} for your saved search"
            )
            sent = send_email(
                user.email,
                subject,
                html,
                text,
                headers=list_unsubscribe_headers(user.id, preference_key),
            )
            saved_search.last_alerted_at = now
            session.add(
                models.Notification(
                    user_id=user.id,
                    type="saved_search_alert",
                    status="sent" if sent else "failed",
                    sent_at=now if sent else None,
                    meta={
                        "saved_search_id": saved_search.id,
                        "opportunity_ids": [opportunity.id for opportunity in opportunities],
                    },
                )
            )
            session.commit()
            if sent:
                result["emailed"] += 1
        except Exception:
            session.rollback()
            logger.exception("saved-search alert failed for saved search %s", saved_search.id)

    return result
