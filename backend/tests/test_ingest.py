"""Integration tests for the ingest/dedup pipeline against the real dev
database (Doc 04 sec 9; PHASE-1-HANDOFF.md Part 1.4 'done' check: same job
from 2 sources -> 1 opportunity + 2 opportunity_sources rows; full re-run =
0 dupes). Requires DATABASE_URL - these are NOT network-free unit tests.

Every test runs inside a transaction that is rolled back at the end, so
nothing persists in the real database (Doc 08: tests must not pollute
shared state).
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core import models
from core.adapters import NormalizedListing, RawListing
from pipeline.ingest import ingest_one, load_board_state


@pytest.fixture
def db_session(engine):
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def seeded(db_session: Session):
    source_a = models.Source(slug="test-greenhouse-x", name="Test Greenhouse", type="ats")
    source_b = models.Source(slug="test-aggregator-x", name="Test Aggregator", type="aggregator")
    company = models.Company(slug="test-acme-x", name="Acme Corp", name_normalized="acme corp")
    db_session.add_all([source_a, source_b, company])
    db_session.flush()
    return source_a, source_b, company


def _raw(external_id: str, url: str, content_hash: str | None = None) -> RawListing:
    return RawListing(
        source_slug="test",
        external_id=external_id,
        source_url=url,
        content_hash=content_hash or f"hash-{external_id}",
        raw_payload={"id": external_id},
    )


def _normalized(
    title: str,
    url: str,
    description: str = "Some description.",
    location: str | None = None,
) -> NormalizedListing:
    return NormalizedListing(
        source_slug="test",
        external_id="x",
        source_url=url,
        title=title,
        company_name="Acme Corp",
        category="internship",
        description_raw=description,
        apply_url=url,
        location=location,
    )


def _ingest(
    db_session: Session,
    source_id: int,
    company_id: int | None,
    raw: RawListing,
    normalized: NormalizedListing,
) -> tuple[models.Opportunity, bool]:
    """Loads a fresh board_state before each call, simulating what
    production actually does: crawlers/runner.py loads board_state once
    per company crawl, and every call site below represents a separate
    crawl of that board (Doc handoffs/PHASE-2-HANDOFF.md sec 2/5)."""
    board_state = load_board_state(db_session, source_id, company_id)
    return ingest_one(db_session, board_state, source_id, company_id, raw, normalized)


def test_same_job_from_two_sources_merges_into_one_opportunity(db_session, seeded):
    """Cross-source merge requires a near-exact title match at the current
    threshold (0.90) - by design, Phase 1 with one source only needs to
    catch verbatim re-posts/syndication; fuzzy cross-source title variants
    are a Phase-3 (embeddings) problem (see pipeline/dedup.py docstring)."""
    source_a, source_b, company = seeded

    raw_a = _raw("job-1", "https://acme.example/jobs/1")
    norm_a = _normalized("Software Engineering Intern", "https://acme.example/jobs/1")
    opp_a, is_new_a = _ingest(db_session, source_a.id, company.id, raw_a, norm_a)
    db_session.flush()
    assert is_new_a is True

    raw_b = _raw("ext-job-1", "https://aggregator.example/acme/1")
    norm_b = _normalized("Software Engineering Intern", "https://aggregator.example/acme/1")
    opp_b, is_new_b = _ingest(db_session, source_b.id, company.id, raw_b, norm_b)
    db_session.flush()

    assert is_new_b is False
    assert opp_b.id == opp_a.id

    opp_count = db_session.scalar(
        select(func.count())
        .select_from(models.Opportunity)
        .where(models.Opportunity.company_id == company.id)
    )
    link_count = db_session.scalar(
        select(func.count())
        .select_from(models.OpportunitySource)
        .where(models.OpportunitySource.opportunity_id == opp_a.id)
    )
    assert opp_count == 1
    assert link_count == 2


def test_full_rerun_creates_zero_duplicates(db_session, seeded):
    source_a, _source_b, company = seeded
    raw = _raw("job-1", "https://acme.example/jobs/1")
    norm = _normalized("Software Engineering Intern", "https://acme.example/jobs/1")

    opp1, is_new1 = _ingest(db_session, source_a.id, company.id, raw, norm)
    db_session.flush()
    opp2, is_new2 = _ingest(db_session, source_a.id, company.id, raw, norm)
    db_session.flush()

    assert is_new1 is True
    assert is_new2 is False
    assert opp1.id == opp2.id

    opp_count = db_session.scalar(
        select(func.count())
        .select_from(models.Opportunity)
        .where(models.Opportunity.company_id == company.id)
    )
    raw_count = db_session.scalar(
        select(func.count())
        .select_from(models.RawListing)
        .where(models.RawListing.source_id == source_a.id)
    )
    link_count = db_session.scalar(
        select(func.count())
        .select_from(models.OpportunitySource)
        .where(models.OpportunitySource.opportunity_id == opp1.id)
    )
    assert opp_count == 1
    assert raw_count == 1
    assert link_count == 1


def test_hackathon_meta_round_trips_and_role_meta_defaults_to_null(db_session, seeded):
    source_a, _source_b, company = seeded
    deadline = datetime(2026, 8, 15, 23, 59, tzinfo=UTC)
    meta = {
        "organizer": "Acme Corp",
        "prize": "INR 100,000",
        "mode": "online",
        "eligibility": "Students",
        "team_size": {"min": 2, "max": 4},
        "registration_deadline": "2026-08-15T23:59:00+00:00",
        "event_start": "2026-08-20T09:00:00+00:00",
        "event_end": "2026-08-22T18:00:00+00:00",
        "tags": ["ai", "web"],
        "platform": "Unstop",
    }
    source_url = "https://acme.example/hackathons/1"
    raw_v1 = _raw("hackathon-1", source_url, content_hash="hash-hackathon-v1")
    normalized_v1 = NormalizedListing(
        source_slug="test",
        external_id="hackathon-1",
        source_url=source_url,
        title="Acme Build Challenge",
        company_name="Acme Corp",
        category="hackathon",
        description_raw="Build a working product.",
        apply_url=source_url,
        deadline=deadline,
        meta=meta,
        deadline_confidence="explicit",
    )
    hackathon, is_new_v1 = _ingest(
        db_session,
        source_a.id,
        company.id,
        raw_v1,
        normalized_v1,
    )
    db_session.flush()

    hackathon_id = hackathon.id
    db_session.expire(hackathon, ["category", "meta", "deadline"])
    assert is_new_v1 is True
    assert hackathon.category == "hackathon"
    assert hackathon.meta == meta
    assert hackathon.deadline == deadline

    updated_deadline = datetime(2026, 8, 17, 23, 59, tzinfo=UTC)
    updated_meta = {**meta, "prize": "INR 150,000"}
    raw_v2 = _raw("hackathon-1", source_url, content_hash="hash-hackathon-v2")
    normalized_v2 = normalized_v1.model_copy(
        update={"deadline": updated_deadline, "meta": updated_meta}
    )
    updated_hackathon, is_new_v2 = _ingest(
        db_session,
        source_a.id,
        company.id,
        raw_v2,
        normalized_v2,
    )
    db_session.flush()
    db_session.expire(updated_hackathon, ["meta", "deadline"])

    assert is_new_v2 is False
    assert updated_hackathon.id == hackathon_id
    assert updated_hackathon.meta == updated_meta
    assert updated_hackathon.deadline == updated_deadline

    role_raw = _raw("job-meta-null", "https://acme.example/jobs/meta-null")
    role_normalized = _normalized("Platform Engineer", role_raw.source_url)
    role, is_new_role = _ingest(
        db_session,
        source_a.id,
        company.id,
        role_raw,
        role_normalized,
    )
    db_session.flush()
    db_session.expire(role, ["meta"])

    assert is_new_role is True
    assert role.meta is None


def test_distinct_roles_at_same_company_do_not_merge(db_session, seeded):
    source_a, _source_b, company = seeded

    raw_1 = _raw("job-1", "https://acme.example/jobs/1")
    norm_1 = _normalized("Backend Engineer", "https://acme.example/jobs/1")
    opp_1, _ = _ingest(db_session, source_a.id, company.id, raw_1, norm_1)
    db_session.flush()

    raw_2 = _raw("job-2", "https://acme.example/jobs/2")
    norm_2 = _normalized("Frontend Engineer", "https://acme.example/jobs/2")
    opp_2, is_new_2 = _ingest(db_session, source_a.id, company.id, raw_2, norm_2)
    db_session.flush()

    assert is_new_2 is True
    assert opp_2.id != opp_1.id


def test_updated_content_refreshes_existing_opportunity_without_duplicating(db_session, seeded):
    source_a, _source_b, company = seeded
    raw_v1 = _raw("job-1", "https://acme.example/jobs/1", content_hash="hash-v1")
    norm_v1 = _normalized(
        "Software Engineering Intern", "https://acme.example/jobs/1", description="Short."
    )
    opp_v1, _ = _ingest(db_session, source_a.id, company.id, raw_v1, norm_v1)
    db_session.flush()

    raw_v2 = _raw("job-1", "https://acme.example/jobs/1", content_hash="hash-v2")
    norm_v2 = _normalized(
        "Software Engineering Intern",
        "https://acme.example/jobs/1",
        description="A much longer, richer description than before.",
    )
    opp_v2, is_new = _ingest(db_session, source_a.id, company.id, raw_v2, norm_v2)
    db_session.flush()

    assert is_new is False
    assert opp_v2.id == opp_v1.id
    assert opp_v2.description_raw == "A much longer, richer description than before."

    raw_count = db_session.scalar(
        select(func.count())
        .select_from(models.RawListing)
        .where(models.RawListing.source_id == source_a.id)
    )
    assert raw_count == 1


def test_same_title_different_location_does_not_merge(db_session, seeded):
    """Regression test: GitLab's real Greenhouse board posts "Senior
    Solutions Architect" as genuinely distinct openings in Germany, US-West,
    India, etc., each with a different apply_url. Title-only similarity
    collapsed all of them into one canonical opportunity in production data
    before this fix (Doc 04 sec 9 - location agreement is required)."""
    source_a, _source_b, company = seeded

    raw_de = _raw("job-de", "https://acme.example/jobs/de")
    norm_de = _normalized(
        "Senior Solutions Architect", "https://acme.example/jobs/de", location="Remote, Germany"
    )
    opp_de, is_new_de = _ingest(db_session, source_a.id, company.id, raw_de, norm_de)
    db_session.flush()

    raw_in = _raw("job-in", "https://acme.example/jobs/in")
    norm_in = _normalized(
        "Senior Solutions Architect, Global SI (India)",
        "https://acme.example/jobs/in",
        location="Remote, India",
    )
    opp_in, is_new_in = _ingest(db_session, source_a.id, company.id, raw_in, norm_in)
    db_session.flush()

    assert is_new_de is True
    assert is_new_in is True
    assert opp_in.id != opp_de.id


def test_same_title_same_location_does_merge(db_session, seeded):
    """The flip side of the regression above: GitLab really did re-post the
    identical "Senior Solutions Architect" / "Remote, Germany" pairing twice
    (two different external_ids) - that genuine duplicate should still
    merge."""
    source_a, _source_b, company = seeded

    raw_1 = _raw("job-de-1", "https://acme.example/jobs/de-1")
    norm_1 = _normalized(
        "Senior Solutions Architect", "https://acme.example/jobs/de-1", location="Remote, Germany"
    )
    opp_1, _ = _ingest(db_session, source_a.id, company.id, raw_1, norm_1)
    db_session.flush()

    raw_2 = _raw("job-de-2", "https://acme.example/jobs/de-2")
    norm_2 = _normalized(
        "Senior Solutions Architect", "https://acme.example/jobs/de-2", location="Remote, Germany"
    )
    opp_2, is_new_2 = _ingest(db_session, source_a.id, company.id, raw_2, norm_2)
    db_session.flush()

    assert is_new_2 is False
    assert opp_2.id == opp_1.id


def test_listing_location_change_does_not_cause_slug_collision(db_session, seeded):
    """Regression test for a real production bug (GH Actions run
    28420810872, 2 of ~2,321 listings): a previously-ingested listing whose
    location changes in place, with its content_hash also changing, must
    update the existing opportunity via the (source_id, external_id)
    identity link on raw_listings - never fall through to dedup (whose
    exact-location filter correctly refuses to self-match a listing whose
    location just changed) and attempt to INSERT a new opportunity at the
    same deterministic slug."""
    source_a, _source_b, company = seeded

    raw_v1 = _raw("job-1", "https://acme.example/jobs/1", content_hash="hash-v1")
    norm_v1 = _normalized(
        "Senior Solutions Architect", "https://acme.example/jobs/1", location="Remote, US"
    )
    opp_v1, is_new_v1 = _ingest(db_session, source_a.id, company.id, raw_v1, norm_v1)
    db_session.flush()
    assert is_new_v1 is True

    raw_v2 = _raw("job-1", "https://acme.example/jobs/1", content_hash="hash-v2")
    norm_v2 = _normalized(
        "Senior Solutions Architect",
        "https://acme.example/jobs/1",
        location="Remote, US; Remote, Canada",
    )
    opp_v2, is_new_v2 = _ingest(db_session, source_a.id, company.id, raw_v2, norm_v2)
    db_session.flush()

    assert is_new_v2 is False
    assert opp_v2.id == opp_v1.id
    assert opp_v2.location == "Remote, US; Remote, Canada"

    opp_count = db_session.scalar(
        select(func.count())
        .select_from(models.Opportunity)
        .where(models.Opportunity.company_id == company.id)
    )
    assert opp_count == 1


def test_pruned_raw_listing_soft_merges_via_slug_instead_of_failing(db_session, seeded):
    """Regression test for the second variant of the same bug: if
    raw_listings is pruned (Doc 03 sec 8 retention) but the opportunity it
    created persists, a re-crawled listing with the same external_id has no
    raw_row to identity-match through - the deterministic slug must still
    be honored as a merge key instead of raising opportunities_slug_key."""
    source_a, _source_b, company = seeded

    raw_v1 = _raw("job-1", "https://acme.example/jobs/1", content_hash="hash-v1")
    norm_v1 = _normalized(
        "Senior Solutions Architect", "https://acme.example/jobs/1", location="Remote, US"
    )
    opp_v1, _ = _ingest(db_session, source_a.id, company.id, raw_v1, norm_v1)
    db_session.flush()

    # Simulate raw_listings retention pruning: null the (nullable) FK first
    # - a real pruning job must do the same, since opportunity_sources ->
    # raw_listings has no ON DELETE CASCADE - then delete the raw_row,
    # keeping the opportunity it created.
    db_session.execute(
        models.OpportunitySource.__table__.update()
        .where(models.OpportunitySource.opportunity_id == opp_v1.id)
        .values(raw_listing_id=None)
    )
    db_session.execute(
        models.RawListing.__table__.delete().where(
            models.RawListing.source_id == source_a.id,
            models.RawListing.external_id == "job-1",
        )
    )
    db_session.flush()

    raw_v2 = _raw("job-1", "https://acme.example/jobs/1", content_hash="hash-v2")
    norm_v2 = _normalized(
        "Senior Solutions Architect",
        "https://acme.example/jobs/1",
        location="Remote, US; Remote, Canada",
    )
    opp_v2, is_new_v2 = _ingest(db_session, source_a.id, company.id, raw_v2, norm_v2)
    db_session.flush()

    assert is_new_v2 is False
    assert opp_v2.id == opp_v1.id

    opp_count = db_session.scalar(
        select(func.count())
        .select_from(models.Opportunity)
        .where(models.Opportunity.company_id == company.id)
    )
    assert opp_count == 1


def test_ingest_derives_and_refreshes_country_on_content_change(db_session, seeded):
    source_a, _source_b, company = seeded
    source_url = "https://acme.example/jobs/country-aware"
    raw_v1 = _raw("country-aware-role", source_url, content_hash="country-hash-v1")
    normalized_v1 = _normalized(
        "Country-aware engineer",
        source_url,
        location="Bengaluru, Karnataka",
    )

    opportunity_v1, is_new_v1 = _ingest(
        db_session,
        source_a.id,
        company.id,
        raw_v1,
        normalized_v1,
    )
    db_session.flush()

    assert is_new_v1 is True
    assert opportunity_v1.country == "IN"

    raw_v2 = _raw("country-aware-role", source_url, content_hash="country-hash-v2")
    normalized_v2 = _normalized(
        "Country-aware engineer",
        source_url,
        location="Toronto, Ontario",
    )
    opportunity_v2, is_new_v2 = _ingest(
        db_session,
        source_a.id,
        company.id,
        raw_v2,
        normalized_v2,
    )
    db_session.flush()

    assert is_new_v2 is False
    assert opportunity_v2.id == opportunity_v1.id
    assert opportunity_v2.country == "CA"
