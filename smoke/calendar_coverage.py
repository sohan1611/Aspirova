"""Pure, database-free comparison used by the deploy smoke canary."""

import json
import time
from collections.abc import Callable
from hashlib import sha256

COUNT_BUCKETS = (
    "published_dated",
    "published_rolling",
    "outside_window",
    "closed",
    "retired",
)
ROW_BUCKETS = ("skipped", "pending_import", "unexplained")


def source_digest(source: dict, metadata: dict) -> str:
    """Match the backend's canonical JSON digest without importing backend code."""

    def canonical(value: dict) -> bytes:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")

    return sha256(canonical(source) + b"\n" + canonical(metadata)).hexdigest()[:16]


def wait_for_deployed_coverage(
    fetch: Callable[[], tuple[int, dict | None]],
    expected_digest: str,
    *,
    timeout_s: float = 360,
    interval_s: float = 20,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict:
    """Wait out independent Vercel/Render deploys using anonymous coverage reads."""
    if timeout_s < 0 or interval_s <= 0:
        raise ValueError("timeout_s must be nonnegative and interval_s positive")
    started = clock()
    deadline = started + timeout_s
    last_status, last_digest = None, None
    polls = 0
    while True:
        polls += 1
        try:
            last_status, body = fetch()
            last_digest = body.get("source_digest") if isinstance(body, dict) else None
            if last_status == 200 and last_digest == expected_digest:
                if polls > 1:
                    print(
                        f"Calendar API served deployed data after "
                        f"{clock() - started:.1f}s ({polls} polls)"
                    )
                return body
        except Exception:
            # A timeout or failed connection is a failed poll, not a failed canary.
            pass
        remaining = deadline - clock()
        if remaining <= 0:
            raise AssertionError(
                "API never served the deployed calendar data "
                "(check the Render deploy): "
                f"expected digest {expected_digest}, last status {last_status}, "
                f"last digest {last_digest}"
            )
        sleep(min(interval_s, remaining))


def assert_calendar_coverage(coverage: dict, source_rows: int) -> None:
    # Pending import is context, not a failure: the daily refresh owns that gate.
    context = f"Calendar coverage (pending_import allowed): {coverage!r}"
    for field in (*COUNT_BUCKETS, "source_rows", "published_total"):
        value = coverage.get(field)
        assert type(value) is int and value >= 0, f"Invalid {field}; {context}"
    for field in ROW_BUCKETS:
        assert isinstance(coverage.get(field), list), f"Invalid {field}; {context}"
    assert (
        coverage["source_rows"] == source_rows
    ), f"Deployed JSON has {source_rows} rows; {context}"
    assert coverage["unexplained"] == [], context
    assert coverage.get("rows_without_metadata") == 0, context
    assert coverage.get("metadata_without_row") == 0, context
    partition = sum(coverage[field] for field in COUNT_BUCKETS) + sum(
        len(coverage[field]) for field in ROW_BUCKETS
    )
    assert partition == source_rows, f"Bucket sum {partition}; {context}"
    assert coverage["published_total"] == (
        coverage["published_dated"] + coverage["published_rolling"]
    ), context
    assert coverage["published_total"] > 0, context
