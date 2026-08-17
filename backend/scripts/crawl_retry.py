"""Redispatch crawl-tier1 only after a hung or truncated crawl."""

from __future__ import annotations

import argparse
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

MAX_ATTEMPTS = 3
RETRY_PREFIXES = ("HUNG:", "TRUNCATED:")


@dataclass(frozen=True)
class RetryDecision:
    should_dispatch: bool
    next_attempt: int | None
    reason: str


def parse_attempt(value: object) -> int:
    try:
        attempt = int(str(value).strip())
    except (TypeError, ValueError):
        return 1
    return max(attempt, 1)


def status_lines(log_paths: list[Path]) -> list[str]:
    matches: list[str] = []
    for path in log_paths:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            continue
        for line in text.splitlines():
            if line.startswith(RETRY_PREFIXES):
                matches.append(line)
    return matches


def retry_decision(
    *,
    attempt: int,
    retry_status_lines: list[str],
    max_attempts: int = MAX_ATTEMPTS,
) -> RetryDecision:
    if not retry_status_lines:
        return RetryDecision(
            should_dispatch=False,
            next_attempt=None,
            reason="No hung/truncated crawl marker found; not redispatching",
        )

    if attempt >= max_attempts:
        return RetryDecision(
            should_dispatch=False,
            next_attempt=None,
            reason=f"Retry suppressed: attempt {attempt} >= {max_attempts}",
        )

    next_attempt = attempt + 1
    return RetryDecision(
        should_dispatch=True,
        next_attempt=next_attempt,
        reason=f"Redispatching crawl-tier1 attempt {next_attempt}",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("logs", nargs="*", type=Path)
    parser.add_argument("--attempt", default=os.getenv("CRAWL_ATTEMPT", "1"))
    parser.add_argument("--workflow", default="crawl-tier1.yml")
    parser.add_argument("--ref", default=os.getenv("GITHUB_REF_NAME", "master"))
    args = parser.parse_args()

    attempt = parse_attempt(args.attempt)
    print(f"Crawl attempt {attempt}", flush=True)

    markers = status_lines(args.logs)
    for marker in markers:
        print(f"Retry trigger: {marker}", flush=True)

    decision = retry_decision(attempt=attempt, retry_status_lines=markers)
    print(decision.reason, flush=True)
    if not decision.should_dispatch:
        return

    subprocess.run(
        [
            "gh",
            "workflow",
            "run",
            args.workflow,
            "--ref",
            args.ref,
            "-f",
            f"attempt={decision.next_attempt}",
        ],
        check=True,
    )


if __name__ == "__main__":
    main()
