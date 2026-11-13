"""Worker DB transactions and offline review with injected HTTP and storage."""

import csv
import json
import random
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from core import models
from core.config import Settings
from pipeline.company_logos import MAX_ATS_BODY_BYTES, MAX_BODY_BYTES, Candidate, FetchResult
from pipeline.company_resolution import resolve_company
from scripts import logo_worker as worker


def test_shipped_overrides_are_domain_entries():
    overrides = worker.load_overrides(worker.DEFAULT_OVERRIDES)
    assert overrides
    assert list(overrides) == sorted(overrides)
    for slug, entry in overrides.items():
        assert set(entry) == {"domain"}, slug
        assert isinstance(entry["domain"], str), slug
        assert entry["domain"] and entry["domain"] == entry["domain"].strip(), slug


@pytest.fixture(scope="session", autouse=True)
def _purge_isolation_test_residue():
    """DB tests use outer rollbacks. The offline test must not request an engine."""


@pytest.fixture
def db_session(engine):
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


class FakeFetcher:
    def __init__(self):
        self.responses = {}
        self.calls = []
        self.limits = []

    def get(self, url, *, params=None, max_bytes=MAX_BODY_BYTES):
        self.calls.append((url, params))
        self.limits.append((url, max_bytes))
        return self.responses.get(url)

    def image(self, url, seed=0):
        output = BytesIO()
        image = Image.frombytes("RGB", (64, 64), random.Random(seed).randbytes(64 * 64 * 3))
        image.save(output, format="PNG")
        self.responses[url] = FetchResult(
            200, url, {"content-type": "image/png"}, output.getvalue()
        )

    def homepage(self, domain, *, seed=0, title="Acme"):
        url = f"https://{domain}/"
        content = f'<title>{title}</title><link rel="icon" href="/logo.png">'.encode()
        self.responses[url] = FetchResult(200, url, {}, content)
        self.image(f"https://{domain}/logo.png", seed)


@pytest.fixture
def companies(db_session, monkeypatch):
    created = []
    original_counts = worker.active_counts

    def counts():
        subquery = original_counts()
        return (
            select(subquery).where(subquery.c.company_id.in_([co.id for co in created])).subquery()
        )

    monkeypatch.setattr(worker, "active_counts", counts)
    original_select = worker.select_companies

    def select_created(session, args, overrides):
        # The shared test DB also holds organiser/external companies (for example
        # one on google.com) that the organiser pass selects; keep each test to
        # the rows it created.
        ids = {company.id for company in created}
        return [row for row in original_select(session, args, overrides) if row[0] in ids]

    monkeypatch.setattr(worker, "select_companies", select_created)

    def create(*, active=True, **kwargs):
        suffix = uuid4().hex
        company = models.Company(
            slug=f"test-logo-worker-{suffix}",
            name=f"Logo Worker {suffix}",
            name_normalized=f"logo worker {suffix}",
            **kwargs,
        )
        db_session.add(company)
        db_session.flush()
        created.append(company)
        if active:
            db_session.add(
                models.Opportunity(
                    company_id=company.id,
                    slug=f"test-logo-worker-job-{suffix}",
                    title="Software Intern",
                    category="internship",
                    apply_url="https://jobs.example/apply",
                    first_seen_at=datetime.now(UTC),
                    status="active",
                )
            )
            db_session.flush()
        return company

    return create


@pytest.fixture
def run_worker(db_session, monkeypatch):
    fetcher = FakeFetcher()
    uploads = []
    notifications = []
    monkeypatch.setattr(
        "pipeline.revalidate.notify_changed", lambda slugs: notifications.append(slugs)
    )

    def upload(slug, logo):
        uploads.append((slug, logo))
        return f"https://stored.example/{slug}-{logo.sha256}.png"

    def run(
        *,
        overrides=None,
        dry_run=False,
        limit=1500,
        time_budget_min=45,
        renormalize=False,
        recheck_days=30,
    ):
        # Persist fixtures into the outer transaction, which the fixture alone
        # owns. Worker commits and rollbacks only release its own savepoints.
        db_session.commit()
        args = worker.parse_args(["--limit", str(limit), "--time-budget-min", str(time_budget_min)])
        args.dry_run = dry_run
        args.renormalize = renormalize
        args.recheck_days = recheck_days
        return worker.run_db(db_session, args, fetcher, overrides or {}, upload)

    run.fetcher = fetcher
    run.uploads = uploads
    run.notifications = notifications
    return run


