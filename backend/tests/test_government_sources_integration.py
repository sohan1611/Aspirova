"""Registry/seed/probe integration with fixture HTTP and disposable PostgreSQL."""

import json
from pathlib import Path

import httpx
import pytest

from api.filters import SOURCE_GROUPS
from core import models
from core.organisers import classify_organiser
from crawlers import runner
from crawlers.runner import AGGREGATOR_ADAPTERS, AGGREGATOR_SOURCE_RESERVE_SECONDS
from pipeline.expire import FULL_INVENTORY_SOURCES
from pipeline.retirement import GOVERNMENT_NOTICE_SOURCES, ROLLING_WINDOW_TTL_DAYS
from scripts import probe_sources, seed_companies
from tests.test_government_adapters import ADAPTERS, NOW, PATHS, fixture
from tests.test_audit_retirement import db_session as db_session


def test_registered_budgeted_seeded_and_no_absence_retirement(monkeypatch, capsys):
    rows = []

    class Session:
        def __init__(self, *args):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def scalar(self, query):
            return None

        def add(self, row):
            rows.append(row)

        def commit(self):
            pass

    monkeypatch.setattr(seed_companies, "make_engine", lambda: None)
    monkeypatch.setattr(seed_companies, "Session", Session)
    seed_companies.seed(sources_only=True)
    assert FULL_INVENTORY_SOURCES == {"unstop", "devpost", "devfolio", "github_lists"}
    assert GOVERNMENT_NOTICE_SOURCES == {cls.source_slug for cls in ADAPTERS}
    for cls in ADAPTERS:
        slug = cls.source_slug
        assert AGGREGATOR_ADAPTERS[slug] is cls
        assert probe_sources.ADAPTERS[slug] is cls
        assert AGGREGATOR_SOURCE_RESERVE_SECONDS[slug] > 0
        assert slug in SOURCE_GROUPS["direct"]
        assert ROLLING_WINDOW_TTL_DAYS[slug] == 45
        row = next(row for row in rows if row.slug == slug)
        assert isinstance(row, models.Source)
        assert row.adapter_key == slug
        assert row.crawl_tier == 1
        assert row.enabled is (slug not in {"meity_careers", "nic_dii", "drdo"})
        assert row.legal_status == "ok"
        assert row.type == "aggregator"
    assert all(not isinstance(row, models.Company) for row in rows)
    reason = (
        "WAF returns HTTP 403 to the AspirovaBot User-Agent (verified 2026-11-13); "
        "re-enable only if MeitY allows our identity"
    )
    us_blocked = "unreachable from GitHub Actions US runners (verified 2026-11-13)"
    assert seed_companies._DISABLED_AGGREGATORS == {
        "meity_careers": reason,
        "nic_dii": us_blocked,
        "drdo": us_blocked,
    }
    assert f"created source: meity_careers (disabled: {reason})" in capsys.readouterr().out


@pytest.mark.parametrize("enabled", [True, False])
def test_seed_preserves_existing_meity_row(monkeypatch, enabled):
    existing = models.Source(
        slug="meity_careers", adapter_key="meity_careers", enabled=enabled, legal_status="blocked"
    )

    class Session:
        def __init__(self, *args):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def scalar(self, query):
            return existing

        def add(self, row):
            pytest.fail("existing source must not be recreated")

        def commit(self):
            pass

    monkeypatch.setattr(seed_companies, "make_engine", lambda: None)
    monkeypatch.setattr(seed_companies, "Session", Session)
    monkeypatch.setattr(seed_companies, "_ADAPTER_SOURCES", {})
    monkeypatch.setattr(
        seed_companies,
        "_AGGREGATOR_SOURCES",
        {"meity_careers": seed_companies._AGGREGATOR_SOURCES["meity_careers"]},
    )
    seed_companies.seed(sources_only=True)
    assert existing.enabled is enabled
    assert existing.legal_status == "blocked"


