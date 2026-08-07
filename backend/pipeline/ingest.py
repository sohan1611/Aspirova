"""Ingest pipeline: adapter output -> raw_listings -> dedup -> canonical
opportunities, with full provenance (Doc 03 sec 3.3-3.5, Doc 04 sec 7 & 9).
Idempotent at every stage - re-running the same raw listing makes zero new
rows (Doc 04 sec 9: "re-running a crawl must not create duplicate canonical
opps").

Set-based bulk refactor (Doc handoffs/PHASE-2-HANDOFF.md sec 2/5, "Lever
1"): the original per-listing implementation issued ~5 serial DB round
trips PER LISTING (existing raw_listing lookup, existing opportunity
lookup, dedup fuzzy-match query, slug-collision check, provenance lookup) -
at 12 companies/~2,300 listings this already cost 12m45s against the
high-latency GH-Actions-to-Supabase link, near the 25-minute timeout (Doc
handoffs/PHASE-1-REPORT.md sec 4a); 3-5x the source count would blow it.

`load_board_state()` now does ONE bulk read each of a source's existing
raw_listings, this company's opportunities (any status - the identity and
slug paths below both match regardless of status, same as the original
per-listing code), and their provenance links, up front. `ingest_one()`
resolves the identity fast-path and slug-collision fallback via in-memory
dict lookups against that state instead of per-listing queries.

The one deliberate exception: the fuzzy dedup match
(pipeline/dedup.py's find_matching_opportunity, backed by Postgres's
pg_trgm similarity()) still issues one query per genuinely-new listing
that reaches it. Reimplementing trigram similarity in Python risks
silently diverging from the exact, carefully-tuned-against-real-data
threshold behavior documented in dedup.py (an earlier 0.6 threshold looked
fine on synthetic data and produced real false merges there - see that
file's "THRESHOLD HISTORY"). This path is the minority case on any
steady-state re-crawl (it only fires for brand-new postings, not the
identity-matched majority a 2-hourly re-crawl mostly sees - SQLAlchemy's
default autoflush keeps it consistent with any not-yet-flushed new
opportunities from earlier in the same batch), so it does not reintroduce
the round-trip-per-listing problem this refactor exists to fix.
"""

import hashlib
import re
from dataclasses import dataclass, field

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from core import models
from core.adapters import NormalizedListing, RawListing
from core.textclean import fix_text
from pipeline.dedup import find_matching_opportunity
from pipeline.location_country import derive_country
from pipeline.normalize import normalize_title
from pipeline.skills import extract_opportunity_skills


def _slugify(text: str) -> str:
    slug = text.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return re.sub(r"-+", "-", slug).strip("-")


def _make_opportunity_slug(company_name: str, title: str, raw: RawListing) -> str:
    base = _slugify(f"{company_name}-{title}")[:80] or "opportunity"
    # Disambiguator derived from the listing that CREATED this opportunity -
    # never recomputed on a later dedup merge, so existing slugs/links never
    # change once set (Doc 03 sec 3.4).
    disambiguator = hashlib.sha256(f"{raw.external_id}|{raw.source_url}".encode()).hexdigest()[:8]
    return f"{base}-{disambiguator}"


@dataclass
class BoardState:
    """Everything ingest_one() needs, pre-fetched once per board instead
    of re-queried per listing."""

    raw_by_external_id: dict[str, models.RawListing] = field(default_factory=dict)
    opportunities_by_id: dict[int, models.Opportunity] = field(default_factory=dict)
    opportunities_by_slug: dict[str, models.Opportunity] = field(default_factory=dict)
    provenance_by_key: dict[tuple[int, int, str], models.OpportunitySource] = field(
        default_factory=dict
    )


def load_board_state(session: Session, source_id: int, company_id: int | None) -> BoardState:
    raw_rows = session.scalars(
        select(models.RawListing).where(models.RawListing.source_id == source_id)
    ).all()
    raw_by_external_id = {r.external_id: r for r in raw_rows}

    opportunities_by_id: dict[int, models.Opportunity] = {}
    opportunities_by_slug: dict[str, models.Opportunity] = {}
    if company_id is not None:
        opportunities = session.scalars(
            select(models.Opportunity).where(models.Opportunity.company_id == company_id)
        ).all()
        for opportunity in opportunities:
            opportunities_by_id[opportunity.id] = opportunity
            opportunities_by_slug[opportunity.slug] = opportunity

    provenance_by_key: dict[tuple[int, int, str], models.OpportunitySource] = {}
    if opportunities_by_id:
        links = session.scalars(
            select(models.OpportunitySource).where(
                models.OpportunitySource.opportunity_id.in_(opportunities_by_id.keys())
            )
        ).all()
        for link in links:
            provenance_by_key[(link.opportunity_id, link.source_id, link.source_url or "")] = link

    return BoardState(
        raw_by_external_id, opportunities_by_id, opportunities_by_slug, provenance_by_key
    )


