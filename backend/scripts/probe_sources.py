"""Read-only government source probe; no database imports or configuration.

Run: uv run python -m scripts.probe_sources --source meity_careers,nic_dii
"""

import argparse
import json

from crawlers.drdo import DrdoAdapter
from crawlers.isro import IsroAdapter
from crawlers.meity import MeityCareersAdapter
from crawlers.nec import NecInternshipsAdapter
from crawlers.nic_dii import NicDiiAdapter

ADAPTERS = {
    adapter.source_slug: adapter
    for adapter in (
        MeityCareersAdapter,
        NicDiiAdapter,
        DrdoAdapter,
        NecInternshipsAdapter,
        IsroAdapter,
    )
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="comma-separated government source slugs")
    args = parser.parse_args(argv)
    sources = list(dict.fromkeys(part.strip() for part in args.source.split(",") if part.strip()))
    unknown = set(sources) - ADAPTERS.keys()
    if unknown or not sources:
        parser.error(
            f"choose source slugs from {', '.join(ADAPTERS)}; unknown: {', '.join(sorted(unknown))}"
        )
    failed = False
    for slug in sources:
        adapter = ADAPTERS[slug]()
        try:
            raw = adapter.fetch()
            parsed = [adapter.parse(item) for item in raw]
            result = {
                "source": slug,
                "health": adapter.health(),
                "coverage": adapter.coverage(),
                "counts": adapter.filter_counts(),
                "fetched": len(raw),
                "parsed": len(parsed),
                "sample": [
                    {
                        "title": item.title,
                        "organiser": item.company_name,
                        "deadline": item.deadline.isoformat() if item.deadline else None,
                        "deadline_confidence": item.deadline_confidence,
                    }
                    for item in parsed[:5]
                ],
            }
            failed |= adapter.health() != "ok"
        except Exception as exc:
            failed = True
            result = {"source": slug, "health": "broken", "error": str(exc)}
        finally:
            adapter._client.close()
        print(json.dumps(result, ensure_ascii=True), flush=True)
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
