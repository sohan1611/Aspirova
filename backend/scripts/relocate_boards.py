"""Move audited ATS boards after verifying live inventory and company identity.

Dry-run by default. --apply writes only the seven reviewed relocations; an
unexpected current board is a conflict, never an invitation to overwrite it.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db import make_engine
from core.models import Company
from crawlers.common import extract_text
from scripts.seed_boards_batch import BoardCandidate, Verification, Verifier, verify_candidate


@dataclass(frozen=True)
class Relocation:
    company_slug: str
    old_ats: str
    old_token: str
    new_ats: str
    new_token: str


# Reviewed against the 2026-11-08 independent audit; not a discovery heuristic.
RELOCATIONS = (
    Relocation("freshworks", "lever", "freshworks", "smartrecruiters", "freshworks"),
    Relocation("ledger", "lever", "ledger", "ashby", "ledger"),
    Relocation("temporaltechnologies", "greenhouse", "temporaltechnologies", "ashby", "temporal"),
    Relocation("sophos", "lever", "sophos", "ashby", "sophos"),
    Relocation("clickhouse", "greenhouse", "clickhouse", "ashby", "clickhouse"),
    Relocation("amplitude", "greenhouse", "amplitude", "ashby", "amplitude"),
    Relocation("webflow", "greenhouse", "webflow", "ashby", "webflow"),
)


def _posting_texts(value: object) -> Iterable[str]:
    if isinstance(value, str):
        # The ATS token is supplied by us. Merely echoing it in a hosted job
        # URL cannot verify identity (especially for names such as Ledger).
        host = urlsplit(value).hostname if value.startswith(("http://", "https://")) else None
        if host and any(
            host == domain or host.endswith(f".{domain}")
            for domain in ("ashbyhq.com", "smartrecruiters.com")
        ):
            return
        yield extract_text(value)
    elif isinstance(value, dict):
        for nested in value.values():
            yield from _posting_texts(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _posting_texts(nested)


def posting_confirms_company(verification: Verification, company: Company) -> bool:
    """Require company text or a first-party domain in at least one posting."""
    name = re.compile(r"(?<!\w)" + re.escape(company.name) + r"(?!\w)", re.IGNORECASE)
    domain = (company.domain or "").lower().removeprefix("www.")
    domain_pattern = (
        re.compile(r"(?<![\w-])" + re.escape(domain) + r"(?![\w.-])", re.IGNORECASE)
        if domain
        else None
    )
    for listing in verification.listings:
        texts = list(_posting_texts(listing.raw_payload))
        texts.extend(_posting_texts(listing.source_url))
        for text_value in texts:
            if name.search(text_value) or (domain_pattern and domain_pattern.search(text_value)):
                return True
    return False


def relocate_boards(
    session: Session,
    *,
    apply: bool = False,
    relocations: Iterable[Relocation] = RELOCATIONS,
    verifier: Verifier = verify_candidate,
) -> dict[str, str]:
    """Verify first, then change only the configured old pair. Caller commits."""
    result = {}
    for relocation in relocations:
        company = session.scalar(select(Company).where(Company.slug == relocation.company_slug))
        if company is None:
            result[relocation.company_slug] = "missing company"
            continue
        current = (company.ats_type, company.ats_board_id)
        target = (relocation.new_ats, relocation.new_token)
        if current == target:
            result[relocation.company_slug] = "unchanged"
            continue
        if current != (relocation.old_ats, relocation.old_token):
            result[relocation.company_slug] = (
                "conflict: current board differs from reviewed old pair"
            )
            continue
        candidate = BoardCandidate(company.name, *target, company.domain)
        try:
            verification = verifier(candidate)
            if (
                not verification.accepted
                or verification.health != "ok"
                or not verification.listings_count
                or not posting_confirms_company(verification, company)
            ):
                result[relocation.company_slug] = (
                    "rejected: target empty, unhealthy or identity unconfirmed"
                )
                continue
        except Exception as exc:
            result[relocation.company_slug] = f"rejected: verification raised {type(exc).__name__}"
            continue
        if apply:
            company.ats_type, company.ats_board_id = target
        result[relocation.company_slug] = "relocated" if apply else "would relocate"
    return result


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--dry-run", action="store_true", help="preview only (default)")
    args = parser.parse_args(argv)
    engine = make_engine()
    try:
        with Session(engine) as session:
            results = relocate_boards(session, apply=args.apply)
            if args.apply:
                session.commit()
            for slug, outcome in results.items():
                print(f"RELOCATE BOARD: {slug}: {outcome}", flush=True)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