def _ensure_provenance(
    session: Session,
    board_state: BoardState,
    opportunity: models.Opportunity,
    source_id: int,
    raw: RawListing,
    raw_row: models.RawListing,
    *,
    is_primary: bool,
) -> None:
    key = (opportunity.id, source_id, raw.source_url or "")
    existing_link = board_state.provenance_by_key.get(key)
    if existing_link is None:
        existing_link = session.scalar(
            select(models.OpportunitySource).where(
                models.OpportunitySource.opportunity_id == opportunity.id,
                models.OpportunitySource.source_id == source_id,
                func.coalesce(models.OpportunitySource.source_url, "") == key[2],
            )
        )
        if existing_link is None:
            link = models.OpportunitySource(
                opportunity_id=opportunity.id,
                source_id=source_id,
                source_url=raw.source_url,
                raw_listing_id=raw_row.id,
                is_primary=is_primary,
            )
            session.add(link)
            board_state.provenance_by_key[key] = link
            return
        board_state.provenance_by_key[key] = existing_link

    if existing_link.raw_listing_id != raw_row.id:
        # Keep provenance pointing at the current raw_listings row - it can
        # go stale if raw_listings was pruned and a fresh row created on a
        # later crawl (Doc 03 sec 8 retention).
        existing_link.raw_listing_id = raw_row.id


