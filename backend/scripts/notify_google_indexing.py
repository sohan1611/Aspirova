"""Publish stateful Google Indexing API notifications for job pages.

Usage:
    uv run python -m scripts.notify_google_indexing
    uv run python -m scripts.notify_google_indexing --apply
"""

import argparse
import json
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import quote

import httpx
from google.auth.transport.requests import Request
from google.oauth2.service_account import Credentials
from sqlalchemy import exists, func, not_, or_, select
from sqlalchemy.engine import Row
from sqlalchemy.orm import Session, aliased
from sqlalchemy.sql import Select

from api.filters import exclude_stale_opportunities
from core import models
from core.config import get_settings
from core.db import make_engine

INDEXING_ENDPOINT = "https://indexing.googleapis.com/v3/urlNotifications:publish"
INDEXING_SCOPE = "https://www.googleapis.com/auth/indexing"
HTTP_TIMEOUT_SECONDS = 30.0
ERROR_BODY_LIMIT = 500
PREVIEW_LIMIT = 10

logger = logging.getLogger(__name__)


class PublishResponse(Protocol):
    @property
    def status_code(self) -> int: ...

    @property
    def text(self) -> str: ...


Sender = Callable[[str], PublishResponse]


@dataclass(frozen=True)
class IndexingCandidate:
    opportunity_id: int
    slug: str


@dataclass
class IndexingResult:
    candidates_opened: int
    candidates_closed: int
    sent_opened: int = 0
    sent_closed: int = 0
    failures: int = 0
    attempted: int = 0
    stopped_on_quota: bool = False
    authorization_failed: bool = False

    @property
    def exit_code(self) -> int:
        if self.authorization_failed:
            return 1
        if self.stopped_on_quota:
            return 0
        if self.attempted and not (self.sent_opened or self.sent_closed):
            return 1
        return 0


def _opened_candidate_query() -> Select[tuple[int, str]]:
    already_opened = exists(
        select(models.GoogleIndexingNotification.id).where(
            models.GoogleIndexingNotification.opportunity_id == models.Opportunity.id,
            models.GoogleIndexingNotification.reason == "opened",
        )
    )
    return (
        select(models.Opportunity.id, models.Opportunity.slug)
        .join(models.Company, models.Company.id == models.Opportunity.company_id)
        .where(
            models.Opportunity.category.in_(("job", "internship")),
            models.Opportunity.status == "active",
            models.Opportunity.closed_at.is_(None),
            exclude_stale_opportunities(),
            models.Opportunity.is_hidden.is_not(True),
            func.btrim(func.coalesce(models.Opportunity.title, "")) != "",
            func.btrim(func.coalesce(models.Company.name, "")) != "",
            func.btrim(func.coalesce(models.Opportunity.country, "")) != "",
            models.Opportunity.is_remote.is_not(None),
            func.btrim(func.coalesce(models.Opportunity.description_raw, "")) != "",
            not_(already_opened),
        )
    )


def _closed_candidate_query() -> Select[tuple[int, str]]:
    opened = aliased(models.GoogleIndexingNotification)
    already_closed = exists(
        select(models.GoogleIndexingNotification.id).where(
            models.GoogleIndexingNotification.opportunity_id == models.Opportunity.id,
            models.GoogleIndexingNotification.reason == "closed",
        )
    )
    return (
        select(models.Opportunity.id, models.Opportunity.slug)
        .join(
            opened,
            (opened.opportunity_id == models.Opportunity.id) & (opened.reason == "opened"),
        )
        .where(
            or_(
                models.Opportunity.closed_at.is_not(None),
                models.Opportunity.is_hidden.is_(True),
                not_(exclude_stale_opportunities()),
            ),
            not_(already_closed),
        )
        .order_by(models.Opportunity.first_seen_at.asc(), models.Opportunity.id.asc())
    )


def _to_candidates(rows: Iterable[Row[tuple[int, str]]]) -> list[IndexingCandidate]:
    return [IndexingCandidate(opportunity_id=row.id, slug=row.slug) for row in rows]


def select_opened_candidates(session: Session, limit: int) -> list[IndexingCandidate]:
    """Return newest eligible JobPosting pages not previously published as opened."""
    if limit < 1:
        return []
    rows = session.execute(
        _opened_candidate_query()
        .order_by(models.Opportunity.first_seen_at.desc(), models.Opportunity.id.desc())
        .limit(limit)
    ).all()
    return _to_candidates(rows)


def select_closed_candidates(session: Session, limit: int) -> list[IndexingCandidate]:
    """Return oldest known pages that no longer emit JobPosting markup."""
    if limit < 1:
        return []
    return _to_candidates(session.execute(_closed_candidate_query().limit(limit)).all())


def _candidate_count(session: Session, query: Select[tuple[int, str]]) -> int:
    count_query = select(func.count()).select_from(query.order_by(None).subquery())
    return int(session.scalar(count_query) or 0)


def count_opened_candidates(session: Session) -> int:
    return _candidate_count(session, _opened_candidate_query())


def count_closed_candidates(session: Session) -> int:
    return _candidate_count(session, _closed_candidate_query())


def opportunity_url(site_url: str, slug: str) -> str:
    encoded_slug = quote(slug, safe="-_.!~*'()")
    return f"{site_url.rstrip('/')}/opportunity/{encoded_slug}"


