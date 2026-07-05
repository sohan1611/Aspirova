"""Sample production p95 for total request time and the isolated DB hop
(Doc handoffs/PHASE-2-HANDOFF.md sec 2/4/6 - the Lever-2 input).
Methodology matches the Phase-1 measurement (Doc handoffs/PHASE-1-REPORT.md
sec 6): a persistent httpx.Client, not a fresh process per request (which
pays its own TLS handshake and was discarded there as a methodology
artifact), n=30 samples per endpoint.

Reports three numbers per endpoint, not one, because a single p95 conflates
three genuinely different things this decision needs to tell apart:
  - client wall-clock: what a real caller experiences, network transit
    both ways included
  - X-Total-Time-Ms (server header): time the Render process spent end to
    end, network transit excluded - isolates "network, or server?"
  - X-DB-Time-Ms (server header): time spent waiting on Postgres,
    specifically - isolates "is it the DB hop?" (the actual Lever-2
    question - Doc handoffs/PHASE-2-HANDOFF.md sec 4)
"""

import argparse
import statistics
import time

import httpx

DEFAULT_BASE_URL = "https://aspirova-api.onrender.com"
SAMPLE_COUNT = 30
ENDPOINTS = {
    "feed": "/feed?limit=20",
    "search": "/search?q=software+engineer&limit=20",
}


def percentile(values: list[float], pct: int) -> float:
    return statistics.quantiles(values, n=100, method="inclusive")[pct - 1]


def sample_endpoint(client: httpx.Client, path: str, n: int) -> dict[str, list[float]]:
    wall_ms: list[float] = []
    total_ms: list[float] = []
    db_ms: list[float] = []
    for _ in range(n):
        start = time.perf_counter()
        response = client.get(path)
        wall_ms.append((time.perf_counter() - start) * 1000)
        response.raise_for_status()
        total_ms.append(float(response.headers["X-Total-Time-Ms"]))
        db_ms.append(float(response.headers["X-DB-Time-Ms"]))
    return {"wall_ms": wall_ms, "total_ms": total_ms, "db_ms": db_ms}


def summarize(label: str, values: list[float]) -> str:
    return (
        f"{label:>22}: p50={statistics.median(values):7.1f}ms  "
        f"p95={percentile(values, 95):7.1f}ms  max={max(values):7.1f}ms"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--n", type=int, default=SAMPLE_COUNT)
    args = parser.parse_args()

    with httpx.Client(base_url=args.base_url, timeout=15.0) as client:
        # Resolve one real slug for the opportunity endpoint via the same
        # client (no extra TLS handshake) - not counted as a sample.
        feed = client.get("/feed?limit=1")
        feed.raise_for_status()
        slug = feed.json()["items"][0]["slug"]
        endpoints = {**ENDPOINTS, "opportunity": f"/opportunity/{slug}"}

        for name, path in endpoints.items():
            samples = sample_endpoint(client, path, args.n)
            print(f"\n=== {name} ({path}) - n={args.n} ===")
            print(summarize("client wall-clock", samples["wall_ms"]))
            print(summarize("X-Total-Time-Ms", samples["total_ms"]))
            print(summarize("X-DB-Time-Ms", samples["db_ms"]))


if __name__ == "__main__":
    main()