def test_existing_logo_is_not_selected_or_fetched(db_session, companies, run_worker):
    company = companies(logo_url="https://stored.example/existing.png", logo_status="found")
    assert worker.select_companies(db_session, worker.parse_args([]), {}) == []
    assert run_worker() == []
    assert run_worker.fetcher.calls == []
    assert run_worker.uploads == []
    db_session.refresh(company)
    assert company.logo_url == "https://stored.example/existing.png"


@pytest.mark.parametrize("status", ["found", "manual"])
def test_renormalize_updates_only_url_and_hash(db_session, companies, run_worker, status):
    url = "https://stored.example/old.png"
    checked_at = datetime.now(UTC) - timedelta(days=5)
    evidence = {"sha256": "old", "override": {"domain": "acme.example"}, "reason": "trusted"}
    company = companies(
        logo_url=url,
        logo_status=status,
        logo_source="override",
        logo_evidence=evidence,
        logo_checked_at=checked_at,
        logo_hint_url="https://hint.example/logo.png",
    )
    run_worker.fetcher.image(url)
    results = run_worker(renormalize=True)
    db_session.refresh(company)
    assert len(results) == len(run_worker.uploads) == 1
    slug, logo = run_worker.uploads[0]
    assert slug == company.slug
    assert company.logo_url == f"https://stored.example/{slug}-{logo.sha256}.png"
    assert company.logo_evidence == {**evidence, "sha256": logo.sha256}
    assert company.logo_status == status
    assert company.logo_source == "override"
    assert company.logo_checked_at == checked_at
    assert company.logo_hint_url == "https://hint.example/logo.png"
    assert company.domain is None
    assert run_worker.fetcher.calls == [(url, None)]
    expected = db_session.scalars(
        select(models.Opportunity.slug).where(models.Opportunity.company_id == company.id)
    ).all()
    assert run_worker.notifications == [expected]


def test_renormalize_dry_run_leaves_everything_untouched(db_session, companies, run_worker):
    url = "https://stored.example/dry.png"
    company = companies(logo_url=url, logo_status="manual", logo_evidence={"sha256": "old"})
    run_worker.fetcher.image(url)
    results = run_worker(renormalize=True, dry_run=True)
    db_session.refresh(company)
    assert len(results) == 1 and results[0].logo is not None
    assert company.logo_url == url
    assert company.logo_evidence == {"sha256": "old"}
    assert company.logo_status == "manual"
    assert run_worker.uploads == run_worker.notifications == []


def test_renormalize_unchanged_bytes_skip_upload(db_session, companies, run_worker):
    url = "https://stored.example/normalized.png"
    run_worker.fetcher.image(url)
    logo = worker.validate_and_normalize(run_worker.fetcher.responses[url])
    assert logo is not None
    run_worker.fetcher.responses[url] = FetchResult(
        200, url, {"content-type": "image/png"}, logo.png_bytes
    )
    company = companies(logo_url=url, logo_status="found", logo_evidence={"sha256": logo.sha256})
    run_worker(renormalize=True)
    db_session.refresh(company)
    assert company.logo_url == url
    assert run_worker.uploads == run_worker.notifications == []


def test_renormalize_selects_stored_statuses_even_without_active_listings(db_session, companies):
    selected = [
        companies(active=False, logo_status=status, logo_url=f"https://stored.example/{status}.png")
        for status in ("found", "manual")
    ]
    companies(logo_status="rejected_generic", logo_url="https://stored.example/rejected.png")
    companies(logo_status="found")
    args = worker.parse_args(["--renormalize"])
    assert {row[0] for row in worker.select_companies(db_session, args, {})} == {
        co.id for co in selected
    }