def ingest_one(
    session: Session,
    board_state: BoardState,
    source_id: int,
    company_id: int | None,
    raw: RawListing,
    normalized: NormalizedListing,
    seen_opportunity_ids: set[int] | None = None,
    changed_slugs: set[str] | None = None,
) -> tuple[models.Opportunity, bool]:
    """Returns (opportunity, is_new_canonical_opportunity).

    Idempotent: a repeat call with byte-identical raw content (same
    content_hash) is a near-no-op - only last_seen_at is touched.
    """

    def mark_seen(opportunity: models.Opportunity) -> None:
        if seen_opportunity_ids is not None and opportunity.id is not None:
            seen_opportunity_ids.add(opportunity.id)
        else:
            opportunity.last_seen_at = func.now()

    normalized = normalized.model_copy(
        update={
            "title": fix_text(normalized.title),
            "company_name": fix_text(normalized.company_name),
            "location": fix_text(normalized.location),
            "description_raw": fix_text(normalized.description_raw),
        }
    )
    country = derive_country(normalized.location)
    raw_row = board_state.raw_by_external_id.get(raw.external_id)

    if raw_row is not None and raw_row.opportunity_id is not None:
        # Identity fast-path: this raw listing is already linked to a
        # canonical opportunity by (source_id, external_id) identity - the
        # strongest possible match, stronger than fuzzy dedup. Re-link and
        # refresh directly; never re-run dedup or risk creating a new
        # opportunity here.
        #
        # This is the fix for a real production bug (confirmed live: 2 of
        # ~2,321 listings in GH Actions run 28420810872): when a listing's
        # CONTENT changes (e.g. its location is edited) but raw_row already
        # points at an opportunity, the old code fell through to
        # find_matching_opportunity() - whose exact-location filter
        # correctly refuses to self-match a listing whose location just
        # changed, returning None - which then tried to INSERT a new
        # opportunity at the SAME deterministic slug (the hash suffix is
        # derived from external_id|source_url, neither of which changed),
        # raising opportunities_slug_key.
        opportunity = board_state.opportunities_by_id.get(raw_row.opportunity_id)
        if opportunity is None:
            # Defensive fallback only - the bulk pre-fetch loads every
            # opportunity for this company, so this should not happen in
            # practice; a direct lookup keeps correctness if it ever does.
            opportunity = session.get(models.Opportunity, raw_row.opportunity_id)
        content_changed = raw_row.content_hash != raw.content_hash

        if content_changed:
            raw_row.content_hash = raw.content_hash
            raw_row.raw_payload = raw.raw_payload
            if len(normalized.description_raw or "") > len(opportunity.description_raw or ""):
                opportunity.description_raw = normalized.description_raw
            opportunity.title = normalized.title
            opportunity.title_normalized = normalize_title(normalized.title)
            opportunity.location = normalized.location
            opportunity.country = country
            opportunity.is_remote = normalized.is_remote
            opportunity.apply_url = normalized.apply_url
            opportunity.category = normalized.category
            opportunity.posted_at = normalized.posted_at
            opportunity.deadline = normalized.deadline
            opportunity.meta = normalized.meta
            opportunity.deadline_confidence = normalized.deadline_confidence
            opportunity.skills = extract_opportunity_skills(
                normalized.title,
                opportunity.description_raw or "",
                company_name=normalized.company_name,
            )
            opportunity.summary = None
            opportunity.embedding = None
            opportunity.embedding_model = None
            session.execute(
                delete(models.OpportunityTag).where(
                    models.OpportunityTag.opportunity_id == opportunity.id
                )
            )
            if changed_slugs is not None:
                changed_slugs.add(opportunity.slug)

        mark_seen(opportunity)
        raw_row.processed = True

        _ensure_provenance(
            session, board_state, opportunity, source_id, raw, raw_row, is_primary=False
        )

        return opportunity, False

    if raw_row is None:
        raw_row = models.RawListing(
            source_id=source_id,
            source_url=raw.source_url,
            external_id=raw.external_id,
            content_hash=raw.content_hash,
            raw_payload=raw.raw_payload,
        )
        session.add(raw_row)
        board_state.raw_by_external_id[raw.external_id] = raw_row
    else:
        raw_row.content_hash = raw.content_hash
        raw_row.raw_payload = raw.raw_payload

    title_normalized = normalize_title(normalized.title)
    # Real DB query, deliberately not batched away - see module docstring.
    # Autoflush keeps this consistent with any new opportunity created
    # earlier in the same board's batch, even though it isn't committed yet.
    match = find_matching_opportunity(
        session, company_id, title_normalized, location=normalized.location
    )

    if match is not None:
        if len(normalized.description_raw or "") > len(match.description_raw or ""):
            match.description_raw = normalized.description_raw
            match.skills = extract_opportunity_skills(
                match.title,
                match.description_raw or "",
                company_name=normalized.company_name,
            )
        mark_seen(match)
        opportunity, is_new = match, False
    else:
        slug = _make_opportunity_slug(normalized.company_name, normalized.title, raw)
        existing_by_slug = board_state.opportunities_by_slug.get(slug)
        if existing_by_slug is not None:
            # Safety net for the variant where raw_listings was pruned
            # (Doc 03 sec 8 retention policy) but the opportunity it
            # originally created still exists: there's no raw_row to
            # identity-match through above, but the deterministic slug is
            # still a reliable merge key. Soft-merge instead of a hard
            # INSERT failure.
            opportunity = existing_by_slug
            if len(normalized.description_raw or "") > len(opportunity.description_raw or ""):
                opportunity.description_raw = normalized.description_raw
                opportunity.skills = extract_opportunity_skills(
                    opportunity.title,
                    opportunity.description_raw or "",
                    company_name=normalized.company_name,
                )
            mark_seen(opportunity)
            is_new = False
        else:
            opportunity = models.Opportunity(
                slug=slug,
                company_id=company_id,
                title=normalized.title,
                title_normalized=title_normalized,
                category=normalized.category,
                skills=extract_opportunity_skills(
                    normalized.title,
                    normalized.description_raw or "",
                    company_name=normalized.company_name,
                ),
                primary_source=raw.source_slug,
                location=normalized.location,
                country=country,
                is_remote=normalized.is_remote,
                description_raw=normalized.description_raw,
                apply_url=normalized.apply_url,
                posted_at=normalized.posted_at,
                deadline=normalized.deadline,
                meta=normalized.meta,
                deadline_confidence=normalized.deadline_confidence,
            )
            session.add(opportunity)
            is_new = True

    if is_new and changed_slugs is not None:
        changed_slugs.add(opportunity.slug)

    session.flush()  # need opportunity.id for the FKs below
    board_state.opportunities_by_id[opportunity.id] = opportunity
    board_state.opportunities_by_slug[opportunity.slug] = opportunity

    raw_row.opportunity_id = opportunity.id
    raw_row.processed = True

    _ensure_provenance(
        session, board_state, opportunity, source_id, raw, raw_row, is_primary=is_new
    )

    return opportunity, is_new
