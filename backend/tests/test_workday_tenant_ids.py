"""Committed runner regressions; run only against a throwaway Postgres database."""

import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from core import models
from core.adapters import RawListing
from crawlers import runner
from crawlers.workday import WorkdayAdapter
from pipeline import ingest


class _OfflineWorkdayAdapter(WorkdayAdapter):
    def __init__(self, board_token: str, company_name: str) -> None:
        super().__init__(board_token, company_name)
        self._client.close()

    def _json(self, *args, **kwargs):
        raise AssertionError("Workday HTTP must be mocked")

    def fetch(self):
        raise AssertionError("Runner must use prefetched listings")


@pytest.fixture
def workday_db(engine):
    # crawl_company_board commits and rolls back itself. An outer test
    # transaction would hide the transaction boundary this regression needs.
    unique = uuid.uuid4().hex[:12]
    source_slug = f"test-isolation-workday-{unique}"
    company_slugs = [f"test-isolation-co-{tenant}-{unique}" for tenant in ("a", "b")]
    source = models.Source(
        slug=source_slug, name="Test Workday", type="ats", crawl_tier=1, adapter_key="workday"
    )
    companies = [
        models.Company(
            slug=slug,
            name=f"Workday Test {tenant.upper()} {unique}",
            name_normalized=f"workday test {tenant} {unique}",
            ats_type="workday",
            ats_board_id=f"{tenant}|{cluster}|External",
        )
        for tenant, cluster, slug in zip(("a", "b"), ("wd1", "wd5"), company_slugs)
    ]
    with Session(engine) as session:
        try:
            session.add_all([source, *companies])
            session.commit()
            yield session, source, companies
        finally:
            session.rollback()
            source_ids = select(models.Source.id).where(models.Source.slug == source_slug)
            company_ids = select(models.Company.id).where(models.Company.slug.in_(company_slugs))
            opportunity_ids = select(models.Opportunity.id).where(
                models.Opportunity.company_id.in_(company_ids)
            )
            # Children first, including any tags created by normal ingest.
            session.execute(
                delete(models.OpportunityTag).where(
                    models.OpportunityTag.opportunity_id.in_(opportunity_ids)
                )
            )
            session.execute(
                delete(models.OpportunitySource).where(
                    models.OpportunitySource.opportunity_id.in_(opportunity_ids)
                    | models.OpportunitySource.source_id.in_(source_ids)
                )
            )
            session.execute(
                delete(models.Notification).where(
                    models.Notification.opportunity_id.in_(opportunity_ids)
                )
            )
            session.execute(
                delete(models.OpportunityViewCount).where(
                    models.OpportunityViewCount.opportunity_id.in_(opportunity_ids)
                )
            )
            for model in (models.RawListing, models.CrawlRun, models.SourceState):
                session.execute(delete(model).where(model.source_id.in_(source_ids)))
            session.execute(
                delete(models.Opportunity).where(models.Opportunity.id.in_(opportunity_ids))
            )
            session.execute(delete(models.Company).where(models.Company.id.in_(company_ids)))
            session.execute(delete(models.Source).where(models.Source.id.in_(source_ids)))
            session.commit()


def _listing(company, *, req_id="R0001", title=None, location=None) -> RawListing:
    adapter = _OfflineWorkdayAdapter(company.ats_board_id, company.name)
    tenant = adapter.tenant
    path = f"/job/Intern_{req_id}"
    info = {
        "jobReqId": req_id,
        "title": title
        or ("Software Engineering Intern" if tenant == "a" else "Data Science Intern"),
        "location": location or ("Bengaluru, India" if tenant == "a" else "London, United Kingdom"),
        "jobDescription": "<p>Build student projects with Python.</p>",
        "externalUrl": f"{adapter.base_url}/{adapter.site}{path}",
        "startDate": "2026-11-01",
    }
    with patch.object(adapter, "_json", return_value={"jobPostingInfo": info}):
        return adapter._details({path: {"title": info["title"]}})[0]


