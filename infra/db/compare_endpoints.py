"""Compare every public API endpoint between two deployments of the same code.

Used as the cutover gate (RUNBOOK step 3d): the candidate is a local API
pointed at the new server, the baseline is production still on Supabase.
Run from backend/ so httpx comes from the project environment:

    uv run python ../infra/db/compare_endpoints.py --exact

Paginated endpoints are compared on `total`, fetched with limit=1 and a
random page. The response cache keys only on declared parameters, and the
site never requests limit=1, so both sides miss the cache and count live
rows. With writes frozen, those totals must match exactly; --exact fails the
run on any difference. Unpaginated endpoints may be served from a cache up to
six hours old, so they are compared on status and response shape only.
"""

import argparse
import random
import sys

import httpx

PROD = "https://aspirova-api.onrender.com"

COUNTED = [
    "/feed",
    "/feed?category=job",
    "/feed?category=internship",
    "/feed?kind=competitions&sort=deadline",
    "/feed?remote=true",
    "/feed?scope=domestic&country=IN",
    "/search?q=engineer",
    "/search?q=data&category=internship",
    "/search?q=hackathon&kind=competitions&sort=deadline",
    "/company/databricks",
    "/programmes",
]

SHAPED = [
    "/health",
    "/search?q=devlopr",  # misspelt on purpose: the pg_trgm fallback path
    "/facets",
    "/facets?category=internship",
    "/facets?kind=competitions",
    "/trending?limit=10",
    "/companies",
    "/companies/top",
    "/plans",
    "/stats",
    "/sitemap-companies",
    "/sitemap-opportunities",
]


def get(client: httpx.Client, base: str, path: str):
    try:
        response = client.get(base + path)
    except httpx.HTTPError as exc:
        return None, type(exc).__name__, None
    try:
        body = response.json()
    except ValueError:
        body = None
    return response.status_code, body, response.headers.get("x-db-time-ms")


def shape(body) -> str:
    if isinstance(body, dict):
        return "dict:" + ",".join(sorted(body))
    if isinstance(body, list):
        first = body[0] if body else None
        return "list:" + (",".join(sorted(first)) if isinstance(first, dict) else type(first).__name__)
    return type(body).__name__


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", default="http://127.0.0.1:8100")
    parser.add_argument("--baseline", default=PROD)
    parser.add_argument("--exact", action="store_true", help="fail on any total difference")
    args = parser.parse_args()

    failures = 0
    with httpx.Client(timeout=60) as client:
        page = random.randint(2, 60)
        for path in COUNTED:
            probe = f"{path}{'&' if '?' in path else '?'}page={page}&limit=1"
            c_status, c_body, c_ms = get(client, args.candidate, probe)
            b_status, b_body, b_ms = get(client, args.baseline, probe)
            c_total = (c_body or {}).get("total") if isinstance(c_body, dict) else None
            b_total = (b_body or {}).get("total") if isinstance(b_body, dict) else None
            ok = c_status == b_status == 200 and c_total is not None
            if ok and c_total != b_total:
                ok = not args.exact and abs(c_total - b_total) <= 0.02 * max(b_total, 1)
            failures += not ok
            status = "" if ok else f"   HTTP {c_status} vs {b_status}"
            print(
                f"{'OK  ' if ok else 'FAIL'} {path:<52} total {c_total} vs {b_total}"
                f"   db {c_ms or '-'} vs {b_ms or '-'} ms{status}"
            )

        slug = None
        _, feed, _ = get(client, args.candidate, "/feed?page=1&limit=1")
        if isinstance(feed, dict) and feed.get("items"):
            slug = feed["items"][0]["slug"]
        _, progs, _ = get(client, args.candidate, "/programmes?page=1&limit=1")
        prog = progs["items"][0]["slug"] if isinstance(progs, dict) and progs.get("items") else None
        extra = [f"/opportunity/{slug}", f"/opportunity/{slug}/similar?limit=6"] if slug else []
        extra += [f"/programme/{prog}"] if prog else []

        for path in SHAPED + extra:
            c_status, c_body, _ = get(client, args.candidate, path)
            b_status, b_body, _ = get(client, args.baseline, path)
            ok = c_status == b_status == 200 and shape(c_body) == shape(b_body)
            failures += not ok
            print(f"{'OK  ' if ok else 'FAIL'} {path:<52} {c_status} vs {b_status}  {shape(c_body)[:60]}")

    print(f"\n{len(COUNTED) + len(SHAPED) + len(extra)} endpoints, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
