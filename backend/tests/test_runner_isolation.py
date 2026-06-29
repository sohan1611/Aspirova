"""Regression test for a real bug found via a live GitHub Actions run: two
boards showed huge "error" counts (262/483 and 129/217 listings) that were
actually ONE root-cause failure each, cascading - because nothing rolled
back between per-listing attempts, and Postgres aborts the WHOLE
transaction after any failed statement, so every subsequent command on it
fails identically until something rolls back (Doc 04 sec 7: per-source
isolation must hold at the per-listing level too, not just per-company).

The forced failure must be a real DB-level error (not a plain Python
exception raised before any SQL is sent) - that distinction is exactly
what the original bug depended on, and a test that only raises in Python
would pass even without the fix.
"""

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from core import models
from core.adapters import NormalizedListing, RawListing
from core.db import make_engine
from crawlers import runner
from pipeline.ingest import ingest_normalized_listing as real_ingest_normalized_listing


class _FakeAdapter:
    requires_browser = False
    source_slug = "greenhouse"

    def __init__(self, board_token: str, company_name: str) -> None:
        self.board_token = board_token
        self.company_name = company_name

    def fetch(self) -> list[RawListing]:
        return [
            RawListing(
                source_slug="greenhouse",
                external_id=eid,
                source_url=f"https://fake.test/{eid}",
                content_hash=f"hash-{eid}",
                raw_payload={"id": eid},
            )
            for eid in ("1", "2", "3")
        ]

    def parse(self, raw: RawListing) -> NormalizedListing:
        return NormalizedListing(
            source_slug="greenhouse",
            external_id=raw.external_id,
            source_url=raw.source_url,
            title=f"Fake Job {raw.external_id}",
            company_name=self.company_name,
            description_raw="fake description",
            apply_url=raw.source_url,
        )

    def health(self) -> str:
        return "ok"


def _ingest_with_forced_db_failure_on_listing_2(session, source_id, company_id, raw, normalized):
    if raw.external_id == "2":
        # A real DB-level error - this is what actually aborts the Postgres
        # transaction, which is the condition the original bug depended on.
        session.execute(text("SELECT 1/0"))
    return real_ingest_normalized_listing(session, source_id, company_id, raw, normalized)


@pytest.fixture
def db_session():
    # NOT the rollback-wrapped-transaction pattern used elsewhere (e.g.
    # test_ingest.py) - that pattern assumes the code under test never
    # commits/rolls back itself. crawl_greenhouse_company commits and rolls
    # back per listing by design (that IS the fix being tested), which
    # conflicts with an externally-imposed outer transaction. Use a real
    # session and clean up explicitly instead.
    engine = make_engine()
    session = Session(engine)
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def seeded(db_session: Session):
    source = models.Source(
        slug="test-isolation-x", name="Test Greenhouse", type="ats", crawl_tier=1
    )
    company = models.Company(
        slug="test-isolation-co-x",
        name="Isolation Test Co",
        name_normalized="isolation test co",
        ats_type="greenhouse",
        ats_board_id="fake-board",
    )
    db_session.add_all([source, company])
    db_session.commit()
    try:
        yield source, company
    finally:
        # FK-dependency order: opportunity_sources and raw_listings both
        # reference opportunities, so they must go first.
        db_session.execute(
            models.OpportunitySource.__table__.delete().where(
                models.OpportunitySource.source_id == source.id
            )
        )
        db_session.execute(
            models.RawListing.__table__.delete().where(models.RawListing.source_id == source.id)
        )
        db_session.execute(
            models.Opportunity.__table__.delete().where(models.Opportunity.company_id == company.id)
        )
        db_session.execute(
            models.CrawlRun.__table__.delete().where(models.CrawlRun.source_id == source.id)
        )
        db_session.execute(
            models.SourceState.__table__.delete().where(models.SourceState.source_id == source.id)
        )
        db_session.delete(company)
        db_session.delete(source)
        db_session.commit()


def test_one_bad_listing_does_not_cascade_fail_the_rest(db_session, seeded, monkeypatch):
    source, company = seeded
    monkeypatch.setattr(runner, "GreenhouseAdapter", _FakeAdapter)
    monkeypatch.setattr(
        runner, "ingest_normalized_listing", _ingest_with_forced_db_failure_on_listing_2
    )

    result = runner.crawl_greenhouse_company(db_session, source, company)

    assert result["errors"] == 1
    assert result["new_opps"] == 2
    assert result["listings_found"] == 3

    titles = set(
        db_session.scalars(
            select(models.Opportunity.title).where(models.Opportunity.company_id == company.id)
        ).all()
    )
    assert titles == {"Fake Job 1", "Fake Job 3"}
