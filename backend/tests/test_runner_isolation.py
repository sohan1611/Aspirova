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

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from core import models
from core.adapters import NormalizedListing, RawListing
from crawlers import runner
from pipeline.ingest import ingest_one as real_ingest_one


def _make_fake_adapter_class(listing_count: int) -> type:
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
                    external_id=str(i),
                    source_url=f"https://fake.test/{i}",
                    content_hash=f"hash-{i}",
                    raw_payload={"id": str(i)},
                )
                for i in range(1, listing_count + 1)
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

    return _FakeAdapter


_FakeAdapter = _make_fake_adapter_class(3)


def _make_forced_failure_ingest(fail_on_external_id: str):
    def _ingest(
        session, board_state, source_id, company_id, raw, normalized, seen_opportunity_ids=None
    ):
        if raw.external_id == fail_on_external_id:
            # A real DB-level error - this is what actually aborts the
            # Postgres transaction, which is the condition the original bug
            # depended on.
            session.execute(text("SELECT 1/0"))
        return real_ingest_one(
            session,
            board_state,
            source_id,
            company_id,
            raw,
            normalized,
            seen_opportunity_ids=seen_opportunity_ids,
        )

    return _ingest


_ingest_with_forced_db_failure_on_listing_2 = _make_forced_failure_ingest("2")