def _crawl(session, source, company, listings):
    return runner.crawl_company_board(
        session,
        source,
        company,
        _OfflineWorkdayAdapter,
        prefetched=listings,
        prefetched_health="ok",
        # Same keys _coverage_from_adapter produces; crawl_runs logging needs them.
        prefetched_coverage={
            "fetched": len(listings),
            "expected_total": None,
            "mode": "search",
            "status": "complete",
            "board_outcome": {"board_state": "ok", "http_status": 200},
        },
    )


def _seed_legacy(session, source, company, raw):
    adapter = _OfflineWorkdayAdapter(company.ats_board_id, company.name)
    legacy = raw.model_copy(update={"external_id": adapter.legacy_external_id(raw)})
    state = ingest.load_board_state(session, source.id, company.id)
    opportunity, is_new = ingest.ingest_one(
        session, state, source.id, company.id, legacy, adapter.parse(legacy)
    )
    assert is_new
    session.add(
        models.SourceState(
            source_id=source.id,
            page_key=company.ats_board_id,
            last_content_hash=runner._board_fingerprint([legacy]),
        )
    )
    session.flush()
    raw_id = state.raw_by_external_id[legacy.external_id].id
    opportunity_id = opportunity.id
    link_id = session.scalar(
        select(models.OpportunitySource.id).where(models.OpportunitySource.source_id == source.id)
    )
    assert link_id is not None
    session.commit()
    return raw_id, opportunity_id, link_id


def _raw_rows(session, source):
    return session.scalars(
        select(models.RawListing)
        .where(models.RawListing.source_id == source.id)
        .order_by(models.RawListing.id)
    ).all()


def _opportunities(session, companies):
    return session.scalars(
        select(models.Opportunity)
        .where(models.Opportunity.company_id.in_([company.id for company in companies]))
        .order_by(models.Opportunity.id)
    ).all()


def _links(session, source):
    return session.scalars(
        select(models.OpportunitySource)
        .where(models.OpportunitySource.source_id == source.id)
        .order_by(models.OpportunitySource.id)
    ).all()


def test_two_tenants_with_same_req_id_stay_separate_on_repeat_crawls(workday_db):
    session, source, companies = workday_db
    listings = [_listing(company) for company in companies]
    assert [raw.external_id for raw in listings] == ["a|external|R0001", "b|external|R0001"]
    for company, raw in zip(companies, listings):
        result = _crawl(session, source, company, [raw])
        assert result["errors"] == 0 and result["new_opps"] == 1

    rows = _raw_rows(session, source)
    opportunities = _opportunities(session, companies)
    assert len(rows) == len(opportunities) == len(_links(session, source)) == 2
    expected_owners = {raw.external_id: company.id for company, raw in zip(companies, listings)}
    owners = {opportunity.id: opportunity.company_id for opportunity in opportunities}
    assert {row.external_id: owners[row.opportunity_id] for row in rows} == expected_owners
    before = [(row.id, row.external_id, row.opportunity_id, row.raw_payload) for row in rows]
    opportunity_ids = [opportunity.id for opportunity in opportunities]
    link_ids = [link.id for link in _links(session, source)]

    for company, raw in zip(companies, listings):
        result = _crawl(session, source, company, [raw])
        assert result["errors"] == result["new_opps"] == result["changed_slugs"] == 0
    assert [
        (row.id, row.external_id, row.opportunity_id, row.raw_payload)
        for row in _raw_rows(session, source)
    ] == before
    assert [opportunity.id for opportunity in _opportunities(session, companies)] == opportunity_ids
    assert [link.id for link in _links(session, source)] == link_ids


