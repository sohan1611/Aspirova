"""Integration tests for the ingest/dedup pipeline against the real dev
database (Doc 04 sec 9; PHASE-1-HANDOFF.md Part 1.4 'done' check: same job
from 2 sources -> 1 opportunity + 2 opportunity_sources rows; full re-run =
0 dupes). Requires DATABASE_URL - these are NOT network-free unit tests.

Every test runs inside a transaction that is rolled back at the end, so
nothing persists in the real database (Doc 08: tests must not pollute
shared state).
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from core import models
from core.adapters import NormalizedListing, RawListing
from crawlers import runner
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
    seen_opportunity_ids: set[int] | None = None,
    changed_slugs: set[str] | None = None,
) -> tuple[models.Opportunity, bool]:
    """Loads a fresh board_state before each call, simulating what
    production actually does: crawlers/runner.py loads board_state once
    per company crawl, and every call site below represents a separate
    crawl of that board (Doc handoffs/PHASE-2-HANDOFF.md sec 2/5)."""
    board_state = load_board_state(db_session, source_id, company_id)
    return ingest_one(
        db_session,
        board_state,
        source_id,
        company_id,
        raw,
        normalized,
        seen_opportunity_ids=seen_opportunity_ids,
        changed_slugs=changed_slugs,
    )


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

    seen_opportunity_ids: set[int] = set()
    opp1, is_new1 = _ingest(
        db_session,
        source_a.id,
        company.id,
        raw,
        norm,
        seen_opportunity_ids=seen_opportunity_ids,
    )
    db_session.flush()
    assert seen_opportunity_ids == set()

    old_last_seen_at = datetime(2000, 1, 1, tzinfo=UTC)
    opp1.last_seen_at = old_last_seen_at
    db_session.flush()

    seen_opportunity_ids = set()
    opp2, is_new2 = _ingest(
        db_session,
        source_a.id,
        company.id,
        raw,
        norm,
        seen_opportunity_ids=seen_opportunity_ids,
    )
    db_session.flush()

    assert is_new1 is True
    assert is_new2 is False
    assert opp1.id == opp2.id
    assert seen_opportunity_ids == {opp1.id}
    assert opp2.last_seen_at == old_last_seen_at

    db_session.execute(
        update(models.Opportunity)
        .where(models.Opportunity.id.in_(seen_opportunity_ids))
        .values(last_seen_at=func.now())
    )
    db_session.flush()
    db_session.refresh(opp2)
    assert opp2.last_seen_at > old_last_seen_at

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


def test_changed_slugs_tracks_new_and_changed_content_but_not_identical_repeat(db_session, seeded):
    source_a, _source_b, company = seeded
    source_url = "https://acme.example/jobs/revalidation"
    raw_v1 = _raw("revalidation-job", source_url, content_hash="hash-v1")
    normalized_v1 = _normalized("Platform Intern", source_url, description="Version one.")
    changed_slugs: set[str] = set()

    opportunity, is_new = _ingest(
        db_session,
        source_a.id,
        company.id,
        raw_v1,
        normalized_v1,
        changed_slugs=changed_slugs,
    )
    db_session.flush()

    assert is_new is True
    assert changed_slugs == {opportunity.slug}

    changed_slugs.clear()
    repeated, is_new_repeat = _ingest(
        db_session,
        source_a.id,
        company.id,
        raw_v1,
        normalized_v1,
        changed_slugs=changed_slugs,
    )
    db_session.flush()

    assert is_new_repeat is False
    assert repeated.id == opportunity.id
    assert changed_slugs == set()

    raw_v2 = _raw("revalidation-job", source_url, content_hash="hash-v2")
    normalized_v2 = _normalized(
        "Platform Intern",
        source_url,
        description="Version two has visibly changed content.",
    )
    updated, is_new_update = _ingest(
        db_session,
        source_a.id,
        company.id,
        raw_v2,
        normalized_v2,
        changed_slugs=changed_slugs,
    )
    db_session.flush()

    assert is_new_update is False
    assert updated.id == opportunity.id
    assert changed_slugs == {opportunity.slug}


def test_changed_slugs_ignores_volatile_raw_payload_only_change(db_session, seeded):
    source_a, _source_b, company = seeded
    source_url = "https://acme.example/jobs/volatile-payload"
    raw_v1 = _raw("volatile-payload-job", source_url, content_hash="hash-v1")
    raw_v1.raw_payload = {
        "id": "volatile-payload-job",
        "publishedAt": "2026-08-10T12:00:00Z",
    }
    normalized = _normalized("Platform Intern", source_url)
    changed_slugs: set[str] = set()

    opportunity, is_new = _ingest(
        db_session,
        source_a.id,
        company.id,
        raw_v1,
        normalized,
        changed_slugs=changed_slugs,
    )
    db_session.flush()

    assert is_new is True
    assert changed_slugs == {opportunity.slug}

    changed_slugs.clear()
    raw_v2 = _raw("volatile-payload-job", source_url, content_hash="hash-v2")
    raw_v2.raw_payload = {
        "id": "volatile-payload-job",
        "publishedAt": "2026-08-11T12:00:00Z",
    }
    updated, is_new_update = _ingest(
        db_session,
        source_a.id,
        company.id,
        raw_v2,
        normalized,
        changed_slugs=changed_slugs,
    )
    db_session.flush()

    raw_row = db_session.scalar(
        select(models.RawListing).where(
            models.RawListing.source_id == source_a.id,
            models.RawListing.external_id == "volatile-payload-job",
        )
    )
    assert is_new_update is False
    assert updated.id == opportunity.id
    assert raw_row.content_hash == raw_v2.content_hash
    assert raw_row.raw_payload == raw_v2.raw_payload
    assert changed_slugs == set()


@pytest.mark.parametrize(
    ("field_name", "updated_value"),
    [
        ("title", "Senior Platform Intern"),
        ("deadline", datetime(2026, 8, 31, 23, 59, tzinfo=UTC)),
        ("apply_url", "https://acme.example/jobs/visible-field/apply"),
    ],
    ids=["title", "deadline", "apply-url"],
)
def test_changed_slugs_tracks_user_visible_field_changes(
    db_session, seeded, field_name, updated_value
):
    source_a, _source_b, company = seeded
    source_url = "https://acme.example/jobs/visible-field"
    raw_v1 = _raw("visible-field-job", source_url, content_hash="hash-v1")
    normalized_v1 = _normalized("Platform Intern", source_url)
    changed_slugs: set[str] = set()

    opportunity, is_new = _ingest(
        db_session,
        source_a.id,
        company.id,
        raw_v1,
        normalized_v1,
        changed_slugs=changed_slugs,
    )
    db_session.flush()

    assert is_new is True
    changed_slugs.clear()

    raw_v2 = _raw("visible-field-job", source_url, content_hash="hash-v2")
    normalized_v2 = normalized_v1.model_copy(update={field_name: updated_value})
    updated, is_new_update = _ingest(
        db_session,
        source_a.id,
        company.id,
        raw_v2,
        normalized_v2,
        changed_slugs=changed_slugs,
    )
    db_session.flush()

    assert is_new_update is False
    assert updated.id == opportunity.id
    assert getattr(updated, field_name) == updated_value
    assert changed_slugs == {opportunity.slug}


def test_changed_slugs_always_tracks_new_opportunity(db_session, seeded):
    source_a, _source_b, company = seeded
    source_url = "https://acme.example/jobs/new-opportunity"
    changed_slugs: set[str] = set()

    opportunity, is_new = _ingest(
        db_session,
        source_a.id,
        company.id,
        _raw("new-opportunity-job", source_url),
        _normalized("New Opportunity Intern", source_url),
        changed_slugs=changed_slugs,
    )
    db_session.flush()

    assert is_new is True
    assert changed_slugs == {opportunity.slug}


def test_changed_slugs_ignores_reordered_skills(db_session, seeded, monkeypatch):
    source_a, _source_b, company = seeded
    source_url = "https://acme.example/jobs/reordered-skills"
    skill_orders = iter((["Python", "SQL"], ["SQL", "Python"]))
    monkeypatch.setattr(
        "pipeline.ingest.extract_opportunity_skills",
        lambda *_args, **_kwargs: next(skill_orders),
    )
    changed_slugs: set[str] = set()
    raw_v1 = _raw("reordered-skills-job", source_url, content_hash="hash-v1")
    normalized = _normalized("Platform Intern", source_url)

    opportunity, is_new = _ingest(
        db_session,
        source_a.id,
        company.id,
        raw_v1,
        normalized,
        changed_slugs=changed_slugs,
    )
    db_session.flush()

    assert is_new is True
    assert opportunity.skills == ["Python", "SQL"]
    changed_slugs.clear()

    raw_v2 = _raw("reordered-skills-job", source_url, content_hash="hash-v2")
    updated, is_new_update = _ingest(
        db_session,
        source_a.id,
        company.id,
        raw_v2,
        normalized,
        changed_slugs=changed_slugs,
    )
    db_session.flush()

    assert is_new_update is False
    assert updated.skills == ["SQL", "Python"]
    assert changed_slugs == set()


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
    assert hackathon.meta == {**meta, "prize_inr": 100000, "prize_text": "INR 100,000"}
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
    assert updated_hackathon.meta == {
        **updated_meta,
        "prize_inr": 150000,
        "prize_text": "INR 150,000",
    }
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


@pytest.mark.parametrize("source_key", ["unstop", "devpost", "devfolio", "remoteok"])
@pytest.mark.parametrize("deadline_days", [1, -1, None])
def test_aggregator_seen_listing_reopens_only_with_full_inventory_and_no_past_deadline(
    db_session: Session,
    seeded,
    monkeypatch: pytest.MonkeyPatch,
    source_key: str,
    deadline_days: int | None,
) -> None:
    source, _other, company = seeded
    source.adapter_key = source_key
    source.type = "aggregator"
    source.crawl_tier = 1
    now = datetime.now(UTC)
    deadline = now + timedelta(days=deadline_days) if deadline_days is not None else None
    raw = _raw("reopen-role", "https://acme.example/jobs/reopen-role").model_copy(
        update={"source_slug": source_key}
    )
    normalized = _normalized("Junior Software Engineer", raw.source_url).model_copy(
        update={"source_slug": source_key, "deadline": deadline}
    )
    opportunity, _ = _ingest(db_session, source.id, company.id, raw, normalized)
    opportunity.closed_at = now - timedelta(days=2)
    db_session.flush()
    opportunity_id = opportunity.id

    class SeenAdapter:
        def fetch(self):
            return [raw]

        def parse(self, _raw):
            return normalized

        def health(self):
            return "ok"

    monkeypatch.setattr(runner, "resolve_company", lambda *_args, **_kwargs: company)
    result = runner.crawl_aggregator(db_session, source, SeenAdapter)
    assert result["status"] == "success"
    assert result["errors"] == 0
    db_session.expire_all()
    refreshed = db_session.get(models.Opportunity, opportunity_id)
    should_reopen = source_key in {"unstop", "devpost", "devfolio"} and deadline_days != -1
    assert (refreshed.closed_at is None) is should_reopen
    assert refreshed.deadline == deadline


@pytest.mark.parametrize("source_key", ["himalayas", "remoteok"])
@pytest.mark.parametrize("deadline_days", [1, -1, None])
@pytest.mark.parametrize("closed_reason", ["rolling_window_ttl", "dead_board", None])
@pytest.mark.parametrize("status", ["active", "expired"])
@pytest.mark.parametrize("unchanged", [False, True])
def test_aggregator_seen_rolling_listing_reopens_only_explicit_ttl_closures(
    db_session: Session,
    seeded,
    monkeypatch: pytest.MonkeyPatch,
    source_key: str,
    deadline_days: int | None,
    closed_reason: str | None,
    status: str,
    unchanged: bool,
) -> None:
    source, _other, company = seeded
    source.adapter_key = source_key
    source.type = "aggregator"
    source.crawl_tier = 1
    now = datetime.now(UTC)
    deadline = now + timedelta(days=deadline_days) if deadline_days is not None else None
    raw = _raw("reseen-rolling-role", "https://acme.example/jobs/reseen-rolling").model_copy(
        update={"source_slug": source_key}
    )
    normalized = _normalized("Junior Software Engineer", raw.source_url).model_copy(
        update={"source_slug": source_key, "deadline": deadline}
    )
    opportunity, _ = _ingest(db_session, source.id, company.id, raw, normalized)
    closed_at = now - timedelta(days=2)
    assert opportunity.primary_source == source_key
    opportunity.closed_at = closed_at
    opportunity.last_seen_at = now - timedelta(days=90)
    opportunity.status = status
    meta = {"keep": {"nested": True}, "liveness_checked_at": now.isoformat()}
    if closed_reason is not None:
        meta["closed_reason"] = closed_reason
    opportunity.meta = meta
    db_session.flush()
    opportunity_id = opportunity.id
    if unchanged:
        db_session.add(
            models.SourceState(
                source_id=source.id,
                page_key="aggregator",
                last_content_hash=runner._board_fingerprint([raw]),
            )
        )
        db_session.flush()

    class SeenAdapter:
        def fetch(self):
            return [raw]

        def parse(self, _raw):
            assert not unchanged, "unchanged feeds must skip parsing"
            return normalized

        def health(self):
            return "ok"

    monkeypatch.setattr(runner, "resolve_company", lambda *_args, **_kwargs: company)
    result = runner.crawl_aggregator(db_session, source, SeenAdapter)
    assert result["status"] == "success"
    assert result["errors"] == 0
    db_session.expire_all()
    refreshed = db_session.get(models.Opportunity, opportunity_id)
    should_reopen = (
        closed_reason == "rolling_window_ttl" and deadline_days != -1 and status == "active"
    )
    assert refreshed.closed_at == (None if should_reopen else closed_at)
    assert refreshed.meta == (
        {key: value for key, value in meta.items() if key != "closed_reason"}
        if should_reopen
        else meta
    )
    assert refreshed.deadline == deadline
    assert refreshed.status == status
    assert refreshed.last_seen_at > now - timedelta(days=1)


def test_aggregator_full_inventory_reopen_removes_closed_reason(
    db_session: Session, seeded, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, _other, company = seeded
    source.adapter_key = "unstop"
    source.type = "aggregator"
    source.crawl_tier = 1
    raw = _raw("reseen-unstop-role", "https://acme.example/jobs/reseen-unstop").model_copy(
        update={"source_slug": "unstop"}
    )
    normalized = _normalized("Junior Software Engineer", raw.source_url).model_copy(
        update={"source_slug": "unstop"}
    )
    opportunity, _ = _ingest(db_session, source.id, company.id, raw, normalized)
    opportunity.closed_at = datetime.now(UTC) - timedelta(days=2)
    opportunity.meta = {"closed_reason": "dead_board", "keep": {"nested": True}}
    db_session.flush()
    opportunity_id = opportunity.id

    class SeenAdapter:
        def fetch(self):
            return [raw]

        def parse(self, _raw):
            return normalized

        def health(self):
            return "ok"

    monkeypatch.setattr(runner, "resolve_company", lambda *_args, **_kwargs: company)
    result = runner.crawl_aggregator(db_session, source, SeenAdapter)
    assert result["status"] == "success"
    assert result["errors"] == 0
    db_session.expire_all()
    refreshed = db_session.get(models.Opportunity, opportunity_id)
    assert refreshed.closed_at is None
    assert refreshed.meta == {"keep": {"nested": True}}


def test_ingest_prefers_explicit_normalized_country(db_session: Session, seeded) -> None:
    source, _other, company = seeded
    raw = _raw("explicit-country", "https://acme.example/jobs/explicit-country")
    normalized = _normalized("Junior Engineer", raw.source_url, location="Online").model_copy(
        update={"country": "IN"}
    )
    opportunity, _ = _ingest(db_session, source.id, company.id, raw, normalized)
    assert opportunity.country == "IN"


@pytest.mark.parametrize("category", ["internship", "job", "hackathon"])
def test_ingest_merges_role_signals_only_for_roles_and_skips_unchanged(
    db_session, seeded, monkeypatch, category
):
    source, _other, company = seeded
    raw = _raw("signals-role", "https://acme.example/jobs/signals", "signals-v1")
    normalized = _normalized(
        "Part-time Platform Intern",
        raw.source_url,
        "Stipend ₹10,000/month\nDuration: 6 months\nPPO",
    ).model_copy(update={"category": category, "country": "IN", "meta": {"custom": "keep"}})
    opportunity, _ = _ingest(db_session, source.id, company.id, raw, normalized)
    if category == "hackathon":
        assert opportunity.meta == {"custom": "keep"}
        return
    assert opportunity.meta["compensation"]["max"] == 10000
    assert opportunity.meta["part_time"] is True
    assert opportunity.meta["custom"] == "keep"
    assert opportunity.meta.get("duration_months") == (6 if category == "internship" else None)
    monkeypatch.setattr(
        "pipeline.ingest.merge_role_signals", lambda *_args: pytest.fail("parsed unchanged content")
    )
    changed = set()
    repeated, is_new = _ingest(
        db_session, source.id, company.id, raw, normalized, changed_slugs=changed
    )
    assert repeated.id == opportunity.id and not is_new and not changed


def test_ingest_preserves_unstop_pay_on_update_and_revalidates_visible_signals(db_session, seeded):
    source, _other, company = seeded
    raw = _raw("signals-update", "https://acme.example/jobs/signals-update", "signals-v1")
    normalized = _normalized("Platform Intern", raw.source_url, "Stipend ₹10,000/month").model_copy(
        update={"country": "IN", "meta": {"compensation": {"unpaid": True, "source": "unstop"}}}
    )
    opportunity, _ = _ingest(db_session, source.id, company.id, raw, normalized)
    assert opportunity.meta["compensation"] == {"unpaid": True, "source": "unstop"}
    changed = set()
    updated, _ = _ingest(
        db_session,
        source.id,
        company.id,
        raw.model_copy(update={"content_hash": "signals-v2"}),
        normalized.model_copy(update={"meta": {"timing": "part_time"}}),
        changed_slugs=changed,
    )
    assert updated.meta["compensation"] == {"unpaid": True, "source": "unstop"}
    assert updated.meta["timing"] == "part_time"
    assert changed == {opportunity.slug}


def test_ingest_refreshes_text_pay_and_accepts_new_structured_unstop_pay(db_session, seeded):
    source, _other, company = seeded
    raw = _raw("signals-refresh", "https://acme.example/jobs/signals-refresh", "signals-v1")
    normalized = _normalized("Platform Intern", raw.source_url, "Stipend ₹10,000/month")
    opportunity, _ = _ingest(db_session, source.id, company.id, raw, normalized)
    assert opportunity.meta["compensation"]["max"] == 10000
    changed = set()
    updated, _ = _ingest(
        db_session,
        source.id,
        company.id,
        raw.model_copy(update={"content_hash": "signals-v2"}),
        normalized.model_copy(update={"description_raw": "Stipend ₹20,000/month"}),
        changed_slugs=changed,
    )
    assert updated.meta["compensation"]["max"] == 20000
    assert changed == {opportunity.slug}
    for version, maximum in ((3, 30000), (4, 40000)):
        structured = {
            "min": maximum,
            "max": maximum,
            "period": "month",
            "currency": "INR",
            "source": "unstop",
        }
        updated, _ = _ingest(
            db_session,
            source.id,
            company.id,
            raw.model_copy(update={"content_hash": f"signals-v{version}"}),
            normalized.model_copy(update={"meta": {"compensation": structured}}),
        )
        assert updated.meta["compensation"] == structured


def _source_role(
    source_slug: str, external_id: str, url: str, description: str = "Build products."
) -> tuple[RawListing, NormalizedListing]:
    raw = _raw(external_id, url).model_copy(update={"source_slug": source_slug})
    normalized = _normalized("Software Engineer, New Grad", url, description).model_copy(
        update={"source_slug": source_slug, "external_id": external_id, "category": "job"}
    )
    return raw, normalized


@pytest.mark.parametrize("longer_description", [False, True])
def test_secondary_content_change_preserves_primary_fields_and_enrichment(
    db_session, seeded, longer_description
):
    direct, board, company = seeded
    deadline = datetime(2027, 8, 31, tzinfo=UTC)
    direct_raw, direct_norm = _source_role("lever", "direct-role", "https://jobs.lever.co/acme/1")
    direct_norm = direct_norm.model_copy(
        update={
            "location": "London",
            "country": "GB",
            "is_remote": False,
            "posted_at": datetime(2026, 11, 1, tzinfo=UTC),
            "deadline": deadline,
            "deadline_confidence": "explicit",
            "meta": {"primary": True},
        }
    )
    opportunity, _ = _ingest(db_session, direct.id, company.id, direct_raw, direct_norm)
    board_raw, board_norm = _source_role("arbeitnow", "board-role", "https://arbeitnow.co.uk/1")
    board_norm = board_norm.model_copy(update={"location": "London", "country": "GB"})
    merged, is_new = _ingest(db_session, board.id, company.id, board_raw, board_norm)
    assert merged.id == opportunity.id and not is_new

    fields = (
        "apply_url",
        "primary_source",
        "title",
        "title_normalized",
        "category",
        "location",
        "country",
        "is_remote",
        "posted_at",
        "deadline",
        "deadline_confidence",
    )
    before = {field: getattr(opportunity, field) for field in fields}
    previous_meta = dict(opportunity.meta or {})
    previous_summary = opportunity.summary
    previous_skills = list(opportunity.skills)
    opportunity.embedding = [0.1] * 1536
    opportunity.embedding_model = "test-secondary-preserves-embedding"
    tag = models.Tag(slug="test-secondary-content-preserves-tag-x")
    db_session.add(tag)
    db_session.flush()
    db_session.add(models.OpportunityTag(opportunity_id=opportunity.id, tag_id=tag.id))
    db_session.flush()
    description = (
        "As a software engineer, you will build reliable Python and SQL services "
        "for our customers."
        if longer_description
        else "Short."
    )
    changed = set()
    seen = set()
    changed_raw = board_raw.model_copy(
        update={"content_hash": "changed-board-role", "raw_payload": {"version": 2}}
    )
    changed_norm = board_norm.model_copy(
        update={
            "title": "Campus Engineering Internship",
            "category": "internship",
            "location": "New York",
            "country": "US",
            "is_remote": True,
            "apply_url": "https://himalayas.app/jobs/other",
            "description_raw": description,
            "deadline": datetime(2028, 1, 1, tzinfo=UTC),
            "posted_at": datetime(2027, 1, 1, tzinfo=UTC),
            "deadline_confidence": "inferred",
            "meta": {"secondary": True, "job_offer": True},
        }
    )
    updated, is_new = _ingest(
        db_session,
        board.id,
        company.id,
        changed_raw,
        changed_norm,
        seen_opportunity_ids=seen,
        changed_slugs=changed,
    )
    db_session.flush()
    assert not is_new
    assert {field: getattr(updated, field) for field in fields} == before
    assert updated.meta == {
        **previous_meta,
        **({"summary_source": "extracted"} if longer_description else {}),
    }
    assert updated.embedding is not None
    assert updated.embedding_model == "test-secondary-preserves-embedding"
    assert db_session.get(models.OpportunityTag, (updated.id, tag.id)) is not None
    assert seen == {updated.id}
    assert changed == ({updated.slug} if longer_description else set())
    if longer_description:
        assert updated.description_raw == description
        assert "Python" in updated.skills
        assert updated.summary != previous_summary
    else:
        assert updated.description_raw == direct_norm.description_raw
        assert updated.skills == previous_skills
        assert updated.summary == previous_summary
    stored_raw = db_session.scalar(
        select(models.RawListing).where(
            models.RawListing.source_id == board.id,
            models.RawListing.external_id == board_raw.external_id,
        )
    )
    assert stored_raw.content_hash == changed_raw.content_hash
    assert stored_raw.raw_payload == {"version": 2}
    assert stored_raw.processed is True
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(models.OpportunitySource)
            .where(models.OpportunitySource.opportunity_id == updated.id)
        )
        == 2
    )


@pytest.mark.parametrize("primary_source", [None, "lever"])
def test_primary_content_change_still_refreshes_canonical_fields(
    db_session, seeded, primary_source
):
    direct, _board, company = seeded
    raw, normalized = _source_role("lever", "primary-role", "https://jobs.lever.co/acme/primary")
    opportunity, _ = _ingest(db_session, direct.id, company.id, raw, normalized)
    opportunity.primary_source = primary_source
    opportunity.embedding = [0.1] * 1536
    opportunity.embedding_model = "test-primary-refresh"
    tag = models.Tag(slug="test-primary-content-clears-tag-x")
    db_session.add(tag)
    db_session.flush()
    db_session.add(models.OpportunityTag(opportunity_id=opportunity.id, tag_id=tag.id))
    db_session.flush()
    updates = {
        "title": "Software Engineer Intern",
        "location": "Toronto",
        "country": "CA",
        "category": "internship",
        "is_remote": True,
        "deadline": datetime(2027, 9, 1, tzinfo=UTC),
        "apply_url": "https://jobs.lever.co/acme/primary/apply",
        "posted_at": datetime(2026, 11, 2, tzinfo=UTC),
        "deadline_confidence": "explicit",
    }
    changed = set()
    updated, is_new = _ingest(
        db_session,
        direct.id,
        company.id,
        raw.model_copy(update={"content_hash": "primary-v2"}),
        normalized.model_copy(update=updates),
        changed_slugs=changed,
    )
    db_session.flush()
    assert not is_new and updated.id == opportunity.id
    assert {field: getattr(updated, field) for field in updates} == updates
    assert updated.embedding is None
    assert updated.embedding_model is None
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(models.OpportunityTag)
            .where(models.OpportunityTag.opportunity_id == updated.id)
        )
        == 0
    )
    assert changed == {updated.slug}


def test_direct_dedup_merge_upgrades_board_link_and_later_board_change_cannot_undo_it(
    db_session, seeded
):
    board, direct, company = seeded
    board_raw, board_norm = _source_role("arbeitnow", "board-role", "https://arbeitnow.com/1")
    opportunity, _ = _ingest(db_session, board.id, company.id, board_raw, board_norm)
    direct_raw, direct_norm = _source_role(
        "ashby", "direct-role", "https://jobs.ashbyhq.com/acme/1"
    )
    changed = set()
    upgraded, is_new = _ingest(
        db_session, direct.id, company.id, direct_raw, direct_norm, changed_slugs=changed
    )
    db_session.flush()
    assert not is_new and upgraded.id == opportunity.id
    assert upgraded.apply_url == direct_norm.apply_url
    assert upgraded.primary_source == "ashby"
    assert changed == {upgraded.slug}
    changed.clear()
    repeated, is_new = _ingest(
        db_session,
        board.id,
        company.id,
        board_raw.model_copy(update={"content_hash": "board-v2"}),
        board_norm.model_copy(
            update={
                "title": "New Graduate Internship",
                "category": "internship",
                "location": "Elsewhere",
                "deadline": datetime(2028, 1, 1, tzinfo=UTC),
            }
        ),
        changed_slugs=changed,
    )
    assert not is_new and repeated.id == upgraded.id
    assert repeated.apply_url == direct_norm.apply_url
    assert repeated.primary_source == "ashby"
    assert repeated.title == direct_norm.title
    assert repeated.category == "job"
    assert repeated.location is None and repeated.deadline is None
    assert changed == set()


def test_another_job_board_does_not_replace_the_canonical_link(db_session, seeded):
    first, second, company = seeded
    raw, normalized = _source_role("arbeitnow", "first-board", "https://arbeitnow.com/1")
    opportunity, _ = _ingest(db_session, first.id, company.id, raw, normalized)
    other_raw, other_norm = _source_role(
        "himalayas", "second-board", "https://himalayas.app/jobs/1"
    )
    changed = set()
    merged, is_new = _ingest(
        db_session, second.id, company.id, other_raw, other_norm, changed_slugs=changed
    )
    assert not is_new and merged.id == opportunity.id
    assert merged.apply_url == normalized.apply_url
    assert merged.primary_source == "arbeitnow"
    assert changed == set()


@pytest.mark.parametrize("content_changed", [False, True])
def test_direct_identity_path_upgrades_a_board_link_even_with_unchanged_raw(
    db_session, seeded, content_changed
):
    direct, _board, company = seeded
    raw, normalized = _source_role("lever", "identity-role", "https://jobs.lever.co/acme/identity")
    opportunity, _ = _ingest(db_session, direct.id, company.id, raw, normalized)
    opportunity.apply_url = "https://arbeitnow.co.uk/identity"
    opportunity.primary_source = "arbeitnow"
    db_session.flush()
    changed = set()
    updated, is_new = _ingest(
        db_session,
        direct.id,
        company.id,
        raw.model_copy(update={"content_hash": "identity-v2"}) if content_changed else raw,
        normalized,
        changed_slugs=changed,
    )
    assert not is_new and updated.id == opportunity.id
    assert updated.apply_url == normalized.apply_url
    assert updated.primary_source == "lever"
    assert changed == {updated.slug}


def test_direct_slug_soft_merge_upgrades_a_board_link(db_session, seeded):
    direct, _board, company = seeded
    raw, normalized = _source_role("lever", "pruned-direct", "https://jobs.lever.co/acme/pruned")
    opportunity, _ = _ingest(db_session, direct.id, company.id, raw, normalized)
    opportunity.apply_url = "https://arbeitnow.com/pruned"
    opportunity.primary_source = "arbeitnow"
    db_session.execute(
        models.OpportunitySource.__table__.update()
        .where(models.OpportunitySource.opportunity_id == opportunity.id)
        .values(raw_listing_id=None)
    )
    db_session.execute(
        models.RawListing.__table__.delete().where(
            models.RawListing.source_id == direct.id,
            models.RawListing.external_id == raw.external_id,
        )
    )
    db_session.flush()
    changed = set()
    updated, is_new = _ingest(
        db_session,
        direct.id,
        company.id,
        raw.model_copy(update={"content_hash": "pruned-v2"}),
        normalized.model_copy(update={"location": "London"}),
        changed_slugs=changed,
    )
    assert not is_new and updated.id == opportunity.id
    assert updated.apply_url == normalized.apply_url
    assert updated.primary_source == "lever"
    assert changed == {updated.slug}


def test_identity_path_fills_a_missing_posting_date_but_never_restamps(
    db_session: Session, seeded
) -> None:
    """An adapter that learns to read a date the payload always carried (same raw
    hash) fills posted_at on the next crawl; a later different date is ignored."""
    source_a, _source_b, company = seeded
    url = "https://acme.example/jobs/dated-later"
    raw = _raw("dated-later", url)
    undated = _normalized("Backend Intern", url)

    opportunity, created = _ingest(db_session, source_a.id, company.id, raw, undated)
    assert created and opportunity.posted_at is None

    posted = datetime(2026, 11, 1, 9, tzinfo=UTC)
    opportunity, created = _ingest(
        db_session,
        source_a.id,
        company.id,
        raw,
        undated.model_copy(update={"posted_at": posted}),
    )
    assert not created and opportunity.posted_at == posted

    opportunity, _ = _ingest(
        db_session,
        source_a.id,
        company.id,
        raw,
        undated.model_copy(update={"posted_at": posted + timedelta(days=5)}),
    )
    assert opportunity.posted_at == posted
