"""Backfill company domains from Clearbit autocomplete suggestions."""

import argparse
import time
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.orm import Session, load_only

from core import models
from core.db import make_engine
from pipeline.normalize import normalize_company_name

BATCH_SIZE = 100
CLEARBIT_SUGGEST_URL = "https://autocomplete.clearbit.com/v1/companies/suggest"
REQUEST_TIMEOUT_SECONDS = 10.0
EXAMPLE_LIMIT = 10


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _non_negative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be at least 0")
    return parsed


def _batches(
    session: Session,
    *,
    limit: int | None,
    batch_size: int = BATCH_SIZE,
) -> Iterator[list[models.Company]]:
    last_id = 0
    remaining = limit
    while remaining is None or remaining > 0:
        current_size = batch_size if remaining is None else min(batch_size, remaining)
        rows = list(
            session.scalars(
                select(models.Company)
                .options(
                    load_only(
                        models.Company.id,
                        models.Company.name,
                        models.Company.name_normalized,
                        models.Company.domain,
                    )
                )
                .where(models.Company.id > last_id, models.Company.domain.is_(None))
                .order_by(models.Company.id)
                .limit(current_size)
            ).all()
        )
        if not rows:
            return
        batch_last_id = rows[-1].id
        yield rows
        last_id = batch_last_id
        if remaining is not None:
            remaining -= len(rows)


def _first_token(value: str) -> str | None:
    tokens = value.split()
    if not tokens:
        return None
    return tokens[0]


def _is_confident_match(company: models.Company, suggestion_name: str) -> bool:
    company_normalized = company.name_normalized or normalize_company_name(company.name)
    suggestion_normalized = normalize_company_name(suggestion_name)
    if not company_normalized or not suggestion_normalized:
        return False
    if suggestion_normalized == company_normalized:
        return True

    company_first = _first_token(company_normalized)
    suggestion_first = _first_token(suggestion_normalized)
    if company_first is None or suggestion_first is None or company_first != suggestion_first:
        return False

    suggestion_extends_company = suggestion_normalized.startswith(company_normalized)
    company_extends_suggestion = company_normalized.startswith(suggestion_normalized)
    return suggestion_extends_company or company_extends_suggestion


def _clean_domain(value: Any) -> str | None:
    if not isinstance(value, str):
        return None

    raw_domain = value.strip().lower()
    if not raw_domain:
        return None

    parsed = urlparse(raw_domain if "://" in raw_domain else f"//{raw_domain}")
    domain = parsed.netloc or parsed.path.split("/", maxsplit=1)[0]
    domain = domain.rsplit("@", maxsplit=1)[-1].split(":", maxsplit=1)[0].strip(".")
    return domain or None


def _lookup_top_suggestion(client: Any, company_name: str) -> dict[str, Any] | None:
    try:
        response = client.get(
            CLEARBIT_SUGGEST_URL,
            params={"query": company_name},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        suggestions = response.json()
    except Exception:
        return None

    if not isinstance(suggestions, list) or not suggestions:
        return None
    top_suggestion = suggestions[0]
    if not isinstance(top_suggestion, dict):
        return None
    return top_suggestion


def _domain_exists(session: Session, domain: str) -> bool:
    existing_id = session.scalar(
        select(models.Company.id).where(func.lower(models.Company.domain) == domain).limit(1)
    )
    return existing_id is not None


def backfill_domains(
    session: Session,
    *,
    limit: int | None = None,
    dry_run: bool = False,
    sleep_seconds: float = 0.4,
) -> dict[str, Any]:
    try:
        import httpx
    except ImportError as exc:
        raise RuntimeError("httpx is required to run the domain backfill script") from exc

    scanned = 0
    matched = 0
    skipped = 0
    examples: list[str] = []
    claimed_domains: set[str] = set()

    with httpx.Client() as client:
        for rows in _batches(session, limit=limit):
            for company in rows:
                scanned += 1
                suggestion = _lookup_top_suggestion(client, company.name)
                if suggestion is None:
                    skipped += 1
                    time.sleep(sleep_seconds)
                    continue

                suggestion_name = suggestion.get("name")
                domain = _clean_domain(suggestion.get("domain"))
                if (
                    not isinstance(suggestion_name, str)
                    or domain is None
                    or not _is_confident_match(company, suggestion_name)
                    or domain in claimed_domains
                    or _domain_exists(session, domain)
                ):
                    skipped += 1
                    time.sleep(sleep_seconds)
                    continue

                matched += 1
                claimed_domains.add(domain)
                if len(examples) < EXAMPLE_LIMIT:
                    examples.append(f"{company.name} -> {domain}")
                if not dry_run:
                    company.domain = domain

                time.sleep(sleep_seconds)

            if not dry_run:
                session.commit()

    if dry_run:
        session.rollback()

    return {
        "scanned": scanned,
        "matched": matched,
        "skipped": skipped,
        "examples": examples,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=_positive_int, help="Maximum domain-null companies to scan")
    parser.add_argument("--dry-run", action="store_true", help="Report matches without writing")
    parser.add_argument(
        "--sleep",
        type=_non_negative_float,
        default=0.4,
        help="Seconds to sleep between Clearbit API calls",
    )
    args = parser.parse_args()

    engine = make_engine()
    with Session(engine) as session:
        result = backfill_domains(
            session,
            limit=args.limit,
            dry_run=args.dry_run,
            sleep_seconds=args.sleep,
        )

    action = "would match" if args.dry_run else "matched"
    print(
        "domain backfill: "
        f"scanned {result['scanned']}, {action} {result['matched']}, "
        f"skipped {result['skipped']}",
        flush=True,
    )
    if args.dry_run and result["examples"]:
        print("example matches:", flush=True)
        for example in result["examples"]:
            print(f"  {example}", flush=True)


if __name__ == "__main__":
    main()