def _response_body(response: PublishResponse) -> str:
    return response.text.replace("\r", " ").replace("\n", " ")[:ERROR_BODY_LIMIT]


def _log_summary(result: IndexingResult) -> None:
    logger.info(
        "candidates opened=%d closed=%d, sent opened=%d closed=%d, "
        "failures=%d, stopped_on_quota=%s",
        result.candidates_opened,
        result.candidates_closed,
        result.sent_opened,
        result.sent_closed,
        result.failures,
        str(result.stopped_on_quota).lower(),
    )


def _preview_candidates(
    session: Session,
    *,
    site_url: str,
    result: IndexingResult,
) -> None:
    logger.info("opened candidates: %d", result.candidates_opened)
    for candidate in select_opened_candidates(session, PREVIEW_LIMIT):
        logger.info("opened preview: %s", opportunity_url(site_url, candidate.slug))

    logger.info("closed candidates: %d", result.candidates_closed)
    for candidate in select_closed_candidates(session, PREVIEW_LIMIT):
        logger.info("closed preview: %s", opportunity_url(site_url, candidate.slug))


def notify_google_indexing(
    session: Session,
    *,
    apply: bool = False,
    limit: int,
    site_url: str,
    sender: Sender | None = None,
) -> IndexingResult:
    """Preview or publish pending notifications, committing every successful URL."""
    if limit < 1:
        raise ValueError("limit must be at least 1")
    if apply and sender is None:
        raise ValueError("sender is required in apply mode")

    result = IndexingResult(
        candidates_opened=count_opened_candidates(session),
        candidates_closed=count_closed_candidates(session),
    )
    if not apply:
        _preview_candidates(session, site_url=site_url, result=result)
        _log_summary(result)
        return result

    assert sender is not None
    closed_candidates = select_closed_candidates(session, limit)
    remaining_budget = limit - len(closed_candidates)
    opened_candidates = select_opened_candidates(session, remaining_budget)

    for reason, candidates in (
        ("closed", closed_candidates),
        ("opened", opened_candidates),
    ):
        for candidate in candidates:
            url = opportunity_url(site_url, candidate.slug)
            result.attempted += 1
            try:
                response = sender(url)
            except Exception as exc:
                result.failures += 1
                logger.error(
                    "Google Indexing publish failed for %s (%s)",
                    url,
                    type(exc).__name__,
                )
                continue

            if response.status_code == 200:
                session.add(
                    models.GoogleIndexingNotification(
                        opportunity_id=candidate.opportunity_id,
                        url=url,
                        reason=reason,
                    )
                )
                session.commit()
                if reason == "opened":
                    result.sent_opened += 1
                else:
                    result.sent_closed += 1
                continue

            result.failures += 1
            if response.status_code == 429:
                result.stopped_on_quota = True
                logger.warning("Google Indexing quota exhausted; stopping this run")
                _log_summary(result)
                return result

            logger.error(
                "Google Indexing publish failed for %s: HTTP %d: %s",
                url,
                response.status_code,
                _response_body(response),
            )
            if response.status_code in {401, 403}:
                result.authorization_failed = True
                _log_summary(result)
                return result

    _log_summary(result)
    return result


def _access_token(service_account_json: str) -> str:
    if not service_account_json.strip():
        raise ValueError("service-account JSON is missing")
    service_account_info = json.loads(service_account_json)
    if not isinstance(service_account_info, dict):
        raise ValueError("service-account JSON must be an object")

    credentials = Credentials.from_service_account_info(
        service_account_info,
        scopes=[INDEXING_SCOPE],
    )
    credentials.refresh(Request())
    if not credentials.token:
        raise ValueError("Google did not return an access token")
    return credentials.token


def _http_sender(client: httpx.Client, access_token: str) -> Sender:
    def send(url: str) -> httpx.Response:
        return client.post(
            INDEXING_ENDPOINT,
            headers={"Authorization": f"Bearer {access_token}"},
            json={"url": url, "type": "URL_UPDATED"},
        )

    return send


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Publish stateful Google Indexing API notifications for job pages."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Preview only (default).")
    mode.add_argument("--apply", action="store_true", help="Publish and record notifications.")
    parser.add_argument(
        "--limit",
        type=_positive_int,
        help="Override the configured daily URL budget for testing.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    settings = get_settings()
    budget = args.limit or settings.indexing_daily_budget
    engine = make_engine()

    with Session(engine) as session:
        if not args.apply:
            result = notify_google_indexing(
                session,
                apply=False,
                limit=budget,
                site_url=settings.site_url,
            )
            return result.exit_code

        try:
            access_token = _access_token(settings.google_indexing_sa_json)
        except Exception:
            logger.error("Google Indexing credentials are missing or invalid")
            result = IndexingResult(
                candidates_opened=count_opened_candidates(session),
                candidates_closed=count_closed_candidates(session),
                failures=1,
                authorization_failed=True,
            )
            _log_summary(result)
            return result.exit_code

        with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS) as client:
            result = notify_google_indexing(
                session,
                apply=True,
                limit=budget,
                site_url=settings.site_url,
                sender=_http_sender(client, access_token),
            )
            return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