def test_runner_skips_disabled_government_source(db_session, monkeypatch):
    # A distinct fixture tier isolates the real selection query from other
    # local test rows. Keep an enabled government source as a positive control.
    disabled = models.Source(
        slug="test-disabled-meity",
        adapter_key="meity_careers",
        type="aggregator",
        crawl_tier=32000,
        enabled=False,
        legal_status="ok",
    )
    enabled = models.Source(
        slug="test-enabled-nic",
        adapter_key="nic_dii",
        type="aggregator",
        crawl_tier=32000,
        enabled=True,
        legal_status="ok",
    )
    db_session.add_all([disabled, enabled])
    db_session.flush()
    crawled = []

    def crawl(session, source, adapter_class, **kwargs):
        crawled.append(source.adapter_key)
        return {}

    monkeypatch.setattr(runner, "make_engine", db_session.get_bind)
    monkeypatch.setattr(runner, "verify_connection_guards", lambda _engine: None)
    monkeypatch.setattr(runner, "crawl_aggregator", crawl)
    monkeypatch.setattr(runner, "_refresh_prestige_matches", lambda _engine: None)
    monkeypatch.setattr(runner, "notify_changed", lambda _slugs: None)
    runner.run_tier(32000, group="aggregator", should_stop=lambda: False)
    assert crawled == ["nic_dii"]


@pytest.mark.parametrize(
    "name",
    [
        "Ministry of Electronics and Information Technology",
        "National Informatics Centre",
        "North Eastern Council",
        "DRDO – DGRE",
        "ISRO – U. R. Rao Satellite Centre",
        "Defence Research and Development Organisation",
        "Indian Space Research Organisation",
        "National e-Governance Division",
        "Digital India Corporation",
    ],
)
def test_precise_government_organisers(name):
    assert classify_organiser(name) == "government"


@pytest.mark.parametrize(
    "name",
    [
        "ISROCKET Labs",
        "DRDON Technologies",
        "NIC Technologies",
        "NEC Corporation",
        "Council Software",
    ],
)
def test_government_names_do_not_overmatch(name):
    assert classify_organiser(name) != "government"


def test_probe_uses_fixtures_and_needs_no_db_settings(monkeypatch, capsys):
    from crawlers import government as gov

    original_init = gov.GovernmentAdapter.__init__

    def respond(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text=fixture(PATHS[request.url.path]))

    def init(self, *args, **kwargs):
        original_init(self, *args, now=lambda: NOW, **kwargs)
        self._client.close()
        self._client = httpx.Client(transport=httpx.MockTransport(respond))

    monkeypatch.setattr(gov.GovernmentAdapter, "__init__", init)
    monkeypatch.setattr(gov, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        seed_companies, "make_engine", lambda: pytest.fail("probe attempted database access")
    )
    for key in (
        "DATABASE_URL",
        "SUPABASE_URL",
        "SUPABASE_ANON_KEY",
        "SUPABASE_SERVICE_KEY",
        "CORS_ORIGINS",
    ):
        monkeypatch.delenv(key, raising=False)
    assert probe_sources.main(["--source", ",".join(probe_sources.ADAPTERS)]) == 0
    results = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [row["source"] for row in results] == list(probe_sources.ADAPTERS)
    assert all(row["health"] == "ok" and row["parsed"] > 0 for row in results)
    assert all(row["coverage"]["status"] == "complete" and row["counts"] for row in results)
    assert all(row["sample"][0]["deadline"] for row in results)


def test_probe_unknown_source_is_rejected():
    with pytest.raises(SystemExit) as error:
        probe_sources.main(["--source", "not-a-source"])
    assert error.value.code == 2


def test_workflow_is_manual_us_runner_and_secret_free():
    workflow = (Path(__file__).parents[2] / ".github/workflows/probe-sources.yml").read_text()
    assert "workflow_dispatch:" in workflow
    assert "sources:" in workflow
    assert "runs-on: ubuntu-latest" in workflow
    assert "secrets." not in workflow
    assert '"$PROBE_SOURCES"' in workflow
