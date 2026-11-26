"""Bounded destination observations, used only by the existing liveness job."""

import re
import socket
from html import unescape
from datetime import datetime, timezone
from ipaddress import ip_address
from time import monotonic
from typing import Callable
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx

from core.destination_facts import (
    ATS,
    ats_board,
    board_matches_company,
    matches,
    public_host,
    registrable_domain,
    url_key,
)

MAX_REDIRECT_HOPS = 5
MAX_BODY_BYTES = 65536
MAX_CHECK_SECONDS = 20
_LOGIN = re.compile(r"(?:^|/)(?:login|log-in|signin|sign-in|sign_in|auth|sso)(?:[./]|$)", re.I)
_LOGIN_HOST = re.compile(r"(?:^|\.)(?:login|log-in|signin|sign-in|auth|sso)(?:\.|$)", re.I)
_PARKED = re.compile(
    r"(?:this domain (?:is |name is )?for sale|buy this domain|domain (?:is )?parked|"
    r"sedoparking\.com|parkingcrew\.net)",
    re.I,
)


class CheckBudgetExceeded(Exception):
    """The check could not start a request within its time budget."""


def public_dns(host: str, port: int) -> bool:
    """Reject private DNS answers too; never send a request to a known internal host."""
    try:
        answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        return bool(answers) and all(
            ip_address(answer[4][0]).is_global and not ip_address(answer[4][0]).is_multicast
            for answer in answers
        )
    except (OSError, ValueError):
        return False


def is_login(url: str, body: str = "") -> bool:
    parts = urlsplit(url)
    if _LOGIN.search(parts.path) or _LOGIN_HOST.search(parts.hostname or ""):
        return True
    # Login navigation or isolated sign-in wording is not an authentication wall.
    return any(
        re.search(r"<(?:input|button)\b", form, re.I)
        and re.search(r"\b(?:sign[- ]?in|log[- ]?in|login)\b", form, re.I)
        for form in re.findall(r"<form\b[^>]*>.*?</form\s*>", body, re.I | re.S)
    )


def observation_liveness(observation: dict) -> str:
    if observation["status"] == "gone":
        return "closed"
    if observation["status"] == "alive":
        return "alive"
    return "inconclusive"


