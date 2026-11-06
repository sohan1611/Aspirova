"""Programme/external logo reads and worker integration with no DB or network."""

from collections import namedtuple
from contextlib import nullcontext
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.dialects import postgresql

from api import company as company_api
from api import programmes as programmes_api
from api.deps import get_db
from core import models
from pipeline import organiser_companies
from pipeline.company_logos import FetchResult
from pipeline.normalize import normalize_company_name
from scripts import logo_worker as worker


@pytest.fixture(scope="session", autouse=True)
def _purge_isolation_test_residue():
    """Override the shared DB cleanup for this entirely in-memory module."""


def company_row(**values):
    return models.Company(
        id=7,
        slug="acme-research",
        name="Acme Research",
        name_normalized="acme research",
        **values,
    )


def programme_row(company=None):
    return models.Programme(
        id=11,
        slug="acme-summer",
        name="Summer Research",
        organiser="Acme Research",
        company=company,
        category="research_internship",
        url="https://acme.example/summer",
        tags=["research"],
        editions=[],
        is_active=True,
    )


def sql(query):
    return str(query.compile(dialect=postgresql.dialect()))


@pytest.mark.parametrize("linked", [False, True])
def test_programme_list_and_detail_expose_stored_company(linked):
    company = company_row(domain="acme.example", logo_url="https://logos.example/acme.png")
    programme = programme_row(company if linked else None)
    Row = namedtuple("Row", "programme edition total_count match_count")
    db = Mock()
    db.execute.return_value.all.return_value = [Row(programme, None, 1, 0)]
    db.scalar.return_value = programme
    app = FastAPI()
    app.include_router(programmes_api.router)
    app.dependency_overrides[get_db] = lambda: db

    with TestClient(app) as client:
        listing = client.get("/programmes?category=research_internship")
        detail = client.get("/programme/acme-summer")

    assert listing.status_code == detail.status_code == 200
    expected = (
        {
            "slug": company.slug,
            "name": company.name,
            "domain": company.domain,
            "logo_url": company.logo_url,
        }
        if linked
        else None
    )
    assert listing.json()["items"][0]["company"] == expected
    assert detail.json()["company"] == expected
    # Eager joins keep company logos in the read query, including legacy NULL links.
    assert "LEFT OUTER JOIN companies" in sql(db.execute.call_args.args[0])
    assert "LEFT OUTER JOIN companies" in sql(db.scalar.call_args.args[0])
    db.add.assert_not_called()
    db.commit.assert_not_called()


def test_external_api_uses_exact_canonical_name_without_active_listings():
    company = models.Company(
        slug="google-canonical",
        name="Google",
        name_normalized=normalize_company_name("Google"),
        domain="google.com",
        logo_url="https://logos.example/google.png",
    )
    db = Mock()
    db.scalars.return_value.all.return_value = [company]
    app = FastAPI()
    app.include_router(company_api.router)
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        response = client.get("/companies/external")
    assert response.status_code == 200
    assert response.json()["google"]["logo_url"] == company.logo_url
    assert response.json()["google"]["slug"] == company.slug
    assert "apple" not in response.json()
    assert "opportunities" not in sql(db.scalars.call_args.args[0])
    db.add.assert_not_called()


def test_backfill_links_programmes_with_existing_resolver(monkeypatch):
    programme = programme_row()
    existing = programme_row()
    existing.company_id = 99
    db = Mock()
    db.scalars.return_value = [programme, existing]
    resolver = Mock(return_value=company_row())
    monkeypatch.setattr(organiser_companies, "resolve_company", resolver)

    organiser_companies.link_organiser_companies(db)
    assert programme.company_id == 7
    assert existing.company_id == 99
    assert resolver.call_args_list[-1].args == (db, programme.organiser)
    assert (db, "Google", "google.com") in [call.args for call in resolver.call_args_list]
    # Authored programme URLs never become trusted organiser domains.
    assert all(programme.url not in call.args for call in resolver.call_args_list)
    resolver.reset_mock()
    organiser_companies.link_organiser_companies(db)
    assert resolver.call_count == len(organiser_companies.EXTERNAL_COMPANIES)
    db.commit.assert_not_called()


def test_selection_includes_programme_and_external_companies_with_retry_rules():
    db = Mock()
    db.execute.return_value.all.return_value = []
    args = SimpleNamespace(recheck_days=30, limit=25)
    assert worker.select_companies(db, args, {}) == []
    query = db.execute.call_args.args[0]
    compiled = query.compile(dialect=postgresql.dialect())
    text = str(compiled)
    assert "LEFT OUTER JOIN" in text
    assert "EXISTS (SELECT programmes.id" in text
    assert "programmes.company_id = companies.id" in text
    assert "programmes.is_active IS true" in text
    assert "companies.logo_url IS NULL" in text
    assert "companies.logo_status IS DISTINCT FROM" in text
    assert "companies.logo_checked_at <" in text
    assert [
        normalize_company_name(entry["name"]) for entry in organiser_companies.EXTERNAL_COMPANIES
    ] in compiled.params.values()


