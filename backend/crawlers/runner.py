"""Crawl runner: for each enabled source at a given tier, crawl every
company it covers, with per-source isolation (Doc 04 sec 7 - one failing
board never aborts the batch) and change detection (Doc 04 sec 6) gating
the expensive parse/dedup work. Invoked by GitHub Actions cron, NEVER by
the API process (Doc 02 sec 3.3 hard rule).

Deliberate Phase-1 simplification: iterates sources/companies directly
rather than claiming work via the crawl_jobs SKIP LOCKED queue. That queue
exists to let multiple parallel matrix runners claim disjoint work once
there are enough sources/companies to need parallelism (Doc 04 sec 4) - at
12 companies and one adapter, a single sequential pass finishes in well
under a minute, so building the parallel-claim path now would be scaling
for anticipated load rather than measured load (Doc 02 sec 5, Doc 08
binding rule). crawl_jobs remains in the schema, unused, until company
count actually justifies it - a real future amendment, not silent drift.
"""

import argparse
import hashlib
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from core import models
from core.db import make_engine
from crawlers.greenhouse import GreenhouseAdapter
from pipeline.ingest import ingest_normalized_listing


def _board_fingerprint(raw_listings: list) -> str:
    """Cheap aggregate hash over a board's listings - if unchanged since the
    last crawl, downstream parse/dedup/enrich is skipped entirely (Doc 04
    sec 6, the core cost lever)."""
    parts = sorted(f"{r.external_id}:{r.content_hash}" for r in raw_listings)
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def crawl_greenhouse_company(
    session: Session, source: models.Source, company: models.Company
) -> dict:
    """Crawl one company's Greenhouse board. Never raises - every failure
    mode, including a dropped DB connection mid-crawl, is caught and
    reflected in the returned result, so one broken board cannot abort the
    batch (Doc 04 sec 7).

    Plain values are captured up front rather than re-read from the ORM
    objects after a rollback: a rollback expires SQLAlchemy instances, and
    touching an expired attribute triggers a lazy-reload query - which can
    itself fail if the connection is the thing that broke, raising OUTSIDE
    any try/except and aborting the whole batch. Confirmed live: a transient
    connection drop during one company's crawl took down the entire
    12-company run before this fix.
    """
    source_id = source.id
    tier = source.crawl_tier
    board_token = company.ats_board_id
    company_name = company.name
    company_slug = company.slug

    started_at = datetime.now(timezone.utc)
    result = {"listings_found": 0, "new_opps": 0, "errors": 0, "status": "success"}

    try:
        adapter = GreenhouseAdapter(board_token=board_token, company_name=company_name)
        raw_listings = adapter.fetch()
        result["listings_found"] = len(raw_listings)

        if adapter.health() == "broken":
            result["status"] = "failed"
        elif adapter.health() == "degraded":
            result["status"] = "partial"

        fingerprint = _board_fingerprint(raw_listings) if raw_listings else None
        state = session.scalar(
            select(models.SourceState).where(
                models.SourceState.source_id == source_id,
                models.SourceState.page_key == board_token,
            )
        )

        if fingerprint is not None and state is not None and state.last_content_hash == fingerprint:
            session.commit()
            return result  # change-detection skip: nothing changed since last crawl

        for raw in raw_listings:
            try:
                normalized = adapter.parse(raw)
                _opportunity, is_new = ingest_normalized_listing(
                    session, source_id, company.id, raw, normalized
                )
                if is_new:
                    result["new_opps"] += 1
            except Exception:
                result["errors"] += 1

        if fingerprint is not None:
            if state is None:
                state = models.SourceState(source_id=source_id, page_key=board_token)
                session.add(state)
            state.last_content_hash = fingerprint
            state.last_crawled_at = datetime.now(timezone.utc)

        session.commit()

    except Exception:
        try:
            session.rollback()
        except Exception:
            pass
        result["status"] = "failed"
        result["errors"] += 1

    try:
        session.add(
            models.CrawlRun(
                source_id=source_id,
                tier=tier,
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
                status=result["status"],
                listings_found=result["listings_found"],
                new_opps=result["new_opps"],
                errors=result["errors"],
                log={"company_slug": company_slug, "board_token": board_token},
            )
        )
        session.commit()
    except Exception as exc:
        try:
            session.rollback()
        except Exception:
            pass
        print(f"WARNING: failed to record crawl_runs for {company_slug}: {exc}")

    return result


def run_tier(tier: int) -> None:
    engine = make_engine()
    with Session(engine) as session:
        sources = session.scalars(
            select(models.Source).where(
                models.Source.crawl_tier == tier, models.Source.enabled.is_(True)
            )
        ).all()

        for source in sources:
            if source.adapter_key != "greenhouse":
                continue  # Phase 1: only the Greenhouse adapter exists

            companies = session.scalars(
                select(models.Company).where(models.Company.ats_type == "greenhouse")
            ).all()

            for company in companies:
                try:
                    result = crawl_greenhouse_company(session, source, company)
                except Exception as exc:
                    # Last-resort safety net: crawl_greenhouse_company already
                    # catches its own failures, but per-source isolation (Doc
                    # 04 sec 7) must hold even against a bug in that handling
                    # itself - one company can never take down the batch.
                    try:
                        session.rollback()
                    except Exception:
                        pass
                    print(f"ERROR: {company.slug} crawl raised unexpectedly: {exc}")
                    continue
                print(f"{company.slug}: {result}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tier", type=int, required=True)
    args = parser.parse_args()
    run_tier(args.tier)


if __name__ == "__main__":
    main()
