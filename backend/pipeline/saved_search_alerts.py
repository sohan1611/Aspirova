"""Daily email alerts for new opportunities matching saved searches."""

import logging
from datetime import datetime, timezone
from html import escape
from urllib.parse import urlencode

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from api.filters import saved_search_base_filters
from core import models
from core.config import get_settings
from core.email_client import send_email
from core.email_templates import email_layout, text_footer

logger = logging.getLogger(__name__)


def _company_name(opportunity: models.Opportunity) -> str:
    return opportunity.company.name if opportunity.company else "Unknown"


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

    return " · ".join(parts) or "your saved filters"


def _saved_search_url(params: dict) -> str:
    base_url = f"{get_settings().site_url.rstrip('/')}/"
    query = urlencode([(key, value) for key, value in params.items() if value is not None])
    return f"{base_url}?{query}" if query else base_url


def _render_saved_search_alert(
    saved_search: models.SavedSearch,
    opportunities: list[models.Opportunity],
) -> tuple[str, str]:
    params = saved_search.params
    label = (
        saved_search.name.strip()
        if saved_search.name and saved_search.name.strip()
        else _filter_summary(params)
    )
    text_rows = [
        f"- {opportunity.title} at {_company_name(opportunity)}: "
        f"View & apply: {opportunity.apply_url}"
        for opportunity in opportunities
    ]
    text = (
        f"New opportunities matching '{label}' —\n\n"
        + "\n".join(text_rows)
        + "\n\n"
        + text_footer()
    )
    html_rows = "".join(
        (
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
            'style="border:1px solid #e7e0d4;border-collapse:separate;border-radius:8px;'
            'border-spacing:0;margin:0 0 12px;width:100%">'
            '<tr><td style="padding:16px">'
            "<p style=\"color:#2b2620;font-family:Georgia,'Times New Roman',serif;font-size:17px;"
            'font-weight:700;line-height:23px;margin:0 0 4px">'
            f"{escape(opportunity.title, quote=True)}</p>"
            '<p style="color:#6b6259;font-family:Arial,Helvetica,sans-serif;font-size:14px;'
            'line-height:20px;margin:0 0 10px">'
            f"at {escape(_company_name(opportunity), quote=True)}</p>"
            f'<a href="{escape(opportunity.apply_url, quote=True)}" '
            'style="color:#5e2b47;font-family:Arial,Helvetica,sans-serif;font-size:14px;'
            'font-weight:700;text-decoration:underline">View &amp; apply &rarr;</a>'
            "</td></tr></table>"
        )
        for opportunity in opportunities
    )
    html = email_layout(
        title="New matches for your saved search",
        intro_html=(
            '<p style="color:#6b6259;font-family:Arial,Helvetica,sans-serif;font-size:15px;'
            'line-height:22px;margin:0 0 20px">'
            f"New opportunities matching &lsquo;{escape(label, quote=True)}&rsquo; &mdash;</p>"
        ),
        body_html=html_rows,
        cta_label="See all matches",
        cta_url=_saved_search_url(params),
    )
    return html, text


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

            html, text = _render_saved_search_alert(saved_search, opportunities)
            subject = (
                f"{len(opportunities)} new match"
                f"{'es' if len(opportunities) > 1 else ''} for your saved search"
            )
            sent = send_email(user.email, subject, html, text)
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
