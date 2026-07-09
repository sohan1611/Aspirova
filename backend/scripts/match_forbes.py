"""Match local companies to bundled Forbes Global 2000 ranks."""

import argparse
import json
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session, load_only

from core import models
from core.db import make_engine
from pipeline.normalize import normalize_company_name

BATCH_SIZE = 500
EXAMPLE_LIMIT = 10
FORBES_PATH = Path(__file__).resolve().parents[1] / "data" / "forbes_global2000.json"


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _best_rank(existing: int | None, candidate: int) -> int:
    if existing is None:
        return candidate
    return min(existing, candidate)


def _load_forbes_rows(path: Path = FORBES_PATH) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as file:
        rows = json.load(file)
    if not isinstance(rows, list):
        raise ValueError("Forbes data must be a JSON array")
    return [row for row in rows if isinstance(row, dict)]


def build_lookup_maps(rows: Iterable[dict[str, Any]]) -> tuple[dict[str, int], dict[str, int]]:
    domain_map: dict[str, int] = {}
    name_map: dict[str, int] = {}

    for row in rows:
        rank = row.get("rank")
        if not isinstance(rank, int):
            continue

        domain = row.get("domain")
        if isinstance(domain, str):
            domain_key = domain.strip().lower()
            if domain_key:
                domain_map[domain_key] = _best_rank(domain_map.get(domain_key), rank)

        name = row.get("name")
        if isinstance(name, str):
            name_key = normalize_company_name(name)
            if name_key:
                name_map[name_key] = _best_rank(name_map.get(name_key), rank)

    return domain_map, name_map


def _batches(
    session: Session,
    *,
    batch_size: int = BATCH_SIZE,
) -> Iterator[list[models.Company]]:
    last_id = 0
    while True:
        rows = list(
            session.scalars(
                select(models.Company)
                .options(
                    load_only(
                        models.Company.id,
                        models.Company.name,
                        models.Company.domain,
                        models.Company.global_rank,
                    )
                )
                .where(models.Company.id > last_id)
                .order_by(models.Company.id)
                .limit(batch_size)
            ).all()
        )
        if not rows:
            return
        last_id = rows[-1].id
        yield rows


def _rank_for_company(
    company: models.Company,
    *,
    domain_map: dict[str, int],
    name_map: dict[str, int],
) -> int | None:
    if company.domain:
        domain_rank = domain_map.get(company.domain.strip().lower())
        if domain_rank is not None:
            return domain_rank

    name_key = normalize_company_name(company.name)
    return name_map.get(name_key)


def match_forbes(
    session: Session,
    *,
    forbes_path: Path = FORBES_PATH,
    dry_run: bool = False,
    reset: bool = False,
    batch_size: int = BATCH_SIZE,
) -> dict[str, Any]:
    rows = _load_forbes_rows(forbes_path)
    domain_map, name_map = build_lookup_maps(rows)

    if reset and not dry_run:
        session.execute(update(models.Company).values(global_rank=None))
        session.commit()

    scanned = 0
    ranked = 0
    examples: list[str] = []

    for companies in _batches(session, batch_size=batch_size):
        for company in companies:
            scanned += 1
            rank = _rank_for_company(company, domain_map=domain_map, name_map=name_map)
            if rank is None:
                continue

            ranked += 1
            if len(examples) < EXAMPLE_LIMIT:
                examples.append(f"{company.name} -> Forbes rank {rank}")
            if not dry_run:
                company.global_rank = rank

        if not dry_run:
            session.commit()

    if dry_run:
        session.rollback()

    return {
        "scanned": scanned,
        "ranked": ranked,
        "unranked": scanned - ranked,
        "examples": examples,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Report matches without writing")
    parser.add_argument("--reset", action="store_true", help="Clear existing ranks before matching")
    parser.add_argument(
        "--batch-size",
        type=_positive_int,
        default=BATCH_SIZE,
        help="Companies to scan between commits",
    )
    args = parser.parse_args()

    engine = make_engine()
    with Session(engine) as session:
        result = match_forbes(
            session,
            dry_run=args.dry_run,
            reset=args.reset,
            batch_size=args.batch_size,
        )

    action = "would rank" if args.dry_run else "ranked"
    print(
        "forbes match: "
        f"scanned {result['scanned']}, {action} {result['ranked']}, "
        f"unranked {result['unranked']}",
        flush=True,
    )
    if args.dry_run and result["examples"]:
        print("example matches:", flush=True)
        for example in result["examples"]:
            print(f"  {example}", flush=True)


if __name__ == "__main__":
    main()
