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

        # Commit every BATCH_SIZE listings, not once per company (the
        # original bug) and not once per listing (the first fix). Per-
        # listing commits are correct but were measured live to be far too
        # slow on this network path: one 484-listing company alone consumed
        # most of a 25-minute job, because each commit is a full-durability
        # round-trip and round-trip count - not server processing time - is
        # what's actually slow here. A failed listing now rolls back only
        # its own batch (still-uncommitted listings earlier in the SAME
        # batch are lost too, not just the failed one), not the whole
        # company - an acceptable, self-healing tradeoff: ingest is
        # idempotent, so anything lost just gets reprocessed on the next
        # 2-hour scheduled crawl, never duplicated or silently dropped.
        BATCH_SIZE = 25
        since_last_commit = 0
        # new_opps is counted as "pending" until its batch actually commits,
        # not the moment ingest_normalized_listing returns - otherwise a
        # later failure in the SAME uncommitted batch rolls back an earlier
        # listing's DB row while result["new_opps"] had already counted it,
        # silently overcounting.
        pending_new_opps = 0

        for raw in raw_listings:
            try:
                normalized = adapter.parse(raw)
                _opportunity, is_new = ingest_normalized_listing(
                    session, source_id, company.id, raw, normalized
                )
                since_last_commit += 1
                if is_new:
                    pending_new_opps += 1
                if since_last_commit >= BATCH_SIZE:
                    session.commit()
                    result["new_opps"] += pending_new_opps
                    since_last_commit = 0
                    pending_new_opps = 0
            except Exception as exc:
                try:
                    session.rollback()
                except Exception:
                    pass
                since_last_commit = 0
                pending_new_opps = 0
                result["errors"] += 1
                print(
                    f"    listing error ({raw.external_id}): {type(exc).__name__}: {exc}",
                    flush=True,
                )

        if since_last_commit > 0:
            session.commit()
            result["new_opps"] += pending_new_opps

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
        print(f"WARNING: failed to record crawl_runs for {company_slug}: {exc}", flush=True)

    return result


def run_tier(tier: int) -> None:
    engine = make_engine()

    # Gather the (source_id, company_id) work list with one short-lived
    # session, then process each company with its OWN fresh session below -
    # not one session shared across all 12 companies. A connection that goes
    # bad partway through company N would otherwise carry its damaged state
    # into every company after it, not just N; a fresh session per company
    # means a bad connection costs at most one company; the next gets a
    # clean slate (Doc 04 sec 7 - per-source isolation, extended to cover
    # connection health, not just exceptions).
    with Session(engine) as session:
        sources = session.scalars(
            select(models.Source).where(
                models.Source.crawl_tier == tier, models.Source.enabled.is_(True)
            )
        ).all()

        jobs: list[tuple[int, str]] = []
        for source in sources:
            if source.adapter_key != "greenhouse":
                continue  # Phase 1: only the Greenhouse adapter exists
            companies = session.scalars(
                select(models.Company).where(models.Company.ats_type == "greenhouse")
            ).all()
            jobs.extend((source.id, company.slug) for company in companies)

    for source_id, company_slug in jobs:
        with Session(engine) as session:
            source = session.get(models.Source, source_id)
            company = session.scalar(
                select(models.Company).where(models.Company.slug == company_slug)
            )
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
                print(f"ERROR: {company_slug} crawl raised unexpectedly: {exc}", flush=True)
                continue
            print(f"{company_slug}: {result}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tier", type=int, required=True)
    args = parser.parse_args()
    run_tier(args.tier)


if __name__ == "__main__":
    main()