@pytest.fixture
def db_session(engine):
    # NOT the rollback-wrapped-transaction pattern used elsewhere (e.g.
    # test_ingest.py) - that pattern assumes the code under test never
    # commits/rolls back itself. crawl_company_board commits and rolls
    # back per listing by design (that IS the fix being tested), which
    # conflicts with an externally-imposed outer transaction. Use a real
    # session (bound to the shared session-scoped engine, tests/conftest.py)
    # and clean up explicitly instead.
    session = Session(engine)
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def seeded(db_session: Session):
    # Unique slugs per test run (Doc handoffs/PHASE-2-HANDOFF.md sec 2/5,
    # Part 2.8) - the old hardcoded "test-isolation-x"/"test-isolation-co-x"
    # meant an interrupted run (killed, crashed, CI cancellation) that never
    # reached the `finally` cleanup below would leave a row behind with
    # that exact slug, and the very next run's INSERT would then fail on
    # sources.slug's/companies.slug's unique constraint - permanently
    # wedging the suite until someone manually deleted the residue. A fresh
    # uuid suffix means an orphaned row from an interrupted run is just
    # harmless residue, never a collision.
    unique = uuid.uuid4().hex[:12]
    source = models.Source(
        slug=f"test-isolation-{unique}", name="Test Greenhouse", type="ats", crawl_tier=1
    )
    company = models.Company(
        slug=f"test-isolation-co-{unique}",
        # Unique per-run name: opportunity slugs are derived from the company
        # name, so this keeps them unique across concurrent runs on a shared DB.
        name=f"Isolation Test Co {unique}",
        name_normalized=f"isolation test co {unique}",
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
    """Listings are committed in batches (BATCH_SIZE=25), not one at a time
    - a real GitHub Actions run showed per-listing commits were far too
    slow under this network's latency (one 484-listing company alone
    consumed most of a 25-minute job). With only 3 fake listings here, none
    of them reach the batch threshold, so listing 1 and listing 2 are both
    still uncommitted when listing 2 fails - rolling back listing 1's work
    too (the intentional batch-blast-radius tradeoff), while listing 3 (a
    fresh, uncontaminated transaction after the rollback) survives via the
    trailing commit. The key regression being guarded against is that the
    failure does NOT cascade past its own batch into listing 3."""
    source, company = seeded
    monkeypatch.setattr(runner, "ingest_one", _ingest_with_forced_db_failure_on_listing_2)

    result = runner.crawl_company_board(db_session, source, company, _FakeAdapter)

    assert result["errors"] == 1
    assert result["new_opps"] == 1
    assert result["listings_found"] == 3

    titles = set(
        db_session.scalars(
            select(models.Opportunity.title).where(models.Opportunity.company_id == company.id)
        ).all()
    )
    assert titles == {"Fake Job 3"}


def test_failure_in_a_later_batch_does_not_roll_back_an_earlier_committed_batch(
    db_session, seeded, monkeypatch
):
    """The actual guarantee that matters at scale: BATCH_SIZE=25, so with 27
    listings, listings 1-25 commit as a batch BEFORE listing 26 fails.
    Losing listing 26 on failure is the accepted tradeoff; losing the
    already-committed batch of 1-25 would be the cascading bug returning at
    a larger scale, which is exactly what this guards against. Listing 27
    starts a fresh batch after the failure and is expected to succeed too,
    via the trailing commit after the loop."""
    source, company = seeded
    monkeypatch.setattr(runner, "ingest_one", _make_forced_failure_ingest("26"))

    result = runner.crawl_company_board(db_session, source, company, _make_fake_adapter_class(27))

    assert result["errors"] == 1
    assert result["new_opps"] == 26  # listings 1-25 (batch 1) + 27 (trailing commit)
    assert result["listings_found"] == 27

    titles = set(
        db_session.scalars(
            select(models.Opportunity.title).where(models.Opportunity.company_id == company.id)
        ).all()
    )
    assert titles == {f"Fake Job {i}" for i in range(1, 26)} | {"Fake Job 27"}


def _make_counting_fake_adapter_class(listings: list[tuple[str, str, str]]) -> type:
    """Return an adapter whose class-level counter is fresh for each crawl."""

    class _CountingFakeAdapter:
        requires_browser = False
        source_slug = "greenhouse"
        parse_calls = 0

        def __init__(self, board_token: str, company_name: str) -> None:
            self.board_token = board_token
            self.company_name = company_name

        def fetch(self) -> list[RawListing]:
            return [
                RawListing(
                    source_slug="greenhouse",
                    external_id=external_id,
                    source_url=f"https://fake.test/{external_id}",
                    content_hash=content_hash,
                    raw_payload={"id": external_id, "title": title},
                )
                for external_id, content_hash, title in listings
            ]

        def parse(self, raw: RawListing) -> NormalizedListing:
            type(self).parse_calls += 1
            return NormalizedListing(
                source_slug="greenhouse",
                external_id=raw.external_id,
                source_url=raw.source_url,
                title=raw.raw_payload["title"],
                company_name=self.company_name,
                description_raw="fake description",
                apply_url=raw.source_url,
            )

        def health(self) -> str:
            return "ok"

    return _CountingFakeAdapter


def test_unchanged_listings_are_not_reparsed_when_the_board_changes(db_session, seeded):
    """A board change must not make unchanged listings pay parse/dedup cost."""
    source, company = seeded
    initial_listings = [
        ("1", "hash-1", "Fake Job 1"),
        ("2", "hash-2", "Fake Job 2"),
        ("3", "hash-3", "Fake Job 3"),
    ]
    initial_adapter = _make_counting_fake_adapter_class(initial_listings)

    runner.crawl_company_board(db_session, source, company, initial_adapter)

    assert initial_adapter.parse_calls == len(initial_listings)
    before_last_seen = dict(
        db_session.execute(
            select(models.Opportunity.id, models.Opportunity.last_seen_at).where(
                models.Opportunity.company_id == company.id
            )
        ).all()
    )
    assert len(before_last_seen) == len(initial_listings)
    assert all(last_seen_at is not None for last_seen_at in before_last_seen.values())

    # Adding one listing changes the board fingerprint, so the per-board
    # change-detection fast path cannot hide the per-listing behavior.
    updated_adapter = _make_counting_fake_adapter_class(
        [*initial_listings, ("4", "hash-4", "Fake Job 4")]
    )
    runner.crawl_company_board(db_session, source, company, updated_adapter)

    assert updated_adapter.parse_calls == 1
    db_session.expire_all()
    after_last_seen = dict(
        db_session.execute(
            select(models.Opportunity.id, models.Opportunity.last_seen_at).where(
                models.Opportunity.company_id == company.id
            )
        ).all()
    )
    assert len(after_last_seen) == len(initial_listings) + 1
    assert set(before_last_seen).issubset(after_last_seen)
    assert all(
        after_last_seen[opportunity_id] > before_last_seen[opportunity_id]
        for opportunity_id in before_last_seen
    )


def test_changed_listing_is_reparsed(db_session, seeded):
    """A changed raw content hash still takes the full ingest/update path."""
    source, company = seeded
    initial_adapter = _make_counting_fake_adapter_class(
        [
            ("1", "hash-1", "Fake Job 1"),
            ("2", "hash-2", "Fake Job 2"),
            ("3", "hash-3", "Fake Job 3"),
        ]
    )
    runner.crawl_company_board(db_session, source, company, initial_adapter)

    changed_adapter = _make_counting_fake_adapter_class(
        [
            ("1", "hash-1-updated", "Fake Job 1 Updated"),
            ("2", "hash-2", "Fake Job 2"),
            ("3", "hash-3", "Fake Job 3"),
        ]
    )
    runner.crawl_company_board(db_session, source, company, changed_adapter)

    assert changed_adapter.parse_calls == 1
    title = db_session.scalar(
        select(models.Opportunity.title).where(
            models.Opportunity.company_id == company.id,
            models.Opportunity.title == "Fake Job 1 Updated",
        )
    )
    assert title == "Fake Job 1 Updated"