@pytest.mark.parametrize("failure", ["fetch", "invalid", "upload"])
def test_renormalize_failure_preserves_row_and_continues(
    db_session, companies, run_worker, failure, monkeypatch
):
    old = "https://stored.example/bad.png"
    bad = companies(logo_status="manual", logo_url=old, logo_evidence={"sha256": "old"})
    good_url = "https://stored.example/good.png"
    good = companies(logo_status="found", logo_url=good_url)
    run_worker.fetcher.image(good_url)
    if failure == "invalid":
        run_worker.fetcher.responses[old] = FetchResult(
            200, old, {"content-type": "image/png"}, b"bad" * 100
        )
    if failure == "upload":
        run_worker.fetcher.image(old)
        original = worker.run_renormalize
        bad_slug = bad.slug

        def failing_upload(session, args, fetcher, uploader):
            def upload(slug, logo):
                if slug == bad_slug:
                    raise RuntimeError("upload failed")
                return uploader(slug, logo)

            return original(session, args, fetcher, upload)

        monkeypatch.setattr(worker, "run_renormalize", failing_upload)
    results = run_worker(renormalize=True)
    db_session.refresh(bad)
    db_session.refresh(good)
    assert any(result.error for result in results)
    assert bad.logo_url == old
    assert bad.logo_evidence == {"sha256": "old"}
    assert bad.logo_status == "manual"
    assert good.logo_url != good_url
    assert len(run_worker.notifications) == 1


def test_renormalize_network_runs_outside_transaction_and_concurrent_change_wins(
    db_session, companies, run_worker, monkeypatch
):
    url = "https://stored.example/race.png"
    company = companies(logo_status="found", logo_url=url, logo_evidence={"sha256": "old"})
    company_id = company.id
    run_worker.fetcher.image(url)
    original = run_worker.fetcher.get

    def concurrent_change(url, *, params=None):
        assert not db_session.in_transaction()
        row = db_session.get(models.Company, company_id)
        row.logo_url = "https://stored.example/manual.png"
        row.logo_status = "manual"
        row.logo_evidence = {"reason": "new manual decision"}
        db_session.commit()
        return original(url, params=params)

    monkeypatch.setattr(run_worker.fetcher, "get", concurrent_change)
    run_worker(renormalize=True)
    db_session.refresh(company)
    assert company.logo_url == "https://stored.example/manual.png"
    assert company.logo_status == "manual"
    assert company.logo_evidence == {"reason": "new manual decision"}
    assert run_worker.notifications == []


def test_renormalize_rejects_offline_mode():
    with pytest.raises(SystemExit):
        worker.parse_args(["--renormalize", "--from-api-json", "companies.json", "--report", "out"])


def test_negative_cache_and_new_hint_retry(db_session, companies, run_worker):
    recent = companies(
        logo_status="not_found", logo_checked_at=datetime.now(UTC) - timedelta(days=10)
    )
    old = companies(logo_status="not_found", logo_checked_at=datetime.now(UTC) - timedelta(days=40))
    reset = companies(
        logo_status="not_found", logo_checked_at=datetime.now(UTC) - timedelta(days=10)
    )
    hint = "https://images.example/new-hint.png"
    resolve_company(db_session, reset.name, logo_hint_url=hint)
    run_worker.fetcher.image(hint)
    rows = worker.select_companies(db_session, worker.parse_args([]), {})
    assert {row[0] for row in rows} == {old.id, reset.id}
    run_worker()
    for company in (recent, old, reset):
        db_session.refresh(company)
    assert recent.logo_checked_at < datetime.now(UTC) - timedelta(days=9)
    assert old.logo_checked_at > datetime.now(UTC) - timedelta(minutes=1)
    assert reset.logo_status == "found"
    assert reset.logo_source == "source_payload"
    assert len(run_worker.uploads) == 1


def test_domain_override_wins_and_manual_is_preserved(db_session, companies, run_worker):
    domain = f"override-{uuid4().hex}.example"
    company = companies(
        domain=f"wrong-{uuid4().hex}.example", logo_hint_url="https://hint.example/logo"
    )
    manual = companies(logo_status="manual", logo_evidence={"reason": "keep this"})
    run_worker.fetcher.homepage(domain)
    override = {"domain": domain}
    run_worker(overrides={company.slug: override}, limit=0)
    db_session.refresh(company)
    db_session.refresh(manual)
    assert company.domain == domain
    assert company.logo_status == "manual"
    assert company.logo_source == "override"
    assert company.logo_evidence["override"] == override
    assert manual.logo_evidence == {"reason": "keep this"}
    assert all("hint.example" not in url for url, _ in run_worker.fetcher.calls)
    assert run_worker.notifications
    run_worker.fetcher.calls.clear()
    assert run_worker(overrides={company.slug: override}) == []
    assert run_worker.fetcher.calls == []


