"""Guard that prevents digest sends with an API/worker signing-key mismatch."""

from types import SimpleNamespace

import httpx
import pytest

from scripts import check_unsubscribe_key as checker


@pytest.fixture(autouse=True)
def _configured_local_key(monkeypatch):
    monkeypatch.setattr(checker, "key_fingerprint", lambda: "aaaaaaaaaaaa")
    monkeypatch.setattr(
        checker,
        "get_settings",
        lambda: SimpleNamespace(api_base_url="https://api.example.test"),
    )


def test_matching_fingerprint_exits_zero(monkeypatch, capsys):
    def matching_health(url: str, *, timeout: float) -> httpx.Response:
        assert url == "https://api.example.test/health"
        assert timeout == checker._TIMEOUT_SECONDS
        return httpx.Response(200, json={"unsubscribe_key": "aaaaaaaaaaaa"})

    monkeypatch.setattr(checker.httpx, "get", matching_health)

    assert checker.check_unsubscribe_key() == 0
    assert "matches API" in capsys.readouterr().out


def test_mismatched_fingerprint_prints_both_and_exits_one(monkeypatch, capsys):
    monkeypatch.setattr(
        checker.httpx,
        "get",
        lambda *_args, **_kwargs: httpx.Response(200, json={"unsubscribe_key": "bbbbbbbbbbbb"}),
    )

    assert checker.check_unsubscribe_key() == 1
    output = capsys.readouterr().out
    assert "local=aaaaaaaaaaaa" in output
    assert "api=bbbbbbbbbbbb" in output


def test_unreachable_api_warns_and_exits_zero(monkeypatch, capsys):
    request = httpx.Request("GET", "https://api.example.test/health")

    def unreachable(*_args, **_kwargs):
        raise httpx.ConnectError("unreachable", request=request)

    monkeypatch.setattr(checker.httpx, "get", unreachable)

    assert checker.check_unsubscribe_key() == 0
    assert "WARNING" in capsys.readouterr().out


def test_non_200_api_warns_and_exits_zero(monkeypatch, capsys):
    monkeypatch.setattr(
        checker.httpx,
        "get",
        lambda *_args, **_kwargs: httpx.Response(503),
    )

    assert checker.check_unsubscribe_key() == 0
    assert "HTTP 503" in capsys.readouterr().out


def test_missing_health_field_warns_and_exits_zero(monkeypatch, capsys):
    monkeypatch.setattr(
        checker.httpx,
        "get",
        lambda *_args, **_kwargs: httpx.Response(200, json={"status": "ok"}),
    )

    assert checker.check_unsubscribe_key() == 0
    assert "no unsubscribe_key" in capsys.readouterr().out


def test_empty_api_fingerprint_is_a_known_mismatch(monkeypatch, capsys):
    monkeypatch.setattr(
        checker.httpx,
        "get",
        lambda *_args, **_kwargs: httpx.Response(200, json={"unsubscribe_key": ""}),
    )

    assert checker.check_unsubscribe_key() == 1
    assert "api=" in capsys.readouterr().out


def test_empty_local_fingerprint_exits_one_without_http(monkeypatch, capsys):
    monkeypatch.setattr(checker, "key_fingerprint", lambda: "")

    def unexpected_request(*_args, **_kwargs):
        raise AssertionError("an empty local key must fail before the HTTP request")

    monkeypatch.setattr(checker.httpx, "get", unexpected_request)

    assert checker.check_unsubscribe_key() == 1
    assert "no local unsubscribe signing key" in capsys.readouterr().out
