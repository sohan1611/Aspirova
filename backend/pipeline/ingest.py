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

# `content_hash` answers "did the upstream payload change at all?"; the
# comparison in `ingest_one` answers "would the rendered page look different?"
# Only the latter should trigger a regeneration.

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from core import models
from core.adapters import NormalizedListing, RawListing
from core.destination import DIRECT_SOURCE_SLUGS, classify_destination
from core.listing_safety import has_manual_closure, safety_flag
from core.summarise import summarise_description
from core.textclean import fix_multiline_text, fix_text
from pipeline.competition_signals import merge_competition_signals
from pipeline.dedup import find_matching_opportunity
from pipeline.location_country import derive_country
from pipeline.normalize import normalize_title
from pipeline.role_signals import merge_role_signals
from pipeline.skills import extract_opportunity_skills

RAW_LISTING_EXTERNAL_ID_CHUNK_SIZE = 500
ROLE_DISPLAY_KEYS = ("compensation", "duration_months", "part_time", "job_offer", "timing")


def _listing_meta(
    normalized: NormalizedListing, country: str | None, existing: dict | None = None
) -> dict | None:
    protected = {
        "safety",
        "closed_reason",
        "duplicate_of",
        "corrections",
        "deadline_override",
        "company_override",
        "alert_reopened_after",
        "alert_reopened_at",
    }
    incoming = {k: v for k, v in _copy_meta(normalized.meta).items() if k not in protected}
    meta = {**_copy_meta(existing), **incoming}
    if normalized.category not in {"internship", "job"}:
        # Refresh source-owned competition signals as before; retain only the
        # founder-owned keys from prior metadata.
        meta = {**incoming, **{k: v for k, v in _copy_meta(existing).items() if k in protected}}
        return merge_competition_signals(meta, normalized.category) or None
    old_pay = (existing or {}).get("compensation")
    incoming_pay = meta.get("compensation")
    incoming_unstop = isinstance(incoming_pay, dict) and incoming_pay.get("source") == "unstop"
    if isinstance(old_pay, dict) and old_pay.get("source") == "unstop" and not incoming_unstop:
        meta["compensation"] = old_pay
    return (
        merge_role_signals(
            meta, normalized.title, normalized.description_raw, normalized.category, country
        )
        or None
    )


def _role_display_meta(meta: dict | None) -> dict:
    return {key: (meta or {}).get(key) for key in ROLE_DISPLAY_KEYS}


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


def _copy_meta(meta: dict | None) -> dict:
    return dict(meta) if isinstance(meta, dict) else {}


def _summary_source(meta: dict | None) -> str | None:
    if not isinstance(meta, dict):
        return None
    value = meta.get("summary_source")
    return value if isinstance(value, str) else None


def _meta_with_summary_source(meta: dict | None, source: str) -> dict:
    next_meta = _copy_meta(meta)
    next_meta["summary_source"] = source
    return next_meta


def _meta_without_summary_source(meta: dict | None) -> dict | None:
    next_meta = _copy_meta(meta)
    next_meta.pop("summary_source", None)
    return next_meta or None


def _extracted_summary_and_meta(
    *,
    description: str | None,
    title: str | None,
    meta: dict | None,
) -> tuple[str | None, dict | None]:
    summary = summarise_description(description, title=title)
    if summary is None:
        return None, _meta_without_summary_source(meta)
    return summary, _meta_with_summary_source(meta, "extracted")


def _refresh_extracted_summary(
    opportunity: models.Opportunity,
    *,
    meta: dict | None,
) -> None:
    # Extracted summaries keep cards useful while all but 45 active rows already
    # have long descriptions. They are placeholders only; an AI summary must
    # never be replaced by this deterministic fallback.
    if _summary_source(opportunity.meta) == "ai":
        opportunity.meta = _meta_with_summary_source(meta, "ai")
        return

    opportunity.summary, opportunity.meta = _extracted_summary_and_meta(
        description=opportunity.description_raw,
        title=opportunity.title,
        meta=meta,
    )


