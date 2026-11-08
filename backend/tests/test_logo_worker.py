"""Worker DB transactions and offline review with injected HTTP and storage."""

import csv
import json
import random
from datetime import UTC, datetime, timedelta
from io import BytesIO
from uuid import uuid4

import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from core import models
from core.config import Settings
from pipeline.company_logos import FetchResult
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

    def get(self, url, *, params=None):
        self.calls.append((url, params))
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

    def run(*, overrides=None, dry_run=False, limit=1500, time_budget_min=45):
        # Persist fixtures into the outer transaction, which the fixture alone
        # owns. Worker commits and rollbacks only release its own savepoints.
        db_session.commit()
        args = worker.parse_args(["--limit", str(limit), "--time-budget-min", str(time_budget_min)])
        args.dry_run = dry_run
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


def test_unconfigured_storage_exits_before_engine_and_changes_no_row(
    db_session,
    companies,
    monkeypatch,
    capsys,
):
    company = companies()
    db_session.commit()
    settings = Settings(_env_file=None, **{field: "" for field in worker.STORAGE_FIELDS})
    monkeypatch.setattr(worker, "get_settings", lambda: settings)

    def forbidden_engine():
        raise AssertionError("must not create an engine")

    monkeypatch.setattr("core.db.make_engine", forbidden_engine)
    assert worker.main([]) == 2
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