@pytest.mark.parametrize("later_db_error", [False, True])
def test_legacy_rename_preserves_identity_and_survives_batch_rollback(
    workday_db, monkeypatch, capsys, later_db_error
):
    session, source, companies = workday_db
    company = companies[0]
    raw = _listing(company)
    raw_id, opportunity_id, link_id = _seed_legacy(session, source, company, raw)
    listings = [raw]
    if later_db_error:
        failing = _listing(company, req_id="R0002")
        listings.extend([failing, raw])
        real_ingest_one = runner.ingest_one

        def fail_second_listing(session, *args, **kwargs):
            if args[3].external_id == failing.external_id:
                session.execute(text("SELECT 1/0"))
            return real_ingest_one(session, *args, **kwargs)

        monkeypatch.setattr(runner, "ingest_one", fail_second_listing)

    result = _crawl(session, source, company, listings)

    assert result["errors"] == int(later_db_error)
    assert result["status"] == ("partial" if later_db_error else "success")
    assert result["new_opps"] == 0
    assert "    workday:a|wd1|External claimed 1 legacy external ids" in capsys.readouterr().out
    session.expire_all()
    rows = _raw_rows(session, source)
    assert [(row.id, row.external_id, row.opportunity_id) for row in rows] == [
        (raw_id, raw.external_id, opportunity_id)
    ]
    assert rows[0].raw_payload == raw.raw_payload
    assert rows[0].content_hash == raw.content_hash
    assert [opportunity.id for opportunity in _opportunities(session, companies)] == [
        opportunity_id
    ]
    links = _links(session, source)
    assert [(link.id, link.opportunity_id, link.raw_listing_id) for link in links] == [
        (link_id, opportunity_id, raw_id)
    ]
    if not later_db_error:
        result = _crawl(session, source, company, [raw])
        assert result["errors"] == result["new_opps"] == 0
        latest = session.scalar(
            select(models.CrawlRun)
            .where(models.CrawlRun.source_id == source.id)
            .order_by(models.CrawlRun.id.desc())
            .limit(1)
        )
        assert latest.log["skipped_unchanged"] is True
        assert "claimed" not in capsys.readouterr().out


def test_legacy_collision_is_claimed_only_by_owner_and_repairs_polluted_content(workday_db, capsys):
    session, source, companies = workday_db
    company_a, company_b = companies
    raw_a, raw_b = [_listing(company) for company in companies]
    raw_id, opportunity_id, link_id = _seed_legacy(session, source, company_a, raw_b)
    polluted = session.get(models.Opportunity, opportunity_id)
    assert (polluted.title, polluted.location, polluted.apply_url) == (
        raw_b.raw_payload["title"],
        raw_b.raw_payload["location"],
        raw_b.source_url,
    )

    result = _crawl(session, source, company_b, [raw_b])

    assert result["errors"] == 0 and result["new_opps"] == 1
    assert "claimed" not in capsys.readouterr().out
    session.expire_all()
    legacy = session.get(models.RawListing, raw_id)
    assert legacy.external_id == "R0001" and legacy.opportunity_id == opportunity_id
    assert legacy.raw_payload == raw_b.raw_payload and legacy.content_hash == raw_b.content_hash
    assert legacy.source_url == raw_b.source_url
    polluted = session.get(models.Opportunity, opportunity_id)
    assert (polluted.title, polluted.location, polluted.apply_url) == (
        raw_b.raw_payload["title"],
        raw_b.raw_payload["location"],
        raw_b.source_url,
    )
    b_row = next(row for row in _raw_rows(session, source) if row.external_id == raw_b.external_id)
    b_opportunity_id = b_row.opportunity_id
    assert b_opportunity_id != opportunity_id
    assert session.get(models.Opportunity, b_opportunity_id).company_id == company_b.id

    result = _crawl(session, source, company_a, [raw_a])

    assert result["errors"] == result["new_opps"] == 0
    assert "claimed 1 legacy external ids" in capsys.readouterr().out
    session.expire_all()
    renamed = session.get(models.RawListing, raw_id)
    assert renamed.external_id == raw_a.external_id and renamed.opportunity_id == opportunity_id
    assert renamed.raw_payload == raw_a.raw_payload and renamed.content_hash == raw_a.content_hash
    restored = session.get(models.Opportunity, opportunity_id)
    assert restored.company_id == company_a.id
    assert (restored.title, restored.location, restored.apply_url) == (
        raw_a.raw_payload["title"],
        raw_a.raw_payload["location"],
        raw_a.source_url,
    )
    assert len(_raw_rows(session, source)) == len(_opportunities(session, companies)) == 2
    assert session.get(models.OpportunitySource, link_id).raw_listing_id == raw_id
    assert session.get(models.Opportunity, b_opportunity_id).apply_url == raw_b.source_url