def test_block_override_clears_existing_logo_and_notifies(db_session, companies, run_worker):
    company = companies(logo_url="https://stored.example/old.png", logo_status="found")
    run_worker(overrides={company.slug: {"block": True}})
    db_session.refresh(company)
    assert company.logo_url is None
    assert company.logo_status == "manual"
    assert company.logo_evidence["override"] == {"block": True}
    assert run_worker.fetcher.calls == []
    assert run_worker.uploads == []
    assert run_worker.notifications


def test_image_override_is_validated_and_stored(db_session, companies, run_worker):
    company = companies(logo_status="manual", logo_url="https://stored.example/previous.png")
    url = "https://images.example/manual.png"
    run_worker.fetcher.image(url)
    run_worker(overrides={company.slug: {"logo_url": url}})
    db_session.refresh(company)
    assert company.logo_status == "manual"
    assert company.logo_source == "override"
    assert company.logo_evidence["image_url"] == url
    assert len(run_worker.uploads) == 1


def test_discovered_domain_cache_copies_without_image_fetch(db_session, companies, run_worker):
    domain = f"cache-{uuid4().hex}.example"
    owner = companies(
        active=False,
        domain=domain,
        logo_url="https://stored.example/cached.png",
        logo_status="found",
        logo_evidence={"domain": domain, "sha256": uuid4().hex},
    )
    sibling = companies()
    opportunity = db_session.scalar(
        select(models.Opportunity).where(models.Opportunity.company_id == sibling.id)
    )
    opportunity.description_raw = f"Learn more at https://{domain}"
    run_worker.fetcher.homepage(domain, title=sibling.name)
    run_worker()
    db_session.refresh(sibling)
    assert sibling.logo_url == owner.logo_url
    assert sibling.logo_source == "domain_cache"
    assert sibling.logo_evidence["domain"] == domain
    assert sibling.domain is None
    assert all(url != f"https://{domain}/logo.png" for url, _ in run_worker.fetcher.calls)
    assert run_worker.uploads == []


def test_accepted_unclaimed_domain_is_saved(db_session, companies, run_worker):
    company = companies()
    domain = f"new-{uuid4().hex}.example"
    opportunity = db_session.scalar(
        select(models.Opportunity).where(models.Opportunity.company_id == company.id)
    )
    opportunity.apply_url = f"https://{domain}/careers"
    run_worker.fetcher.homepage(domain, title=company.name)
    run_worker()
    db_session.refresh(company)
    assert company.domain == domain
    assert company.logo_source == "domain_icon"
    assert company.logo_evidence["candidates"][domain]["score"] == 3


def test_parked_trusted_domain_stops_before_discovery(db_session, companies, run_worker):
    domain = f"parked-{uuid4().hex}.example"
    company = companies(domain=domain)
    run_worker.fetcher.homepage(domain, title="Domain is for sale")
    run_worker()
    db_session.refresh(company)
    assert company.logo_status == "not_found"
    assert company.logo_evidence["reason"] == "parked"
    assert [url for url, _ in run_worker.fetcher.calls] == [
        f"https://{domain}/robots.txt",
        f"https://{domain}/",
    ]


def test_generic_post_pass_rejects_three_domains_and_preserves_manual(db_session, companies):
    sha = uuid4().hex
    rows = [
        companies(
            logo_status="found",
            logo_url=f"https://stored.example/{i}.png",
            logo_evidence={"domain": f"generic-{i}-{uuid4().hex}.example", "sha256": sha},
        )
        for i in range(3)
    ]
    manual = companies(
        logo_status="manual",
        logo_url="https://stored.example/manual.png",
        logo_evidence={"sha256": sha},
    )
    changed = worker.generic_post_pass(db_session)
    assert {row.id for row in rows} <= changed
    for row in rows:
        assert row.logo_url is None
        assert row.logo_status == "rejected_generic"
    assert manual.logo_url == "https://stored.example/manual.png"