def test_programme_urls_join_existing_listing_evidence():
    db = Mock()
    db.execute.return_value.all.return_value = [("https://jobs.example/apply", "Research role")]
    db.scalars.return_value.all.return_value = ["https://acme.example/summer"]
    assert worker.recent_listing_texts(db, 7) == [
        "https://jobs.example/apply\nResearch role",
        "https://acme.example/summer",
    ]
    query = sql(db.scalars.call_args.args[0])
    assert "programmes.company_id" in query
    assert "programmes.is_active IS true" in query


@pytest.mark.parametrize(
    "status,logo_url",
    [("not_found", None), ("manual", None), ("found", "https://logos.example/saved.png")],
)
def test_new_programme_evidence_resets_only_unsaved_nonmanual_logos(monkeypatch, status, logo_url):
    company = company_row(logo_status=status, logo_url=logo_url)
    programme = programme_row()
    monkeypatch.setattr(organiser_companies, "resolve_company", lambda *_: company)
    organiser_companies.link_programme_company(Mock(), programme)
    assert programme.company_id == company.id
    assert company.logo_status == (None if status == "not_found" else status)
    assert company.logo_url == logo_url
    company.logo_status = status
    # Re-linking unchanged data preserves the negative cache.
    organiser_companies.link_programme_company(Mock(), programme)
    assert company.logo_status == status
    organiser_companies.link_programme_company(Mock(), programme, evidence_changed=True)
    assert company.logo_status == (None if status == "not_found" else status)


class ScalarRows(list):
    def all(self):
        return self


class FakeFetcher:
    def __init__(self):
        self.calls = []
        output = BytesIO()
        image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        for x in range(16, 48):
            for y in range(16, 48):
                image.putpixel((x, y), (30, 80, 160, 255))
        image.save(output, format="PNG")
        self.responses = {
            "https://acme.example/": FetchResult(
                200,
                "https://acme.example/",
                {},
                b'<title>Acme Research</title><link rel="icon" href="/icon.png">',
            ),
            "https://acme.example/icon.png": FetchResult(
                200,
                "https://acme.example/icon.png",
                {"content-type": "image/png"},
                output.getvalue(),
            ),
        }

    def get(self, url, *, params=None):
        self.calls.append(url)
        return self.responses.get(url)


@pytest.mark.parametrize("dry_run", [False, True])
def test_worker_reuses_storage_pipeline_and_keeps_dry_run_write_free(monkeypatch, dry_run):
    company = company_row()
    db = Mock()
    db.get.return_value = company
    db.scalars.return_value = ScalarRows()
    db.scalar.return_value = None
    db.begin_nested.side_effect = lambda: nullcontext()
    backfill = Mock()
    notify = Mock()
    monkeypatch.setattr(organiser_companies, "link_organiser_companies", backfill)
    monkeypatch.setattr(worker, "select_companies", lambda *_: [(company.id, 0)])
    monkeypatch.setattr(worker, "recent_listing_texts", lambda *_: ["https://acme.example/summer"])
    monkeypatch.setattr(worker, "generic_post_pass", lambda *_: set())
    monkeypatch.setattr(worker, "print_missing", lambda *_: None)
    from pipeline import revalidate

    monkeypatch.setattr(revalidate, "notify_changed", notify)
    args = SimpleNamespace(dry_run=dry_run, time_budget_min=1)
    fetcher = FakeFetcher()
    uploader = Mock(return_value="https://logos.example/acme.png")

    result = worker.run_db(db, args, fetcher, {}, uploader)[0]
    assert result.status == "found"
    assert result.domain == "acme.example"
    assert result.evidence["candidates"]["acme.example"]["score"] == 3
    if dry_run:
        backfill.assert_not_called()
        uploader.assert_not_called()
        db.commit.assert_not_called()
        db.flush.assert_not_called()
        assert company.logo_url is None
    else:
        backfill.assert_called_once_with(db)
        uploader.assert_called_once()
        png = uploader.call_args.args[1].png_bytes
        assert Image.open(BytesIO(png)).size == (128, 128)
        assert company.logo_url == "https://logos.example/acme.png"
        fetcher.calls.clear()
        uploader.reset_mock()
        # Even a stale selection cannot make a stored programme logo search again.
        assert worker.run_db(db, args, fetcher, {}, uploader) == []
        assert fetcher.calls == []
        uploader.assert_not_called()


def test_programme_url_alone_cannot_bypass_discovery_threshold():
    result = worker.resolve_logo(
        FakeFetcher(),
        "Unrelated Foundation",
        None,
        None,
        None,
        lambda: ["https://acme.example/summer"],
        {},
        lambda _: None,
    )
    assert result.status == "not_found"
    assert result.logo is None
    assert result.evidence["candidates"]["acme.example"]["score"] == 2