@dataclass
class BoardState:
    """Everything ingest_one() needs, pre-fetched once per board instead
    of re-queried per listing."""

    locked_transaction: object | None = field(default=None, init=False, repr=False)
    locked_ids: set[int] = field(default_factory=set, init=False, repr=False)
    raw_by_external_id: dict[str, models.RawListing] = field(default_factory=dict)
    opportunities_by_id: dict[int, models.Opportunity] = field(default_factory=dict)
    opportunities_by_slug: dict[str, models.Opportunity] = field(default_factory=dict)
    provenance_by_key: dict[tuple[int, int, str], models.OpportunitySource] = field(
        default_factory=dict
    )


def load_source_raw_listings(
    session: Session,
    source_id: int,
    external_ids: Iterable[str] | None = None,
) -> dict[str, models.RawListing]:
    query = select(models.RawListing).where(models.RawListing.source_id == source_id)
    if external_ids is None:
        raw_rows = session.scalars(query).all()
        return {raw.external_id: raw for raw in raw_rows}

    raw_by_external_id: dict[str, models.RawListing] = {}
    unique_external_ids = list(dict.fromkeys(external_ids))
    for start in range(0, len(unique_external_ids), RAW_LISTING_EXTERNAL_ID_CHUNK_SIZE):
        chunk = unique_external_ids[start : start + RAW_LISTING_EXTERNAL_ID_CHUNK_SIZE]
        raw_rows = session.scalars(query.where(models.RawListing.external_id.in_(chunk))).all()
        raw_by_external_id.update({raw.external_id: raw for raw in raw_rows})
    return raw_by_external_id


def claim_legacy_raw_listings(
    session: Session,
    source_id: int,
    board_state: BoardState,
    legacy_by_new_id: dict[str, str],
) -> int:
    """Rename only legacy rows linked to this board's company, in listing order."""
    candidates = {
        new_id: legacy_id
        for new_id, legacy_id in legacy_by_new_id.items()
        if new_id not in board_state.raw_by_external_id and "|" not in legacy_id
    }
    legacy_rows = load_source_raw_listings(session, source_id, candidates.values())
    claimed = 0
    for new_id, legacy_id in candidates.items():
        row = legacy_rows.get(legacy_id)
        if (
            row is None
            or row.opportunity_id is None
            or row.opportunity_id not in board_state.opportunities_by_id
        ):
            continue
        row.external_id = new_id
        board_state.raw_by_external_id[new_id] = row
        # Two listings may report the same old identity. The first owns it.
        del legacy_rows[legacy_id]
        claimed += 1
    return claimed


def load_board_state(
    session: Session,
    source_id: int,
    company_id: int | None,
    raw_by_external_id: dict[str, models.RawListing] | None = None,
) -> BoardState:
    if raw_by_external_id is None:
        raw_by_external_id = load_source_raw_listings(session, source_id)

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


