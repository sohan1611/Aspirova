"""Reproduce landing EXPLAINs on synthetic data; refuses every non-local URL.

From the repository root, using the backend virtualenv:
    python backend/scripts/landing_perf.py --seed
    python backend/scripts/landing_perf.py --output _local/landing-perf.json
No dotenv files are read. The database must already have alembic upgrade head.
"""

import argparse
import inspect
import json
import os
import sys
from pathlib import Path
from time import perf_counter

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import Settings  # noqa: E402

Settings.model_config["env_file"] = None

from tests.landing_reference import legacy_landing_feed_rows  # noqa: E402

URL = "postgresql+psycopg://postgres:test@localhost:56432/aspirova_perf"


def seed(connection):
    if connection.scalar(text("select count(*) from opportunities")):
        raise RuntimeError("Seed requires an empty disposable database")
    connection.execute(text("""
        INSERT INTO companies (id, slug, name, logo_url, prestige_rank)
        SELECT i, 'perf-company-' || i, 'Perf Company ' || i,
            CASE WHEN i % 5 < 3 THEN 'https://example.org/logo/' || i END,
            CASE WHEN i % 13 = 0 THEN i END
        FROM generate_series(1, 5600) i
    """))
    connection.execute(text("""
        INSERT INTO opportunities
            (id, slug, company_id, title, category, primary_source, country,
             is_remote, apply_url, status, first_seen_at, last_seen_at, posted_at,
             deadline, closed_at, meta, eligibility_facts, description_raw, summary)
        SELECT i, 'perf-opp-' || i,
            CASE WHEN i % 101 = 0 THEN NULL
                 WHEN i % 9 = 0 THEN 13 ELSE 1 + (i * 47 % 5600) END,
            (ARRAY['Software Intern', 'Senior Engineer', 'Graduate Analyst',
                   'Staff Accountant', 'Product Designer', 'Engineering Apprentice'])[1 + i % 6],
            CASE WHEN i % 6 = 0 THEN 'internship' ELSE 'job' END,
            CASE WHEN i % 5 < 2 THEN 'greenhouse'
                 ELSE 'source-' || (i % 16) END,
            (ARRAY['IN','US','GB',NULL])[1 + i % 4], i % 3 = 0,
            'https://example.org/apply/' || i,
            CASE WHEN i % 20 < 11 THEN 'active' ELSE 'closed' END,
            now() - (i % 400) * interval '1 day',
            now() - (i % 90) * interval '1 hour',
            CASE WHEN i % 7 = 0 THEN NULL ELSE now() - (i % 320) * interval '1 day' END,
            CASE WHEN i % 11 = 0 THEN now() - interval '2 days'
                 WHEN i % 5 = 0 THEN now() + interval '30 days' END,
            CASE WHEN i % 29 = 0 THEN now() - interval '3 days' END,
            jsonb_build_object(
                'eligible_experienced_only', i % 23 = 0,
                'eligibility', CASE WHEN i % 31 = 0 THEN '["School Students"]'::jsonb
                    WHEN i % 3 = 0 THEN '["Undergraduate","Graduate"]'::jsonb
                    ELSE '[]'::jsonb END,
                'summary_source', 'extracted',
                'source_detail', repeat(md5(i::text), 32)),
            CASE WHEN i % 3 = 0 THEN NULL ELSE jsonb_build_object(
                'grad_years', jsonb_build_object('value', jsonb_build_array(2026 + i % 3)),
                'stages', jsonb_build_object('value', jsonb_build_array('undergraduate')),
                'remote_regions', jsonb_build_object('value',
                    CASE WHEN i % 2 = 0 THEN '["IN","APAC"]'::jsonb ELSE '["US"]'::jsonb END),
                'visa_sponsorship', jsonb_build_object('value', i % 2 = 0)) END,
            repeat('Build and test software systems. ' || md5(i::text), 80),
            'Build and test software systems with the engineering team.'
        FROM generate_series(1, 62000) i
    """))
    # Simulate pre-migration rows that have not received the founder backfill.
    connection.execute(text("UPDATE opportunities SET role_rank = NULL WHERE id % 3 = 0"))
    connection.exec_driver_sql("SELECT setval(pg_get_serial_sequence('companies','id'), 5600)")
    connection.exec_driver_sql("SELECT setval(pg_get_serial_sequence('opportunities','id'), 62000)")
    connection.exec_driver_sql("ANALYZE companies")
    connection.exec_driver_sql("ANALYZE opportunities")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=URL)
    parser.add_argument("--seed", action="store_true")
    parser.add_argument(
        "--current-only", action="store_true", help="Measure the current query only"
    )
    parser.add_argument("--role-ranks", choices=("stored", "null", "mixed"))
    parser.add_argument("--limit", type=int, default=24, choices=range(1, 101))
    parser.add_argument("--output", default="_local/landing-perf.json")
    args = parser.parse_args()
    url = make_url(args.url)
    if (
        url.host not in {"localhost", "127.0.0.1"}
        or url.port != 56432
        or not (
            url.database == "aspirova_perf" or (url.database or "").startswith("aspirova_perf_")
        )
        or url.query
    ):
        parser.error(
            "Only localhost:56432/aspirova_perf[_suffix] without URL query options is permitted"
        )
    os.environ["DATABASE_URL"] = args.url
    from api import feed

    engine = create_engine(url, connect_args={"connect_timeout": 3})
    if args.seed:
        with engine.begin() as connection:
            seed(connection)
    with engine.begin() as connection:
        if args.role_ranks:
            rank = {
                "stored": "opportunity_role_rank(title, category, meta)",
                "null": "NULL",
                "mixed": "CASE WHEN id % 3 = 0 THEN NULL "
                "ELSE opportunity_role_rank(title, category, meta) END",
            }[args.role_ranks]
            connection.execute(text("UPDATE opportunities SET role_rank = " + rank))
            connection.exec_driver_sql("ANALYZE opportunities")
        null_ranks = connection.scalar(
            text("SELECT count(*) FROM opportunities WHERE role_rank IS NULL")
        )
    plans = []

    @event.listens_for(engine, "before_cursor_execute")
    def explain(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().startswith(("SELECT", "WITH")):
            cursor.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + statement, parameters)
            plans.append(cursor.fetchone()[0][0])

    results = []
    current = feed.landing_feed_rows
    implementations = [("after", current)]
    if not args.current_only:
        implementations.insert(0, ("before", legacy_landing_feed_rows))
    defaults = {
        key: param.default.default
        for key, param in inspect.signature(feed.get_feed).parameters.items()
        if key != "db"
    }
    try:
        for prefer_country in (None, "IN"):
            for name, implementation in implementations:
                feed.landing_feed_rows = implementation
                plans.clear()
                with Session(engine) as session:
                    # Same app statement timeout; do not mask a slow plan.
                    session.connection().exec_driver_sql("SET LOCAL statement_timeout = '20s'")
                    started = perf_counter()
                    response = feed.get_feed(
                        **{
                            **defaults,
                            "prefer_logos": True,
                            "prefer_country": prefer_country,
                            "limit": args.limit,
                        },
                        db=session,
                    )
                    result = {
                        "query": name,
                        "limit": args.limit,
                        "null_role_ranks": null_ranks,
                        "prefer_country": prefer_country,
                        "wall_ms_with_explains": round((perf_counter() - started) * 1000, 2),
                        "ids": [
                            int(item.slug.removeprefix("perf-opp-")) for item in response.items
                        ],
                        "total": response.total,
                        "open_total": response.open_total,
                        "plans": list(plans),
                    }
                    results.append(result)
                    print(
                        name,
                        prefer_country,
                        [round(p["Execution Time"], 2) for p in plans],
                        "total=",
                        response.total,
                        flush=True,
                    )
        if not args.current_only:
            for before, after in zip(results[::2], results[1::2]):
                assert before["ids"] == after["ids"]
                assert before["total"] == after["total"]
                assert before["open_total"] == after["open_total"]
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(results, indent=2), encoding="utf-8")
    finally:
        feed.landing_feed_rows = current
        engine.dispose()


if __name__ == "__main__":
    main()
