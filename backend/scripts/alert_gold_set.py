"""Founder-run, read-only ALERT-01 sampling and offline precision scoring.

Run from backend: uv run python -m scripts.alert_gold_set sample --n 100 --out ../_local/gold.csv
Only sample needs DATABASE_URL. score never opens a database connection.
"""

import argparse
import csv
import json
import os
import sys
from pathlib import Path

from sqlalchemy import Integer, case, cast, create_engine, func, select, true
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from core import models

COLUMNS = (
    "notification_id",
    "opportunity_slug",
    "title",
    "company",
    "category",
    "stream",
    "interests",
    "graduation_year",
    "country",
    "reason_code",
    "reason_text",
    "matched_term",
    "rank",
    "eligibility_signal",
    "relevant",
    "eligible_claim_correct",
)


def sample_rows(session: Session, n: int) -> list[dict]:
    """One SELECT over sent email ledger snapshots; never loads users or PII."""
    evidence = models.Notification.meta["reasons"]
    # Older ledgers have no reasons. JSON null/scalars are not jsonb_each inputs.
    evidence = case((func.jsonb_typeof(evidence) == "object", evidence), else_=cast("{}", JSONB))
    reasons = func.jsonb_each(evidence).table_valued("key", "value", joins_implicitly=True)
    # Cast the table-valued JSON expression for SQLAlchemy's JSON operators.
    value = cast(reasons.c.value, JSONB)
    rows = session.execute(
        select(models.Notification.id, models.Notification.meta["reader_profile"], value)
        .join(reasons, true())
        .where(
            models.Notification.type == "digest",
            models.Notification.status == "sent",
            models.Notification.channel == "email",
        )
        .order_by(
            models.Notification.sent_at.desc(),
            models.Notification.id.desc(),
            cast(value["position"].astext, Integer).asc(),
            reasons.c.key.asc(),
        )
        .limit(n)
    ).all()
    result = []
    for notification_id, profile, reason in rows:
        profile = profile or {}
        opportunity = reason.get("opportunity") or {}
        result.append(
            {
                "notification_id": notification_id,
                "opportunity_slug": opportunity.get("slug", ""),
                "title": opportunity.get("title", ""),
                "company": opportunity.get("company", ""),
                "category": opportunity.get("category", ""),
                "stream": profile.get("stream", ""),
                "interests": ",".join(profile.get("interests") or []),
                "graduation_year": profile.get("graduation_year", ""),
                "country": profile.get("country", ""),
                "reason_code": reason.get("code", ""),
                "reason_text": reason.get("text", ""),
                "matched_term": reason.get("matched_term", ""),
                "rank": reason.get("rank", ""),
                "eligibility_signal": json.dumps(reason.get("eligibility", {}), ensure_ascii=False),
                "relevant": "",
                "eligible_claim_correct": "",
            }
        )
    return result


def write_sample(rows: list[dict], out: Path) -> None:
    def safe_cell(value):
        # A listing title must stay data when the founder opens the CSV in Excel.
        if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
            return "'" + value
        return value

    with out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows({key: safe_cell(row.get(key, "")) for key in COLUMNS} for row in rows)


def score(path: Path) -> int:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not {"relevant", "eligible_claim_correct"}.issubset(reader.fieldnames or []):
            raise ValueError("CSV must contain relevant and eligible_claim_correct columns")
        labelled = relevant = 0
        false_claims = []
        for number, row in enumerate(reader, start=2):
            labels = {
                key: (row.get(key) or "").strip().lower()
                for key in ("relevant", "eligible_claim_correct")
            }
            if any(label not in {"", "y", "n"} for label in labels.values()):
                raise ValueError(f"Row {number}: labels must be y, n or empty")
            if labels["relevant"]:
                labelled += 1
                relevant += labels["relevant"] == "y"
            if labels["eligible_claim_correct"] == "n":
                false_claims.append(
                    (number, row.get("notification_id", ""), row.get("opportunity_slug", ""))
                )
    if labelled:
        print(f"Precision: {relevant / labelled:.2%} ({relevant}/{labelled} labelled)")
    else:
        print("Precision: n/a (0 labelled)")
    print(f"False eligibility claims: {len(false_claims)}")
    for number, notification_id, slug in false_claims:
        print(f"Row {number}: notification {notification_id}, opportunity {slug}")
    return 1 if false_claims else (0 if labelled else 2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    sample = commands.add_parser("sample")
    sample.add_argument("--n", type=int, default=100)
    sample.add_argument("--out", type=Path, required=True)
    evaluate = commands.add_parser("score")
    evaluate.add_argument("csv", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "score":
            return score(args.csv)
        if args.n <= 0:
            parser.error("--n must be positive")
        url = os.environ.get("DATABASE_URL")
        if not url:
            parser.error("Set your own DATABASE_URL in this local shell")
        db_url = make_url(url)
        if db_url.drivername in {"postgres", "postgresql"}:
            db_url = db_url.set(drivername="postgresql+psycopg")
        engine = create_engine(db_url, connect_args={"connect_timeout": 10})
        try:
            with engine.connect().execution_options(postgresql_readonly=True) as connection:
                with connection.begin(), Session(bind=connection) as session:
                    rows = sample_rows(session, args.n)
            write_sample(rows, args.out)
        finally:
            engine.dispose()
        print(f"Sampled {len(rows)} picks")
        return 0
    except SQLAlchemyError:
        # SQLAlchemy connection errors can include credentials. Never echo them.
        print(
            "Database sample failed; check your connection and read permissions.", file=sys.stderr
        )
        return 2
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
