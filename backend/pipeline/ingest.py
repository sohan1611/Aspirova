"""Ingest pipeline: adapter output -> raw_listings -> dedup -> canonical
opportunities, with full provenance (Doc 03 sec 3.3-3.5, Doc 04 sec 7 & 9).
Idempotent at every stage - re-running the same raw listing makes zero new
rows (Doc 04 sec 9: "re-running a crawl must not create duplicate canonical
opps").
"""

import hashlib
import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core import models
from core.adapters import NormalizedListing, RawListing
from pipeline.dedup import find_matching_opportunity
from pipeline.normalize import normalize_title


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


def ingest_normalized_listing(
    session: Session,
    source_id: int,
    company_id: int | None,
    raw: RawListing,
    normalized: NormalizedListing,
) -> tuple[models.Opportunity, bool]:
    """Returns (opportunity, is_new_canonical_opportunity).

    Idempotent: a repeat call with byte-identical raw content (same
    content_hash) is a near-no-op - only last_seen_at is touched.
    """
    raw_row = session.scalar(
        select(models.RawListing).where(
            models.RawListing.source_id == source_id,
            models.RawListing.external_id == raw.external_id,
        )
    )
    is_unchanged = raw_row is not None and raw_row.content_hash == raw.content_hash

    if is_unchanged and raw_row.opportunity_id is not None:
        opportunity = session.get(models.Opportunity, raw_row.opportunity_id)
        opportunity.last_seen_at = func.now()
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
    else:
        raw_row.content_hash = raw.content_hash
        raw_row.raw_payload = raw.raw_payload

    title_normalized = normalize_title(normalized.title)
    match = find_matching_opportunity(
        session, company_id, title_normalized, location=normalized.location
    )

    if match is not None:
        if len(normalized.description_raw or "") > len(match.description_raw or ""):
            match.description_raw = normalized.description_raw
        match.last_seen_at = func.now()
        opportunity, is_new = match, False
    else:
        opportunity = models.Opportunity(
            slug=_make_opportunity_slug(normalized.company_name, normalized.title, raw),
            company_id=company_id,
            title=normalized.title,
            title_normalized=title_normalized,
            category=normalized.category,
            location=normalized.location,
            is_remote=normalized.is_remote,
            description_raw=normalized.description_raw,
            apply_url=normalized.apply_url,
            posted_at=normalized.posted_at,
            deadline=normalized.deadline,
            deadline_confidence=normalized.deadline_confidence,
        )
        session.add(opportunity)
        is_new = True

    session.flush()  # need opportunity.id for the FKs below

    raw_row.opportunity_id = opportunity.id
    raw_row.processed = True

    existing_link = session.scalar(
        select(models.OpportunitySource).where(
            models.OpportunitySource.opportunity_id == opportunity.id,
            models.OpportunitySource.source_id == source_id,
            models.OpportunitySource.source_url == raw.source_url,
        )
    )
    if existing_link is None:
        session.add(
            models.OpportunitySource(
                opportunity_id=opportunity.id,
                source_id=source_id,
                source_url=raw.source_url,
                raw_listing_id=raw_row.id,
                is_primary=is_new,
            )
        )

    return opportunity, is_new
