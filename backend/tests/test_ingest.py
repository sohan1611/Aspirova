"""Integration tests for the ingest/dedup pipeline against the real dev
database (Doc 04 sec 9; PHASE-1-HANDOFF.md Part 1.4 'done' check: same job
from 2 sources -> 1 opportunity + 2 opportunity_sources rows; full re-run =
0 dupes). Requires DATABASE_URL - these are NOT network-free unit tests.

Every test runs inside a transaction that is rolled back at the end, so
nothing persists in the real database (Doc 08: tests must not pollute
shared state).
"""

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from core import models
from core.adapters import NormalizedListing, RawListing
from core.config import get_settings
from pipeline.ingest import ingest_normalized_listing


@pytest.fixture
def db_session():
    engine = create_engine(get_settings().database_url)
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


def test_same_job_from_two_sources_merges_into_one_opportunity(db_session, seeded):
    """Cross-source merge requires a near-exact title match at the current
    threshold (0.90) - by design, Phase 1 with one source only needs to
    catch verbatim re-posts/syndication; fuzzy cross-source title variants
    are a Phase-3 (embeddings) problem (see pipeline/dedup.py docstring)."""
    source_a, source_b, company = seeded

    raw_a = _raw("job-1", "https://acme.example/jobs/1")
    norm_a = _normalized("Software Engineering Intern", "https://acme.example/jobs/1")
    opp_a, is_new_a = ingest_normalized_listing(db_session, source_a.id, company.id, raw_a, norm_a)
    db_session.flush()
    assert is_new_a is True

    raw_b = _raw("ext-job-1", "https://aggregator.example/acme/1")
    norm_b = _normalized("Software Engineering Intern", "https://aggregator.example/acme/1")
    opp_b, is_new_b = ingest_normalized_listing(db_session, source_b.id, company.id, raw_b, norm_b)
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

    opp1, is_new1 = ingest_normalized_listing(db_session, source_a.id, company.id, raw, norm)
    db_session.flush()
    opp2, is_new2 = ingest_normalized_listing(db_session, source_a.id, company.id, raw, norm)
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


def test_distinct_roles_at_same_company_do_not_merge(db_session, seeded):
    source_a, _source_b, company = seeded

    raw_1 = _raw("job-1", "https://acme.example/jobs/1")
    norm_1 = _normalized("Backend Engineer", "https://acme.example/jobs/1")
    opp_1, _ = ingest_normalized_listing(db_session, source_a.id, company.id, raw_1, norm_1)
    db_session.flush()

    raw_2 = _raw("job-2", "https://acme.example/jobs/2")
    norm_2 = _normalized("Frontend Engineer", "https://acme.example/jobs/2")
    opp_2, is_new_2 = ingest_normalized_listing(db_session, source_a.id, company.id, raw_2, norm_2)
    db_session.flush()

    assert is_new_2 is True
    assert opp_2.id != opp_1.id


def test_updated_content_refreshes_existing_opportunity_without_duplicating(db_session, seeded):
    source_a, _source_b, company = seeded
    raw_v1 = _raw("job-1", "https://acme.example/jobs/1", content_hash="hash-v1")
    norm_v1 = _normalized(
        "Software Engineering Intern", "https://acme.example/jobs/1", description="Short."
    )
    opp_v1, _ = ingest_normalized_listing(db_session, source_a.id, company.id, raw_v1, norm_v1)
    db_session.flush()

    raw_v2 = _raw("job-1", "https://acme.example/jobs/1", content_hash="hash-v2")
    norm_v2 = _normalized(
        "Software Engineering Intern",
        "https://acme.example/jobs/1",
        description="A much longer, richer description than before.",
    )
    opp_v2, is_new = ingest_normalized_listing(db_session, source_a.id, company.id, raw_v2, norm_v2)
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
    opp_de, is_new_de = ingest_normalized_listing(
        db_session, source_a.id, company.id, raw_de, norm_de
    )
    db_session.flush()

    raw_in = _raw("job-in", "https://acme.example/jobs/in")
    norm_in = _normalized(
        "Senior Solutions Architect, Global SI (India)",
        "https://acme.example/jobs/in",
        location="Remote, India",
    )
    opp_in, is_new_in = ingest_normalized_listing(
        db_session, source_a.id, company.id, raw_in, norm_in
    )
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
    opp_1, _ = ingest_normalized_listing(db_session, source_a.id, company.id, raw_1, norm_1)
    db_session.flush()

    raw_2 = _raw("job-de-2", "https://acme.example/jobs/de-2")
    norm_2 = _normalized(
        "Senior Solutions Architect", "https://acme.example/jobs/de-2", location="Remote, Germany"
    )
    opp_2, is_new_2 = ingest_normalized_listing(db_session, source_a.id, company.id, raw_2, norm_2)
    db_session.flush()

    assert is_new_2 is False
    assert opp_2.id == opp_1.id
