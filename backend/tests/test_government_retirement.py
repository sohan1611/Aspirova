"""Local disposable PostgreSQL fixtures; no source/network fetches."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from core import models
from core.adapters import NormalizedListing, RawListing
from crawlers import runner
from pipeline.expire import expire_missing_opportunities
from pipeline.ingest import ingest_one, load_board_state
from pipeline.retirement import GOVERNMENT_NOTICE_SOURCES, retire_rolling_window_listings
from tests.test_audit_retirement import _opportunity
from tests.test_audit_retirement import board as board
from tests.test_audit_retirement import db_session as db_session


@pytest.mark.parametrize("slug", sorted(GOVERNMENT_NOTICE_SOURCES))
def test_only_undated_stale_notices_use_ttl(db_session, board, slug):
    _, company, _ = board
    now = datetime.now(timezone.utc)
    source = models.Source(slug=uuid.uuid4().hex, adapter_key=slug, type="aggregator")
    db_session.add(source)
    db_session.flush()
    db_session.add(
        models.CrawlRun(source_id=source.id, status="success", started_at=now, finished_at=now)
    )
    stale = _opportunity(db_session, company, slug, days=46)
    fresh = _opportunity(db_session, company, slug, days=44)
    dated = _opportunity(db_session, company, slug, days=46)
    dated.deadline = now + timedelta(days=30)
    expired = _opportunity(db_session, company, slug, days=1)
    expired.deadline = now - timedelta(days=1)
    db_session.flush()
    retire_rolling_window_listings(db_session)
    expire_missing_opportunities(db_session)
    db_session.expire_all()
    assert stale.closed_at is not None
    assert stale.meta["closed_reason"] == "rolling_window_ttl"
    assert fresh.closed_at is None
    assert dated.closed_at is None
    assert expired.closed_at is not None


@pytest.mark.parametrize("reason", [None, "cancelled"])
def test_same_notice_extension_updates_and_reopens_only_deadline_closure(
    db_session, board, monkeypatch, reason
):
    _, company, _ = board
    now = datetime.now(timezone.utc)
    source = models.Source(
        slug=uuid.uuid4().hex, adapter_key="drdo", type="aggregator", crawl_tier=1
    )
    db_session.add(source)
    db_session.flush()
    raw = RawListing(
        source_slug="drdo",
        external_id="casdic/2026/02",
        source_url="https://www.drdo.gov.in/notice",
        content_hash="original",
        raw_payload={},
    )
    normalized = NormalizedListing(
        source_slug="drdo",
        external_id=raw.external_id,
        source_url=raw.source_url,
        title="CASDIC Paid Internship",
        company_name=company.name,
        category="internship",
        description_raw="Official internship notice",
        apply_url=raw.source_url,
        deadline=now - timedelta(days=1),
        deadline_confidence="inferred",
    )
    opportunity, _ = ingest_one(
        db_session,
        load_board_state(db_session, source.id, company.id),
        source.id,
        company.id,
        raw,
        normalized,
    )
    db_session.flush()
    identity = opportunity.id
    expire_missing_opportunities(db_session)
    db_session.expire_all()
    assert opportunity.closed_at is not None
    if reason:
        opportunity.meta = {**(opportunity.meta or {}), "closed_reason": reason}
        db_session.flush()
    updated = raw.model_copy(update={"content_hash": "extended"})
    extended = normalized.model_copy(update={"deadline": now + timedelta(days=7)})

    class Adapter:
        source_slug = "drdo"

        def fetch(self):
            return [updated]

        def parse(self, item):
            return extended

        def health(self):
            return "ok"

    monkeypatch.setattr(runner, "resolve_company", lambda *args, **kwargs: company)
    result = runner.crawl_aggregator(db_session, source, Adapter)
    assert result["errors"] == 0
    assert result["new_opps"] == 0
    db_session.expire_all()
    assert opportunity.id == identity
    assert opportunity.deadline == extended.deadline
    assert (opportunity.closed_at is None) is (reason is None)