def _lock_existing_opportunity(
    session: Session,
    board_state: BoardState,
    opportunity_id: int,
) -> models.Opportunity:
    """Lock and refresh ONE opportunity right before a canonical write.

    A founder may correct a row after the board was loaded or between batch
    commits (TRUST-05). Re-reading the row under FOR UPDATE in the writing
    transaction means stale ORM state can never erase that correction.

    Only the row about to be written is locked. Locking every board row once
    per transaction re-read the whole board after every 25-listing batch
    commit: O(N^2 / 25) full rows (description, embedding), about 36 x 900
    for databricks, which took 652 s in crawl 44703841666 (2026-11-20) and
    pushed the ATS step past its budget. Callers skip the lock entirely when
    an unchanged listing writes nothing canonical.
    """
    transaction = session.get_transaction()
    if board_state.locked_transaction is not transaction:
        board_state.locked_ids.clear()
    if opportunity_id not in board_state.locked_ids:
        row = session.scalar(
            select(models.Opportunity)
            .where(models.Opportunity.id == opportunity_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is not None:
            board_state.opportunities_by_id[row.id] = row
            board_state.opportunities_by_slug[row.slug] = row
            board_state.locked_ids.add(row.id)
        board_state.locked_transaction = session.get_transaction()
    opportunity = board_state.opportunities_by_id.get(opportunity_id)
    if opportunity is None:
        raise ValueError(f"Linked opportunity no longer exists: {opportunity_id}")
    return opportunity


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


def _would_upgrade_direct_apply_url(opportunity: models.Opportunity, raw: RawListing) -> bool:
    return (
        raw.source_slug in DIRECT_SOURCE_SLUGS
        and classify_destination(opportunity.apply_url, None).kind == "job_board"
    )


def _blocks_canonical_writes(opportunity: models.Opportunity) -> bool:
    return (
        safety_flag(opportunity) is not None
        or opportunity.status == "withdrawn"
        or has_manual_closure(opportunity)
    )


def _content_change_diff(
    opportunity: models.Opportunity,
    normalized: NormalizedListing,
    country: str | None,
    raw: RawListing,
) -> set[str]:
    """Canonical fields a changed raw payload would actually change, without writing.

    MUST mirror the `if content_changed:` block in ingest_one's identity branch.
    test_content_change_diff_mirrors_the_write_path pins the two together.

    A raw payload can change while nothing a student sees does. On 2026-11-19
    Greenhouse re-stamped `updated_at` on whole boards (databricks 862 jobs in
    one hour), every listing's hash changed, and each one paid the full write:
    lock, tag delete, re-extraction, embedding reset. That pushed the ATS step
    past its budget (crawl 44703841666).
    """
    description = opportunity.description_raw
    if len(normalized.description_raw or "") > len(opportunity.description_raw or ""):
        description = normalized.description_raw
    values: dict[str, object] = {}
    if opportunity.primary_source is None or opportunity.primary_source == raw.source_slug:
        title = normalized.title
        values.update(
            title=title,
            title_normalized=normalize_title(title),
            location=normalized.location,
            country=country,
            is_remote=normalized.is_remote,
            apply_url=normalized.apply_url,
            category=normalized.category,
            posted_at=normalized.posted_at,
            description_raw=description,
            skills=extract_opportunity_skills(
                title, description or "", company_name=normalized.company_name
            ),
        )
        if "deadline_override" not in (opportunity.meta or {}):
            values.update(
                deadline=normalized.deadline,
                deadline_confidence=normalized.deadline_confidence,
            )
        meta = _listing_meta(normalized, country, opportunity.meta)
    elif description != opportunity.description_raw:
        title = opportunity.title
        values.update(
            description_raw=description,
            skills=extract_opportunity_skills(
                title, description or "", company_name=normalized.company_name
            ),
        )
        meta = opportunity.meta
    else:
        return set()
    # Exactly what _refresh_extracted_summary would store.
    if _summary_source(opportunity.meta) == "ai":
        values["meta"] = _meta_with_summary_source(meta, "ai")
    else:
        values["summary"], values["meta"] = _extracted_summary_and_meta(
            description=description, title=title, meta=meta
        )

    def differs(field: str, current: object, value: object) -> bool:
        if field == "skills":  # extraction order is not a change (changed_slugs agrees)
            return sorted(current or []) != sorted(value or [])
        return current != value

    return {
        field
        for field, value in values.items()
        if differs(field, getattr(opportunity, field), value)
    }


def _fills_posted_at(
    opportunity: models.Opportunity, raw: RawListing, normalized: NormalizedListing
) -> bool:
    return (
        opportunity.posted_at is None
        and normalized.posted_at is not None
        and opportunity.primary_source in (None, raw.source_slug)
    )


def _upgrade_direct_apply_url(
    opportunity: models.Opportunity,
    raw: RawListing,
    normalized: NormalizedListing,
    changed_slugs: set[str] | None,
) -> None:
    if _would_upgrade_direct_apply_url(opportunity, raw):
        opportunity.apply_url = normalized.apply_url
        opportunity.primary_source = raw.source_slug
        if changed_slugs is not None:
            changed_slugs.add(opportunity.slug)


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
            "description_raw": fix_multiline_text(normalized.description_raw),
        }
    )
    country = normalized.country or derive_country(normalized.location)
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
        cached = board_state.opportunities_by_id.get(raw_row.opportunity_id)
        if cached is None:
            # Rare: the linked row is outside this board's company cache.
            cached = _lock_existing_opportunity(session, board_state, raw_row.opportunity_id)
        if _blocks_canonical_writes(cached):
            # Blocked rows (safety, withdrawn, manual closure) are left alone
            # and not marked seen, exactly as in the locked re-check below.
            if not raw_row.processed:
                raw_row.processed = True
            _ensure_provenance(
                session, board_state, cached, source_id, raw, raw_row, is_primary=False
            )
            return cached, False
        payload_changed = raw_row.content_hash != raw.content_hash
        diff = _content_change_diff(cached, normalized, country, raw) if payload_changed else set()
        if diff <= {"posted_at"} and not _would_upgrade_direct_apply_url(cached, raw):
            # Nothing a student sees changes, so no lock and no per-listing
            # SELECT: last_seen_at is stamped in bulk through seen ids, and the
            # raw row plus a moved or missing posted_at flush as narrow UPDATEs
            # of only those columns (batched at the next commit), which cannot
            # overwrite a founder correction to any other field.
            if payload_changed:
                raw_row.content_hash = raw.content_hash
                raw_row.raw_payload = raw.raw_payload
            if "posted_at" in diff or _fills_posted_at(cached, raw, normalized):
                cached.posted_at = normalized.posted_at
            mark_seen(cached)
            if not raw_row.processed:
                raw_row.processed = True
            _ensure_provenance(
                session, board_state, cached, source_id, raw, raw_row, is_primary=False
            )
            return cached, False
        # A canonical write follows: re-read this one row under lock and
        # re-check, so a correction made since the board loaded is kept.
        opportunity = _lock_existing_opportunity(session, board_state, raw_row.opportunity_id)
        if _blocks_canonical_writes(opportunity):
            raw_row.processed = True
            _ensure_provenance(
                session, board_state, opportunity, source_id, raw, raw_row, is_primary=False
            )
            return opportunity, False
        _upgrade_direct_apply_url(opportunity, raw, normalized, changed_slugs)
        content_changed = raw_row.content_hash != raw.content_hash

        if content_changed:
            previous_user_visible_fields = {
                "title": opportunity.title,
                "location": opportunity.location,
                "country": opportunity.country,
                "is_remote": opportunity.is_remote,
                "apply_url": opportunity.apply_url,
                "category": opportunity.category,
                "deadline": opportunity.deadline,
                "description_raw": opportunity.description_raw,
                "summary": opportunity.summary,
                "role_meta": _role_display_meta(opportunity.meta),
                "skills": sorted(opportunity.skills or []),
            }
            # Deliberately exclude title_normalized (derived from title); non-display
            # meta and deadline_confidence; posted_at
            # (the upstream can re-timestamp it without a listing change).
            raw_row.content_hash = raw.content_hash
            raw_row.raw_payload = raw.raw_payload
            if opportunity.primary_source is None or opportunity.primary_source == raw.source_slug:
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
                if "deadline_override" not in (opportunity.meta or {}):
                    opportunity.deadline = normalized.deadline
                    opportunity.deadline_confidence = normalized.deadline_confidence
                opportunity.skills = extract_opportunity_skills(
                    normalized.title,
                    opportunity.description_raw or "",
                    company_name=normalized.company_name,
                )
                opportunity.embedding = None
                opportunity.embedding_model = None
                _refresh_extracted_summary(
                    opportunity, meta=_listing_meta(normalized, country, opportunity.meta)
                )
                session.execute(
                    delete(models.OpportunityTag).where(
                        models.OpportunityTag.opportunity_id == opportunity.id
                    )
                )
            elif len(normalized.description_raw or "") > len(opportunity.description_raw or ""):
                opportunity.description_raw = normalized.description_raw
                opportunity.skills = extract_opportunity_skills(
                    opportunity.title,
                    opportunity.description_raw or "",
                    company_name=normalized.company_name,
                )
                _refresh_extracted_summary(opportunity, meta=opportunity.meta)
            current_user_visible_fields = {
                "title": opportunity.title,
                "location": opportunity.location,
                "country": opportunity.country,
                "is_remote": opportunity.is_remote,
                "apply_url": opportunity.apply_url,
                "category": opportunity.category,
                "deadline": opportunity.deadline,
                "description_raw": opportunity.description_raw,
                "summary": opportunity.summary,
                "role_meta": _role_display_meta(opportunity.meta),
                "skills": sorted(opportunity.skills or []),
            }
            if (
                changed_slugs is not None
                and previous_user_visible_fields != current_user_visible_fields
            ):
                changed_slugs.add(opportunity.slug)

        # Fill a missing posting date from the primary source even when the raw
        # payload is unchanged (an adapter learned to read the source's date), but
        # never overwrite one: upstreams re-stamp unchanged listings. Not added to
        # changed_slugs, so a first crawl that dates many rows cannot start a burst
        # of page revalidations; pages pick the date up on their normal ISR cycle.
        if (
            opportunity.posted_at is None
            and normalized.posted_at is not None
            and opportunity.primary_source in (None, raw.source_slug)
        ):
            opportunity.posted_at = normalized.posted_at

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
        match = _lock_existing_opportunity(session, board_state, match.id)
        if (
            safety_flag(match) is not None
            or match.status == "withdrawn"
            or has_manual_closure(match)
        ):
            raw_row.opportunity_id = match.id
            raw_row.processed = True
            _ensure_provenance(
                session, board_state, match, source_id, raw, raw_row, is_primary=False
            )
            return match, False
        _upgrade_direct_apply_url(match, raw, normalized, changed_slugs)
        if len(normalized.description_raw or "") > len(match.description_raw or ""):
            match.description_raw = normalized.description_raw
            match.skills = extract_opportunity_skills(
                match.title,
                match.description_raw or "",
                company_name=normalized.company_name,
            )
            _refresh_extracted_summary(match, meta=match.meta)
        mark_seen(match)
        opportunity, is_new = match, False
    else:
        slug = _make_opportunity_slug(normalized.company_name, normalized.title, raw)
        existing_by_slug = board_state.opportunities_by_slug.get(slug)
        if existing_by_slug is not None:
            existing_by_slug = _lock_existing_opportunity(session, board_state, existing_by_slug.id)
        else:
            # Company corrections can move a row out of this board's company cache.
            existing_by_slug = session.scalar(
                select(models.Opportunity)
                .where(models.Opportunity.slug == slug)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        if existing_by_slug is not None:
            # Safety net for the variant where raw_listings was pruned
            # (Doc 03 sec 8 retention policy) but the opportunity it
            # originally created still exists: there's no raw_row to
            # identity-match through above, but the deterministic slug is
            # still a reliable merge key. Soft-merge instead of a hard
            # INSERT failure.
            opportunity = existing_by_slug
            if (
                safety_flag(opportunity) is not None
                or opportunity.status == "withdrawn"
                or has_manual_closure(opportunity)
            ):
                raw_row.opportunity_id = opportunity.id
                raw_row.processed = True
                _ensure_provenance(
                    session, board_state, opportunity, source_id, raw, raw_row, is_primary=False
                )
                return opportunity, False
            _upgrade_direct_apply_url(opportunity, raw, normalized, changed_slugs)
            if len(normalized.description_raw or "") > len(opportunity.description_raw or ""):
                opportunity.description_raw = normalized.description_raw
                opportunity.skills = extract_opportunity_skills(
                    opportunity.title,
                    opportunity.description_raw or "",
                    company_name=normalized.company_name,
                )
                _refresh_extracted_summary(opportunity, meta=opportunity.meta)
            mark_seen(opportunity)
            is_new = False
        else:
            summary, meta = _extracted_summary_and_meta(
                description=normalized.description_raw,
                title=normalized.title,
                meta=_listing_meta(normalized, country),
            )
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
                summary=summary,
                apply_url=normalized.apply_url,
                posted_at=normalized.posted_at,
                deadline=normalized.deadline,
                meta=meta,
                deadline_confidence=normalized.deadline_confidence,
            )
            session.add(opportunity)
            is_new = True

    if not is_new and normalized.category in {"internship", "job"}:
        previous_role_meta = _role_display_meta(opportunity.meta)
        opportunity.meta = _listing_meta(normalized, country, opportunity.meta)
        if changed_slugs is not None and previous_role_meta != _role_display_meta(opportunity.meta):
            changed_slugs.add(opportunity.slug)

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
