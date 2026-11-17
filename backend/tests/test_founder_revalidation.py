"""Founder command order and dry-run isolation without a database or live HTTP."""

from types import SimpleNamespace

import pytest

from pipeline import revalidate
from scripts import flag_listing as flag_cli
from scripts import reports as report_cli


class FakeSession:
    def __init__(self, events):
        self.events = events

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def commit(self):
        self.events.append("commit")

    def rollback(self):
        self.events.append("rollback")

    def scalar(self, query):
        return SimpleNamespace(status="withdrawn", closed_at=None)


def command_setup(monkeypatch, module, *, changed=True):
    events = []
    engine = SimpleNamespace(dispose=lambda: None)
    monkeypatch.setattr(module, "make_engine", lambda: engine)
    monkeypatch.setattr(module, "Session", lambda _: FakeSession(events))
    if module is flag_cli:
        monkeypatch.setattr(module, "flag_listing", lambda *a, **kw: changed)
    else:
        monkeypatch.setattr(module, "resolve_report", lambda *a, **kw: (None, "role", changed))
        monkeypatch.setattr(module, "triage_report", lambda *a, **kw: changed)
        monkeypatch.setattr(module, "send_resolution_email", lambda *a: False)
    return events


def cache_callbacks(monkeypatch, module, events, *, status="ok"):
    def refresh(slugs):
        assert slugs == ["role"]
        events.append("refresh")
        return {"status": "ok", "refreshed": 1}

    def notify(slugs, *, landing):
        assert slugs == ["role"] and landing is False
        events.append("notify")
        return {"status": status, "notified": 1}

    monkeypatch.setattr(module, "refresh_api_details", refresh)
    monkeypatch.setattr(module, "notify_changed", notify)


@pytest.mark.parametrize("mode", ["scam", "recalled", "clear"])
@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.parametrize("changed", [False, True])
def test_flag_and_clear_commit_then_refresh_then_detail_revalidation(
    monkeypatch, mode, dry_run, changed, capsys
):
    events = command_setup(monkeypatch, flag_cli, changed=changed)
    cache_callbacks(monkeypatch, flag_cli, events, status="unconfigured")
    args = (
        ["--slug", "role", "--clear"]
        if mode == "clear"
        else ["--slug", "role", "--kind", mode, "--note", "Checked"]
    )
    if dry_run:
        args.append("--dry-run")
    flag_cli.main(args)
    output = capsys.readouterr().out
    assert events == (["rollback"] if dry_run else ["commit", "refresh", "notify"])
    assert output.count(revalidate.LOCAL_REVALIDATION_WARNING) == (0 if dry_run else 1)
    if not dry_run:
        assert "API refresh:" in output and "Frontend revalidation:" in output


@pytest.mark.parametrize(
    "action",
    [
        ["--close-listing"],
        ["--set-deadline", "2026-12-15"],
        ["--withdraw", "--kind", "scam"],
        ["--duplicate-of", "original"],
        ["--company", "correct-company"],
    ],
)
@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.parametrize("changed", [False, True])
def test_report_listing_actions_refresh_after_commit(monkeypatch, action, dry_run, changed, capsys):
    events = command_setup(monkeypatch, report_cli, changed=changed)
    cache_callbacks(monkeypatch, report_cli, events, status="unconfigured")
    args = ["resolve", "R-ABC234", "--resolution", "corrected", "--note", "Checked", *action]
    if dry_run:
        args.append("--dry-run")
    report_cli.main(args)
    output = capsys.readouterr().out
    expected = ["rollback"] if dry_run else ["commit", "refresh", "notify"]
    if changed and not dry_run:
        expected.append("commit")  # release the post-delivery recipient lock
    assert events == expected
    assert output.count(revalidate.LOCAL_REVALIDATION_WARNING) == (0 if dry_run else 1)
    if not dry_run:
        assert '"api_refresh"' in output and '"revalidation"' in output


@pytest.mark.parametrize("command", ["triage", "resolve"])
def test_report_only_updates_do_not_refresh_listings(monkeypatch, command, capsys):
    events = command_setup(monkeypatch, report_cli)
    monkeypatch.setattr(
        report_cli, "refresh_api_details", lambda *a: pytest.fail("No listing changed")
    )
    monkeypatch.setattr(
        report_cli, "notify_changed", lambda *a, **kw: pytest.fail("No listing changed")
    )
    args = [command, "R-ABC234"]
    if command == "resolve":
        args.extend(["--resolution", "no_change", "--note", "Checked"])
    report_cli.main(args)
    output = capsys.readouterr().out
    assert "refresh" not in events and "notify" not in events
    assert revalidate.LOCAL_REVALIDATION_WARNING not in output


@pytest.mark.parametrize("module", [flag_cli, report_cli])
def test_founder_command_http_order_is_refresh_before_slug_only_post(monkeypatch, module):
    events = command_setup(monkeypatch, module, changed=False)
    monkeypatch.setattr(
        revalidate,
        "get_settings",
        lambda: SimpleNamespace(
            api_base_url="https://api.example",
            revalidate_url="",
            revalidate_secret="",
        ),
    )
    monkeypatch.setenv("REVALIDATE_URL", "https://frontend.example/api/revalidate")
    monkeypatch.setenv("REVALIDATE_SECRET", "test-only")

    def get(url, **kwargs):
        assert url == "https://api.example/opportunity/role"
        assert kwargs["headers"] == {"X-Aspirova-Refresh": "1"}
        events.append("GET detail")
        return SimpleNamespace(raise_for_status=lambda: None)

    def post(url, **kwargs):
        assert kwargs["json"] == {"slugs": ["role"]}
        events.append("POST slug")
        return SimpleNamespace(raise_for_status=lambda: None)

    monkeypatch.setattr(revalidate.httpx, "get", get)
    monkeypatch.setattr(revalidate.httpx, "post", post)
    if module is flag_cli:
        flag_cli.main(["--slug", "role", "--kind", "scam", "--note", "Checked"])
    else:
        report_cli.main(
            [
                "resolve",
                "R-ABC234",
                "--resolution",
                "corrected",
                "--note",
                "Checked",
                "--set-deadline",
                "2026-12-15",
            ]
        )
    assert events == ["commit", "GET detail", "POST slug"]
