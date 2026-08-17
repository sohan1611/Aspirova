from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import text

from core.db import make_engine, verify_connection_guards

STALE_AFTER_HOURS = 48.0


@dataclass(frozen=True)
class SourceStaleness:
    adapter_key: str
    source_type: str | None
    last_success: datetime | None
    age_hours: float | None
    stale: bool


def _format_timestamp(value: datetime | None) -> str:
    if value is None:
        return "never"
    return value.astimezone(timezone.utc).isoformat()


def _format_days(age_hours: float | None) -> str:
    if age_hours is None:
        return "inf"
    return f"{age_hours / 24.0:.2f}"


def _load_staleness(now: datetime) -> list[SourceStaleness]:
    engine = make_engine()
    verify_connection_guards(engine)
    with engine.connect() as conn:
        rows = conn.execute(text("""
                select
                  s.adapter_key,
                  s.type as source_type,
                  max(cr.finished_at) filter (where cr.status = 'success') as last_success
                from sources s
                left join crawl_runs cr on cr.source_id = s.id
                where s.enabled is true
                group by s.id, s.adapter_key, s.type
                order by s.type, s.adapter_key
                """)).mappings()

        result: list[SourceStaleness] = []
        for row in rows:
            last_success = row["last_success"]
            if last_success is not None and last_success.tzinfo is None:
                last_success = last_success.replace(tzinfo=timezone.utc)
            age_hours = (
                None
                if last_success is None
                else (now - last_success.astimezone(timezone.utc)).total_seconds() / 3600.0
            )
            result.append(
                SourceStaleness(
                    adapter_key=row["adapter_key"],
                    source_type=row["source_type"],
                    last_success=last_success,
                    age_hours=age_hours,
                    stale=age_hours is None or age_hours > STALE_AFTER_HOURS,
                )
            )
    return result


def print_staleness_summary(now: datetime | None = None) -> int:
    checked_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    sources = _load_staleness(checked_at)
    stale_sources = [source for source in sources if source.stale]

    print(
        "CRAWL STALENESS SUMMARY: "
        f"enabled_sources={len(sources)} threshold_hours={STALE_AFTER_HOURS:.0f} "
        f"checked_at={checked_at.isoformat()}",
        flush=True,
    )
    for source in sources:
        status = "STALE" if source.stale else "OK"
        print(
            "CRAWL STALENESS: "
            f"{source.adapter_key} type={source.source_type or 'unknown'} "
            f"last_success={_format_timestamp(source.last_success)} "
            f"days_since={_format_days(source.age_hours)} status={status}",
            flush=True,
        )

    if stale_sources:
        names = ", ".join(source.adapter_key for source in stale_sources)
        print(
            "CRAWL STALENESS ALARM: "
            f"{len(stale_sources)} enabled sources exceeded {STALE_AFTER_HOURS:.0f}h: {names}",
            flush=True,
        )
    else:
        print("CRAWL STALENESS ALARM: all enabled sources are within threshold", flush=True)

    return len(stale_sources)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fail-on-stale", action="store_true")
    args = parser.parse_args()
    stale_count = print_staleness_summary()
    if args.fail_on_stale and stale_count:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
