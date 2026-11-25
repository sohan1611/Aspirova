"""TRUST-01: read-only stratified sampling and offline, counts-only scoring.

Sample/labels stay under _local/eval/trust01; never commit them. No .env loading.
Labels JSONL: {"id": 123, "type": "aggregator", "domain": "jobicy.com",
               "status": "sign_in_required", "employer_verified": false, "valid": true}
Use "unchecked" when no HTTP observation exists. Human labels must be independent.
"""

import argparse
import json
from collections import defaultdict, deque
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from core import models
from core.destination_facts import (
    DESTINATION_TYPES,
    classify_destination_facts,
    public_host,
    registrable_domain,
)
from scripts.backfill_destination_facts import chosen_engine

LOCAL_DIR = Path(__file__).resolve().parents[2] / "_local" / "eval" / "trust01"


def private_path(path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(LOCAL_DIR.resolve()):
        raise ValueError("Evaluation files must stay under _local/eval/trust01")
    return resolved


def stratify(rows: list[dict], n: int) -> list[dict]:
    """Round-robin sources, then distinct registrable domains before repeats."""
    # Preserve rare boundary cases when already recorded; never fetch or invent them.
    preferred = {}
    for row in rows:
        observation = row.get("observation") or {}
        code = observation.get("http_status")
        case = f"http{code}" if code in {404, 410, 401, 403} else None
        if not case and observation.get("status") == "sign_in_required":
            case = "login_wall"
        if case and case not in preferred:
            preferred[case] = row
    result = list({row["id"]: row for row in preferred.values()}.values())[:n]
    chosen = {row["id"] for row in result}
    groups = defaultdict(lambda: defaultdict(deque))
    for row in rows:
        if row["id"] in chosen:
            continue
        domain = registrable_domain(public_host(row["url"])) or "unknown"
        groups[row.get("source") or "unknown"][domain].append(row)
    sources = deque(
        deque(domains[key] for key in sorted(domains)) for _, domains in sorted(groups.items())
    )
    while sources and len(result) < n:
        domains = sources.popleft()
        listings = domains.popleft()
        result.append(listings.popleft())
        if listings:
            domains.append(listings)
        if domains:
            sources.append(domains)
    return result


def sample_rows(session: Session, n: int) -> list[dict]:
    o, c = models.Opportunity, models.Company
    rows = session.execute(
        select(
            o.id,
            o.apply_url,
            o.primary_source,
            c.domain,
            c.ats_type,
            c.ats_board_id,
            o.destination_facts["observation"],
        )
        .outerjoin(c, c.id == o.company_id)
        .where(o.status == "active")
        .order_by(o.id)
    ).all()
    return stratify(
        [
            {
                "id": row[0],
                "url": row[1],
                "source": row[2],
                "company_domain": row[3],
                "ats_type": row[4],
                "ats_board_id": row[5],
                "observation": row[6],
            }
            for row in rows
        ],
        n,
    )


def predictions(row: dict) -> dict:
    return classify_destination_facts(
        row["url"],
        row.get("company_domain"),
        source=row.get("source"),
        ats_type=row.get("ats_type"),
        ats_board_id=row.get("ats_board_id"),
        observation=row.get("observation"),
    )


def score(rows: list[dict], labels: list[dict]) -> tuple[dict, bool]:
    by_id = {row["id"]: row for row in rows}
    if len(by_id) != len(rows) or len({row["id"] for row in labels}) != len(labels):
        raise ValueError("Duplicate sample or label IDs")
    stats = {kind: {"tp": 0, "fp": 0, "fn": 0} for kind in DESTINATION_TYPES}
    totals = {
        "labelled": 0,
        "domain_exact": 0,
        "valid_correct": 0,
        "employer_correct": 0,
        "status_correct": 0,
        "gone_total": 0,
        "gone_correct": 0,
        "auth_total": 0,
        "auth_correct": 0,
    }
    for code in (404, 410, 401, 403):
        totals[f"http{code}_total"] = totals[f"http{code}_correct"] = 0
    for label in labels:
        if (
            label.get("type") not in DESTINATION_TYPES
            or label.get("id") not in by_id
            or not {"domain", "status", "valid", "employer_verified"}.issubset(label)
            or type(label["valid"]) is not bool
            or type(label["employer_verified"]) is not bool
            or label["status"]
            not in {"unchecked", "alive", "gone", "sign_in_required", "unknown", "invalid"}
        ):
            raise ValueError("Incomplete or invalid labels")
        predicted = predictions(by_id[label["id"]])
        code = (by_id[label["id"]].get("observation") or {}).get("http_status")
        if code in {404, 410, 401, 403}:
            status = "gone" if code in {404, 410} else "sign_in_required"
            totals[f"http{code}_total"] += 1
            totals[f"http{code}_correct"] += predicted["status"] == label["status"] == status
        expected, actual = label["type"], predicted["type"]
        totals["labelled"] += 1
        if actual == expected:
            stats[actual]["tp"] += 1
        else:
            stats[actual]["fp"] += 1
            stats[expected]["fn"] += 1
        for field, key in (
            ("domain", "domain_exact"),
            ("valid", "valid_correct"),
            ("employer_verified", "employer_correct"),
            ("status", "status_correct"),
        ):
            totals[key] += predicted[field] == label[field]
        for status, prefix in (("gone", "gone"), ("sign_in_required", "auth")):
            if label["status"] == status:
                totals[prefix + "_total"] += 1
                totals[prefix + "_correct"] += predicted["status"] == status
    # Precision = tp/(tp+fp), recall = tp/(tp+fn). Print only counts, no row IDs/URLs.
    for kind, counts in stats.items():
        print(
            f"{kind} precision={counts['tp']}/{counts['tp'] + counts['fp']} "
            f"recall={counts['tp']}/{counts['tp'] + counts['fn']}"
        )
    print(" ".join(f"{key}={value}" for key, value in totals.items()))
    print(f"domain_exact_match={totals['domain_exact']}/{totals['labelled']}")
    complete = (
        len(labels) == len(rows) >= 100 and totals["http404_total"] > 0 and totals["auth_total"] > 0
    )
    correct = all(counts["fp"] == counts["fn"] == 0 for counts in stats.values()) and all(
        totals[key] == len(labels)
        for key in ("domain_exact", "valid_correct", "employer_correct", "status_correct")
    )
    return {"types": stats, **totals}, complete and correct


def read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in private_path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    sample = commands.add_parser("sample")
    sample.add_argument("--n", type=int, default=100)
    sample.add_argument("--out", type=Path, default=LOCAL_DIR / "sample.jsonl")
    evaluate = commands.add_parser("score")
    evaluate.add_argument("--sample", type=Path, default=LOCAL_DIR / "sample.jsonl")
    evaluate.add_argument("--labels", type=Path, default=LOCAL_DIR / "labels.jsonl")
    args = parser.parse_args()
    try:
        if args.command == "score":
            _, passed = score(read_jsonl(args.sample), read_jsonl(args.labels))
            return 0 if passed else 1
        if args.n < 100:
            raise ValueError("Sample size must be at least 100")
        out = private_path(args.out)
        engine = chosen_engine()
        try:
            with engine.connect().execution_options(postgresql_readonly=True) as connection:
                with connection.begin(), Session(bind=connection) as session:
                    connection.exec_driver_sql("SET LOCAL statement_timeout = '30s'")
                    rows = sample_rows(session, args.n)
        finally:
            engine.dispose()
        if len(rows) < 100:
            raise ValueError("Fewer than 100 rows available")
        out.parent.mkdir(parents=True, exist_ok=True)
        # Never overwrite a previously labelled sample accidentally.
        with out.open("x", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(
            f"sampled={len(rows)} sources={len({row['source'] for row in rows})} "
            f"domains={len({registrable_domain(public_host(row['url'])) for row in rows})}"
        )
        return 0
    except (SQLAlchemyError, ValueError, OSError, KeyError, TypeError):
        # Malformed input/connection errors may contain URLs, tokens or personal data.
        parser.exit(2, "Evaluation failed; check private inputs, arguments and connection.\n")


if __name__ == "__main__":
    raise SystemExit(main())
