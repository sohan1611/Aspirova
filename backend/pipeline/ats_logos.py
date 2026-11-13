"""Identify employer ATS boards and their explicitly uploaded logo URLs."""

import json
import re
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup

from core.domains import http_url
from pipeline.company_logos import Fetcher, robots_allowed

ATS_HOSTS = frozenset(
    {
        "greenhouse.io",
        "lever.co",
        "ashbyhq.com",
        "myworkdayjobs.com",
        "workday.com",
        "smartrecruiters.com",
        "workable.com",
        "recruitee.com",
        "keka.com",
        "keka.co",
        "icims.com",
        "bamboohr.com",
        "breezy.hr",
        "jobvite.com",
        "teamtailor.com",
        "personio.de",
        "personio.com",
        "zohorecruit.com",
        "zohorecruit.in",
        "zoho.com",
        "freshteam.com",
        "darwinbox.in",
        "darwinbox.com",
        "successfactors.com",
        "successfactors.eu",
        "taleo.net",
        "oraclecloud.com",
        "ultipro.com",
        "paylocity.com",
        "adp.com",
        "jazzhr.com",
        "applytojob.com",
        "pinpointhq.com",
        "rippling.com",
        "dover.com",
        "gem.com",
        "homerun.co",
        "join.com",
        "hirehive.com",
        "trakstar.com",
    }
)
_TOKEN = re.compile(r"[a-zA-Z0-9_-]+")


def ats_hosted(url: str | None) -> bool:
    host = urlsplit(http_url(url) or "").hostname or ""
    return any(host == root or host.endswith("." + root) for root in ATS_HOSTS)


def board_from_url(url: str | None) -> str | None:
    """Canonicalize supported public/API job URLs, including Workday locales."""
    parts = urlsplit(http_url(url) or "")
    host = parts.hostname or ""
    path = parts.path.strip("/").split("/")
    roots = {
        "boards.greenhouse.io": "https://job-boards.greenhouse.io/",
        "job-boards.greenhouse.io": "https://job-boards.greenhouse.io/",
        "jobs.lever.co": "https://jobs.lever.co/",
        "jobs.eu.lever.co": "https://jobs.eu.lever.co/",
        "jobs.ashbyhq.com": "https://jobs.ashbyhq.com/",
    }
    if host in roots and _TOKEN.fullmatch(path[0]):
        return roots[host] + path[0].lower()
    if host == "boards-api.greenhouse.io" and path[:2] == ["v1", "boards"]:
        return board_from_token("greenhouse", path[2] if len(path) > 2 else "")
    if host == "api.lever.co" and path[:2] == ["v0", "postings"]:
        return board_from_token("lever", path[2] if len(path) > 2 else "")
    if host == "api.ashbyhq.com" and path[:2] == ["posting-api", "job-board"]:
        return board_from_token("ashby", path[2] if len(path) > 2 else "")
    tenant = re.fullmatch(r"([a-z0-9-]+)\.wd\d+\.myworkdayjobs\.com", host)
    if tenant:
        if re.fullmatch(r"[a-zA-Z]{2}[-_][a-zA-Z]{2}", path[0]):
            path = path[1:]
        if path[:2] == ["wday", "cxs"]:
            path = path[3:] if len(path) > 3 and path[2] == tenant[1] else []
        if path and _TOKEN.fullmatch(path[0]):
            return f"https://{host}/{path[0]}"
    return None


def board_from_token(ats_type: str | None, token: str | None) -> str | None:
    if not token:
        return None
    roots = {
        "greenhouse": "https://job-boards.greenhouse.io/",
        "lever": "https://jobs.lever.co/",
        "ashby": "https://jobs.ashbyhq.com/",
    }
    if ats_type in roots and _TOKEN.fullmatch(token):
        return roots[ats_type] + token.lower()
    if ats_type == "workday":
        parts = token.split("|")
        if (
            len(parts) == 3
            and re.fullmatch(r"[a-zA-Z0-9-]+", parts[0])
            and re.fullmatch(r"wd\d+", parts[1], re.IGNORECASE)
            and _TOKEN.fullmatch(parts[2])
        ):
            return f"https://{parts[0].lower()}.{parts[1].lower()}.myworkdayjobs.com/{parts[2]}"
    return None


def _ashby_logo(soup: BeautifulSoup) -> str | None:
    for script in soup.find_all("script"):
        match = re.search(r"window\.__appData\s*=\s*", script.get_text())
        if not match:
            continue
        try:
            data, _ = json.JSONDecoder().raw_decode(script.get_text()[match.end() :])
        except ValueError:
            continue
        objects = [data]
        wordmark = None
        while objects:
            item = objects.pop()
            if isinstance(item, dict):
                if square := http_url(item.get("logoSquareImageUrl")):
                    return square
                wordmark = wordmark or http_url(item.get("logoWordmarkImageUrl"))
                objects.extend(item.values())
            elif isinstance(item, list):
                objects.extend(item)
        if wordmark:
            return wordmark
    return None


def extract_board_logo(board: str, content: bytes) -> str | None:
    host = urlsplit(board).hostname or ""
    if host.endswith(".myworkdayjobs.com"):
        return board.rstrip("/") + "/assets/logo"
    soup = BeautifulSoup(content, "html.parser")
    if host == "jobs.ashbyhq.com":
        return _ashby_logo(soup)
    for image in soup.find_all("img"):
        source = image.get("src")
        url = http_url(urljoin(board, source)) if isinstance(source, str) else None
        if not url:
            continue
        parts = urlsplit(url)
        if host == "job-boards.greenhouse.io" and (
            re.fullmatch(r"s[\w-]*-recruiting\.cdn\.greenhouse\.io", parts.hostname or "")
            and parts.path.startswith("/external_greenhouse_job_boards/logos/")
        ):
            return url
        if host in {"jobs.lever.co", "jobs.eu.lever.co"} and (
            re.fullmatch(r"lever-client-logos\.s3[.-][a-z0-9.-]+", parts.hostname or "")
            and str(image.get("alt", "")).strip().lower().endswith(" logo")
            and str(image.get("alt", "")).strip().lower() != "lever logo"
            and "footer-logo" not in image.get("class", [])
        ):
            return url
    return None


def board_logo_url(fetcher: Fetcher, board: str, robots: dict[str, RobotFileParser]) -> str | None:
    if not robots_allowed(fetcher, board, robots):
        return None
    if (urlsplit(board).hostname or "").endswith(".myworkdayjobs.com"):
        url = extract_board_logo(board, b"")
        return url if url and robots_allowed(fetcher, url, robots) else None
    page = fetcher.get(board)
    if page is None or page.status != 200 or board_from_url(page.url) != board:
        return None
    return extract_board_logo(board, page.content)