def inspect_destination(
    url: str,
    client: httpx.Client,
    *,
    max_hops: int = MAX_REDIRECT_HOPS,
    resolve: Callable[[str, int], bool] = public_dns,
    request_url: str | None = None,
    request: Callable[[str], httpx.Response | None] | None = None,
    allowed_board: tuple[str, str] | None = None,
    expected_title: str | None = None,
    valid_response: Callable[[httpx.Response], bool] | None = None,
) -> dict:
    """Record terminal evidence; stop before fetching unsafe/unrelated redirects.

    Hop records contain hosts/domains/statuses only, never query tokens or addresses.
    An unrelated Location is recorded as the observed target, not a checked page.
    """
    if not 0 <= max_hops <= MAX_REDIRECT_HOPS:
        raise ValueError("max_hops must be between 0 and 5")
    result = {
        "url_key": url_key(url),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "status": "unknown",
        "http_status": None,
        "warnings": [],
        "hops": [],
        "terminal_host": None,
        "terminal_domain": None,
    }
    current = request_url or url
    visited: set[str] = set()
    started = monotonic()
    if not public_host(url):
        return {**result, "status": "invalid", "warnings": ["invalid_url"]}
    for hop in range(max_hops + 1):
        host = public_host(current)
        if not host:
            result["warnings"].append("invalid_redirect")
            return result
        result.update(terminal_host=host, terminal_domain=registrable_domain(host))
        if current in visited:
            result["warnings"].append("redirect_loop")
            return result
        visited.add(current)
        parts = urlsplit(current)
        if monotonic() - started >= MAX_CHECK_SECONDS:
            result["failure_reason"] = "lock_or_budget"
            result["warnings"].append("unreachable_or_private")
            return result
        if not resolve(
            parts.hostname or host, parts.port or (443 if parts.scheme == "https" else 80)
        ):
            result["warnings"].append("unreachable_or_private")
            return result
        try:
            if request is not None:
                response = request(current)
                if response is None:
                    return result
                body = response.text[:MAX_BODY_BYTES]
            else:
                # A streaming cap prevents giant/dripping parked pages occupying a worker.
                with client.stream("GET", current, follow_redirects=False) as response:
                    data = bytearray()
                    for chunk in response.iter_bytes(chunk_size=4096):
                        data.extend(chunk[: MAX_BODY_BYTES - len(data)])
                        if (
                            len(data) >= MAX_BODY_BYTES
                            or monotonic() - started >= MAX_CHECK_SECONDS
                        ):
                            break
                    body = data.decode("utf-8", errors="replace")
            code = response.status_code
            result["http_status"] = code
            result["hops"].append(
                {"host": host, "domain": registrable_domain(host), "status": code}
            )
            if code == 401:
                result.update(status="sign_in_required")
                return result
            if code in {403, 429}:
                # These responses often mean bot protection/rate limiting, not auth.
                # Some sites include an authentication Location even on a 403.
                location = response.headers.get("location")
                target = urljoin(current, location) if location else None
                target_host = public_host(target) if target else None
                if target_host and is_login(target):
                    result.update(
                        terminal_host=target_host, terminal_domain=registrable_domain(target_host)
                    )
                    result.update(status="sign_in_required")
                    result["warnings"].append("login_wall")
                elif is_login(current, body):
                    result.update(status="sign_in_required")
                    result["warnings"].append("login_wall")
                else:
                    result["warnings"].append(f"blocked_{code}")
                return result
            if code in {404, 410}:
                result.update(status="gone")
                return result
            if code >= 400:
                return result
            if code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location:
                    result["warnings"].append("redirect_without_location")
                    return result
                target = urljoin(current, location)
                target_host = public_host(target)
                result.update(
                    terminal_host=target_host, terminal_domain=registrable_domain(target_host)
                )
                if not target_host:
                    result["warnings"].append("invalid_redirect")
                    return result
                if is_login(target):
                    result.update(status="sign_in_required")
                    result["warnings"].append("login_wall")
                    return result
                # Compare board identities on shared ATS domains, not just their eTLD+1.
                board, target_board = ats_board(current), ats_board(target)
                same_board = bool(board and board == target_board)
                tied_board = bool(
                    allowed_board and board_matches_company(target_board, *allowed_board)
                )
                greenhouse_soft_404 = bool(
                    host
                    in {
                        "boards.greenhouse.io",
                        "job-boards.greenhouse.io",
                        "boards.eu.greenhouse.io",
                        "job-boards.eu.greenhouse.io",
                    }
                    and target_host
                    in {
                        "boards.greenhouse.io",
                        "job-boards.greenhouse.io",
                        "boards.eu.greenhouse.io",
                        "job-boards.eu.greenhouse.io",
                    }
                    and "true" in parse_qs(urlsplit(target).query).get("error", [])
                )
                same_site = (
                    registrable_domain(host) == registrable_domain(target_host)
                    and registrable_domain(host) is not None
                )
                shared_ats = any(
                    matches(host, domain) or matches(target_host, domain) for domain in ATS
                )
                if parts.scheme == "https" and urlsplit(target).scheme == "http":
                    result["warnings"].append("redirect_downgrade")
                    return result
                if not (same_board or tied_board or greenhouse_soft_404) and (
                    not same_site or (shared_ats and (not board or board != target_board))
                ):
                    result["warnings"].append("redirect_unrelated")
                    return result
                if hop == max_hops:
                    result["warnings"].append("redirect_limit")
                    return result
                current = target
                continue
            if is_login(current, body):
                result.update(status="sign_in_required")
                result["warnings"].append("login_wall")
            elif _PARKED.search(body):
                result["warnings"].append("parked")
            elif 200 <= code < 300:
                if host in {
                    "boards.greenhouse.io",
                    "job-boards.greenhouse.io",
                    "boards.eu.greenhouse.io",
                    "job-boards.eu.greenhouse.io",
                } and ("true" in parse_qs(parts.query).get("error", [])):
                    result.update(status="gone")
                else:
                    if valid_response is not None and not valid_response(response):
                        result["failure_reason"] = "parse_or_shape"
                        return result
                    result.update(status="alive")
                    if expected_title:
                        words = set(re.findall(r"[a-z0-9]+", expected_title.casefold())) - {
                            "a",
                            "an",
                            "and",
                            "at",
                            "for",
                            "in",
                            "of",
                            "the",
                            "to",
                            "with",
                        }
                        title_text = " ".join(re.findall(r"\w+", expected_title.casefold()))
                        body_text = " ".join(
                            re.findall(r"\w+", unescape(re.sub(r"<[^>]+>", " ", body)).casefold())
                        )
                        # Require the exact posting path and its title. A redirect
                        # to a careers index or recycled generic page is no rescue.
                        result["same_posting"] = bool(
                            len(words) >= 2
                            and f" {title_text} " in f" {body_text} "
                            and urlsplit(current).path.rstrip("/")
                            == urlsplit(request_url or url).path.rstrip("/")
                            and urlsplit(current).query == urlsplit(request_url or url).query
                        )
            return result
        except (httpx.InvalidURL, httpx.UnsupportedProtocol, httpx.RemoteProtocolError):
            result["warnings"].append("invalid_redirect")
            return result
        except httpx.TimeoutException:
            result["failure_reason"] = "timeout"
            return result
        except CheckBudgetExceeded:
            result["failure_reason"] = "lock_or_budget"
            return result
        except httpx.RequestError:
            return result
    return result