def test_existing_scoped_row_leaves_legacy_row_alone(workday_db, capsys):
    session, source, companies = workday_db
    company = companies[0]
    raw = _listing(company)
    raw_id, opportunity_id, link_id = _seed_legacy(session, source, company, raw)
    scoped = models.RawListing(
        source_id=source.id,
        external_id=raw.external_id,
        source_url=raw.source_url,
        content_hash=raw.content_hash,
        raw_payload=raw.raw_payload,
        processed=True,
        opportunity_id=opportunity_id,
    )
    session.add(scoped)
    session.flush()
    scoped_id = scoped.id
    session.get(models.OpportunitySource, link_id).raw_listing_id = scoped_id
    session.commit()

    result = _crawl(session, source, company, [raw])

    assert result["errors"] == result["new_opps"] == 0
    assert "claimed" not in capsys.readouterr().out
    session.expire_all()
    assert session.get(models.RawListing, raw_id).external_id == "R0001"
    assert session.get(models.RawListing, scoped_id).external_id == raw.external_id
    assert session.get(models.OpportunitySource, link_id).raw_listing_id == scoped_id
    assert len(_raw_rows(session, source)) == 2
    assert [opportunity.id for opportunity in _opportunities(session, companies)] == [
        opportunity_id
    ]


def test_claim_rejects_unowned_and_already_scoped_legacy_ids(workday_db):
    session, source, companies = workday_db
    company_a, company_b = companies
    raw_a = _listing(company_a)
    _, a_id, _ = _seed_legacy(session, source, company_a, raw_a)
    result = _crawl(session, source, company_b, [_listing(company_b)])
    assert result["errors"] == 0
    b_id = next(o.id for o in _opportunities(session, companies) if o.company_id == company_b.id)
    invalid = [
        models.RawListing(source_id=source.id, external_id="NULL", opportunity_id=None),
        models.RawListing(source_id=source.id, external_id="OTHER", opportunity_id=b_id),
        models.RawListing(
            source_id=source.id, external_id="old|external|R0001", opportunity_id=a_id
        ),
    ]
    session.add_all(invalid)
    session.commit()
    state = ingest.load_board_state(session, source.id, company_a.id, {})

    claimed = ingest.claim_legacy_raw_listings(
        session,
        source.id,
        state,
        {
            "a|external|NULL": "NULL",
            "a|external|OTHER": "OTHER",
            "a|external|OLD": "old|external|R0001",
        },
    )

    session.commit()
    assert claimed == 0 and state.raw_by_external_id == {}
    assert [row.external_id for row in invalid] == ["NULL", "OTHER", "old|external|R0001"]


def test_same_legacy_row_is_claimed_once_in_listing_order(workday_db):
    session, source, companies = workday_db
    company = companies[0]
    raw = _listing(company)
    raw_id, opportunity_id, _ = _seed_legacy(session, source, company, raw)
    state = ingest.load_board_state(session, source.id, company.id, {})

    claimed = ingest.claim_legacy_raw_listings(
        session,
        source.id,
        state,
        {"a|external|first": "R0001", "a|external|second": "R0001"},
    )

    session.commit()
    assert claimed == 1
    assert list(state.raw_by_external_id) == ["a|external|first"]
    row = session.get(models.RawListing, raw_id)
    assert row.external_id == "a|external|first" and row.opportunity_id == opportunity_id