def test_generic_post_pass_groups_domain_cache_siblings(db_session, companies):
    sha = uuid4().hex
    domain = f"siblings-{uuid4().hex}.example"
    rows = [
        companies(
            logo_status="found",
            logo_url=f"https://stored.example/{i}.png",
            logo_evidence={"domain": host, "sha256": sha},
        )
        for i, host in enumerate((domain, domain, f"other-{uuid4().hex}.example"))
    ]
    changed = worker.generic_post_pass(db_session)
    assert not ({row.id for row in rows} & changed)
    assert all(row.logo_status == "found" and row.logo_url for row in rows)


def test_guard_rejects_third_accept_and_post_pass_clears_first_two(
    db_session, companies, run_worker
):
    rows = []
    for _ in range(3):
        domain = f"default-{uuid4().hex}.example"
        rows.append(companies(domain=domain))
        run_worker.fetcher.homepage(domain)
    results = run_worker()
    for row in rows:
        db_session.refresh(row)
        assert row.logo_status == "rejected_generic"
        assert row.logo_url is None
    assert len(run_worker.uploads) == 2
    assert all(result.status == "rejected_generic" for result in results)


@pytest.mark.parametrize("argv", [[], ["--renormalize"]])
def test_unconfigured_storage_exits_before_engine_and_changes_no_row(
    db_session,
    companies,
    monkeypatch,
    capsys,
    argv,
):
    company = companies()
    db_session.commit()
    settings = Settings(_env_file=None, **{field: "" for field in worker.STORAGE_FIELDS})
    monkeypatch.setattr(worker, "get_settings", lambda: settings)

    def forbidden_engine():
        raise AssertionError("must not create an engine")

    monkeypatch.setattr("core.db.make_engine", forbidden_engine)
    assert worker.main(argv) == 2
    output = capsys.readouterr().out
    assert all(field.upper() in output for field in worker.STORAGE_FIELDS)
    db_session.refresh(company)
    assert company.logo_status is None
    assert company.logo_checked_at is None
    assert company.logo_url is None


def test_dry_run_rolls_back_domains_and_logos(db_session, companies, run_worker):
    domain = f"dry-{uuid4().hex}.example"
    company = companies()
    opportunity = db_session.scalar(
        select(models.Opportunity).where(models.Opportunity.company_id == company.id)
    )
    opportunity.apply_url = f"https://{domain}/careers"
    run_worker.fetcher.homepage(domain, title=company.name)
    run_worker(dry_run=True)
    db_session.refresh(company)
    assert company.domain is None
    assert company.logo_url is None
    assert company.logo_status is None
    assert company.logo_checked_at is None
    assert company.logo_evidence is None
    assert run_worker.uploads == []
    assert run_worker.notifications == []


