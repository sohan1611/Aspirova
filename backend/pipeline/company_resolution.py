"""Resolve a listing's free-text company name to a canonical Company row -
needed by aggregator sources (Doc handoffs/PHASE-2-HANDOFF.md sec 2/5),
since ATS adapters are always pre-associated with a company at seed time
(scripts/seed_companies.py) but one aggregator fetch spans many different
companies whose only identity signal is a text string.

Exact match on the already-existing name_normalized blocking key (Doc 03
sec 7, pipeline/normalize.py) - not fuzzy - is the deliberate Phase-2 cut:
cross-source company-name fuzzy matching is exactly the kind of problem
pipeline/dedup.py's own docstring already flags as a Phase-3 (embeddings)
concern for opportunity titles; extending that same caution to company
names avoids a second, unvalidated fuzzy-matching surface. A false SPLIT
(two Company rows for spelling variants of the same real company) is the
safer failure mode here, consistent with Doc 01 R5's preference for false
splits over false merges.
"""

import hashlib
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from core import models
from core.textclean import fix_text
from pipeline.normalize import normalize_company_name


def _slugify(text: str) -> str:
    slug = text.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return re.sub(r"-+", "-", slug).strip("-")


def resolve_company(
    session: Session, company_name: str, domain: str | None = None
) -> models.Company:
    company_name = fix_text(company_name) or ""
    name_normalized = normalize_company_name(company_name)
    existing = session.scalar(
        select(models.Company).where(models.Company.name_normalized == name_normalized)
    )
    if existing is not None:
        return existing

    base_slug = _slugify(company_name)[:80] or "company"
    # Disambiguator from the normalized name, not raw input - two spellings
    # that normalize identically (whitespace/case/legal-suffix variants)
    # must resolve to the SAME slug attempt, so a retry lands on the
    # existing-row branch above rather than colliding on insert.
    disambiguator = hashlib.sha256(name_normalized.encode()).hexdigest()[:8]
    slug = f"{base_slug}-{disambiguator}"

    company = models.Company(
        slug=slug,
        name=company_name,
        name_normalized=name_normalized,
        domain=domain,
    )
    session.add(company)
    session.flush()  # need company.id for the caller's board_state/ingest
    return company