def test_offline_reports_without_engine_or_upload(tmp_path, monkeypatch, capsys):
    companies = [
        {"slug": "miss", "name": "Missing", "domain": None, "logo_url": None, "active_count": 1},
        {
            "slug": "acme",
            "name": "Acme <test>",
            "domain": "acme.example",
            "logo_url": None,
            "active_count": 10,
        },
    ]
    path = tmp_path / "companies.json"
    path.write_text(json.dumps(companies), encoding="utf-8")
    fetcher = FakeFetcher()
    fetcher.homepage("acme.example")
    monkeypatch.setattr(worker, "HttpFetcher", lambda _client: fetcher)

    def forbidden(*args, **kwargs):
        raise AssertionError("offline mode cannot open a database or upload")

    monkeypatch.setattr("core.db.make_engine", forbidden)
    monkeypatch.setattr(worker, "s3_client", forbidden)
    monkeypatch.setattr(worker, "upload_logo", forbidden)
    report = tmp_path / "report"
    assert worker.main(["--from-api-json", str(path), "--report", str(report)]) == 0
    with (report / "decisions.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert [row["slug"] for row in rows] == ["acme", "miss"]
    assert rows[0]["status"] == "found"
    assert rows[0]["sha256"]
    assert rows[1]["status"] == "not_found"
    sheet = (report / "contact-sheet.html").read_text(encoding="utf-8")
    assert "data:image/png;base64," in sheet
    assert "Acme &lt;test&gt;" in sheet
    assert "no confident domain" in sheet
    assert "Coverage top 100 1/2 companies" in capsys.readouterr().out


def test_offline_generic_guard_counts_distinct_domains(tmp_path):
    fetcher = FakeFetcher()
    companies = []
    for index in range(3):
        domain = f"generic-{index}.example"
        fetcher.homepage(domain)
        companies.append(
            {
                "slug": str(index),
                "name": str(index),
                "domain": domain,
                "logo_url": None,
                "active_count": index + 1,
            }
        )
    path = tmp_path / "companies.json"
    path.write_text(json.dumps(companies), encoding="utf-8")
    report = tmp_path / "report"
    args = worker.parse_args(["--from-api-json", str(path), "--report", str(report)])
    results = worker.run_offline(args, fetcher)
    assert all(result.status == "rejected_generic" for result in results)
    assert "data:image/png;base64," not in (report / "contact-sheet.html").read_text(
        encoding="utf-8"
    )


def test_wikimedia_redirect_keeps_wikidata_source():
    fetcher = FakeFetcher()
    url = worker.wikimedia_logo_url("Example.png")
    fetcher.image(url)
    image = fetcher.responses[url]
    fetcher.responses[url] = FetchResult(
        200, "https://upload.wikimedia.org/example.png", image.headers, image.content
    )
    result = worker.domain_logo(
        fetcher,
        "Example",
        "example.com",
        {},
        lambda _domain: None,
        p154_filename="Example.png",
    )
    assert result.source == "wikidata_logo"
    assert result.evidence["image_url"] == "https://upload.wikimedia.org/example.png"


def test_generic_hint_falls_through_to_valid_domain_icon():
    fetcher = FakeFetcher()
    hint = "https://images.example/default.png"
    fetcher.image(hint)
    generic = worker.best_logo(fetcher, [hint])
    guard = worker.GenericGuard()
    guard.add(generic.sha256, "one.example", "one")
    guard.add(generic.sha256, "two.example", "two")
    fetcher.homepage("acme.example", seed=1)
    result = worker.resolve_logo(
        fetcher,
        "Acme",
        "acme.example",
        hint,
        None,
        lambda: [],
        {},
        lambda _domain: None,
        lambda candidate: worker.guard_outcome(guard, candidate, "three"),
    )
    assert result.status == "found"
    assert result.source == "domain_icon"
    assert result.evidence["sha256"] != generic.sha256
    assert generic.sha256 in guard.rejected


def test_guard_treats_one_brand_as_one_group():
    guard = worker.GenericGuard()
    sha = uuid4().hex
    for domain, name in (
        ("amazon.com", "Amazon"),
        ("aws.amazon.com", "AWS"),
        ("amazon.in", "Amazon India"),
        ("other.com", "Other"),
    ):
        guard.add(sha, domain, name)
    assert sha not in guard.rejected
    guard.add(sha, "third.io", "Third")
    assert sha in guard.rejected


def test_guard_groups_domainless_names_by_first_token():
    guard = worker.GenericGuard()
    crest, placeholder = uuid4().hex, uuid4().hex
    for name in ("IIT Bombay", "IIT Bombay Techfest", "IIT Bombay E-Cell"):
        guard.add(crest, None, name)
    for name in ("Acme", "Globex", "Initech"):
        guard.add(placeholder, None, name)
    assert crest not in guard.rejected
    assert placeholder in guard.rejected


def board_listing(
    company_id=1, name="Acme", domain=None, url="https://jobs.lever.co/acme/job", **kwargs
):
    return worker.BoardListing(
        company_id=company_id,
        name=name,
        domain=domain,
        ats_type=None,
        ats_board_id=None,
        apply_url=url,
        primary_source=None,
        source_url=None,
        source_slug=None,
        **kwargs,
    )


def test_own_board_rejects_other_brands_even_if_their_board_is_ambiguous():
    rows = [
        board_listing(),
        board_listing(2, "Other"),
        board_listing(2, "Other", url="https://jobs.ashbyhq.com/other/job"),
    ]
    assert worker.own_company_boards(rows) == {}


def test_own_board_allows_sibling_brands_and_non_ats_listings():
    rows = [
        board_listing(domain="acme.com"),
        board_listing(2, "Acme India", "acme.in"),
        board_listing(url="https://acme.com/careers"),
    ]
    assert worker.own_company_boards(rows) == {
        1: "https://jobs.lever.co/acme",
        2: "https://jobs.lever.co/acme",
    }
    assert worker.own_company_boards([board_listing(), board_listing(2, "Acme Labs")]) == {
        1: "https://jobs.lever.co/acme",
        2: "https://jobs.lever.co/acme",
    }


@pytest.mark.parametrize(
    "other_url",
    [
        "https://jobs.lever.co/other/job",
        "https://acme.workable.com/jobs/123",
        "https://jobs.lever.co/",
    ],
)
def test_own_board_requires_all_ats_listings_to_identify_the_same_board(other_url):
    assert worker.own_company_boards([board_listing(), board_listing(url=other_url)]) == {}


def test_board_id_without_an_active_listing_is_not_ownership_evidence():
    assert worker.own_company_boards([]) == {}
    row = worker.BoardListing(
        1, "Acme", None, "lever", "acme", "https://acme.com/jobs/1", "lever", None, None
    )
    assert worker.own_company_boards([row]) == {1: "https://jobs.lever.co/acme"}
    # A configured board may not be borrowed by an unrelated aggregator listing.
    row = worker.BoardListing(
        1, "Acme", None, "lever", "acme", "https://github.com/list/jobs", "github", None, None
    )
    assert worker.own_company_boards([row]) == {}


def test_ats_fallback_uses_ashby_square_svg_and_preserves_source_priority():
    fetcher = FakeFetcher()
    fixtures = Path(__file__).parent / "fixtures/logos"
    board = "https://jobs.ashbyhq.com/saronic"
    image = "https://cdn.example/saronic-square.png"
    fetcher.responses[board] = FetchResult(
        200, board, {}, (fixtures / "board_ashby.html").read_bytes()
    )
    fetcher.responses[image] = FetchResult(
        200, image, {"content-type": "image/png"}, (fixtures / "board_square.svg").read_bytes()
    )
    result = worker.resolve_logo(
        fetcher, "Saronic", None, None, None, lambda: [], {}, lambda _: None, board=board
    )
    assert result.source == "ats_board" and result.logo is not None
    assert result.evidence["board"] == board
    assert result.evidence["image_url"] == image
    assert result.evidence["sha256"] == result.logo.sha256
    assert (image, MAX_ATS_BODY_BYTES) in fetcher.limits
    fetcher.calls.clear()
    hint = "https://images.example/logo.png"
    fetcher.image(hint)
    result = worker.resolve_logo(
        fetcher, "Saronic", None, hint, None, lambda: [], {}, lambda _: None, board=board
    )
    assert result.source == "source_payload"
    assert fetcher.calls == [(hint, None)]
    fetcher.calls.clear()
    result = worker.resolve_logo(
        fetcher, "Saronic", None, hint, {"block": True}, lambda: [], {}, lambda _: None, board=board
    )
    assert not result.found and fetcher.calls == []


def test_generic_ats_logo_is_rejected():
    fetcher = FakeFetcher()
    board = "https://acme.wd1.myworkdayjobs.com/Jobs"
    fetcher.image(board + "/assets/logo")
    logo = worker.best_logo(fetcher, [board + "/assets/logo"])
    guard = worker.GenericGuard()
    guard.add(logo.sha256, None, "One")
    guard.add(logo.sha256, None, "Two")
    result = worker.resolve_logo(
        fetcher,
        "Three",
        None,
        None,
        None,
        lambda: [],
        {},
        lambda _: None,
        lambda candidate: worker.guard_outcome(guard, candidate, "Three"),
        board=board,
    )
    assert result.status == "rejected_generic" and not result.found


@pytest.mark.parametrize("final_domain,accepted", [("notion.com", True), ("unrelated.com", False)])
def test_trusted_homepage_redirect_uses_final_domain_icons(final_domain, accepted):
    fetcher = FakeFetcher()
    fetcher.responses["https://notion.so/"] = FetchResult(
        200, f"https://{final_domain}/", {}, b"<title>Notion</title>"
    )
    fetcher.image(f"https://{final_domain}/apple-touch-icon.png")
    result = worker.domain_logo(fetcher, "Notion", "notion.so", {}, lambda _: None)
    assert result.found == accepted
    assert result.domain == "notion.so"
    if accepted:
        assert result.evidence["image_url"] == "https://notion.com/apple-touch-icon.png"
        assert not any("notion.so/apple" in url for url, _ in fetcher.calls)
    else:
        assert result.evidence["reason"] == "homepage redirected off domain"
        assert not any("apple-touch" in url for url, _ in fetcher.calls)


def test_trusted_domain_wordmark_requires_matching_official_website(monkeypatch):
    fetcher = FakeFetcher()
    image = worker.wikimedia_logo_url("Acme.svg")
    fetcher.image(image)
    candidates = [Candidate("other.example", {"wikidata"}, "Acme.svg")]
    monkeypatch.setattr(worker, "wikidata_candidates", lambda *_: candidates)
    assert not worker.domain_logo(fetcher, "Acme", "acme.example", {}, lambda _: None).found
    assert (image, None) not in fetcher.calls
    candidates[0].domain = "acme.example"
    assert (
        worker.domain_logo(fetcher, "Acme", "acme.example", {}, lambda _: None).source
        == "wikidata_logo"
    )


def test_forced_recheck_selects_all_missing_statuses_but_preserves_blocks(
    db_session, companies, run_worker
):
    rows = [
        companies(logo_status=status, logo_checked_at=datetime.now(UTC))
        for status in ("not_found", "ambiguous", "error", "manual")
    ]
    blocked = companies(logo_status="manual", logo_evidence={"override": {"block": True}})
    stored = companies(logo_status="manual", logo_url="https://stored.example/keep.png")
    manual = rows[-1]
    override = {"domain": f"retry-{uuid4().hex}.example"}
    manual.logo_evidence = {"override": override}
    overrides = {manual.slug: override, blocked.slug: {"block": True}}
    selected = worker.select_companies(
        db_session, worker.parse_args(["--recheck-days", "0"]), overrides
    )
    assert {row[0] for row in selected} == {company.id for company in rows}
    assert worker.select_companies(db_session, worker.parse_args([]), overrides) == []
    run_worker.fetcher.homepage(override["domain"])
    run_worker(overrides=overrides, recheck_days=0)
    db_session.refresh(manual)
    db_session.refresh(blocked)
    db_session.refresh(stored)
    assert manual.logo_url and manual.logo_status == "manual"
    assert blocked.logo_url is None
    assert stored.logo_url == "https://stored.example/keep.png"


@pytest.mark.parametrize("dry_run", [False, True])
def test_worker_uses_listing_board_and_prints_image_url(
    db_session, companies, run_worker, capsys, dry_run
):
    company = companies()
    opportunity = db_session.scalar(
        select(models.Opportunity).where(models.Opportunity.company_id == company.id)
    )
    opportunity.apply_url = "https://acme.wd1.myworkdayjobs.com/en-US/Jobs/job/123"
    image = "https://acme.wd1.myworkdayjobs.com/Jobs/assets/logo"
    run_worker.fetcher.image(image)
    result = run_worker(dry_run=dry_run)[0]
    assert result.source == "ats_board"
    assert f"image_url={image}" in capsys.readouterr().out
    db_session.refresh(company)
    assert bool(company.logo_url) != dry_run


def test_ownership_map_includes_secondary_source_urls(db_session, companies):
    company = companies()
    opportunity = db_session.scalar(
        select(models.Opportunity).where(models.Opportunity.company_id == company.id)
    )
    source = models.Source(slug=f"test-logos-{uuid4().hex}", name="Logo fixture")
    db_session.add(source)
    db_session.flush()
    db_session.add(
        models.OpportunitySource(
            opportunity_id=opportunity.id,
            source_id=source.id,
            source_url="https://boards.greenhouse.io/acme/jobs/123",
        )
    )
    db_session.flush()
    assert (
        worker.load_company_boards(db_session)[company.id]
        == "https://job-boards.greenhouse.io/acme"
    )
