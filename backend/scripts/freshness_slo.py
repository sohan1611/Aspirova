"""Read-only freshness SLO report. Never fetches destinations or prints rows/URLs."""

from sqlalchemy import case, func, literal, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from api.filters import open_opportunity_filters
from core import models
from core.db import make_engine
from core.freshness import SOURCE_CADENCE, cadence_value, stale_expression, verified_expression


def measure(connection: Connection | Session) -> list[dict]:
    verified_at = verified_expression()
    never_verified = verified_at.is_(None)
    hours = case(
        (never_verified, None),
        else_=func.greatest(0, func.extract("epoch", func.now() - verified_at) / 3600.0),
    )
    visible = (
        select(
            case(
                {key: key for key in SOURCE_CADENCE},
                value=models.Opportunity.primary_source,
                else_="other",
            ).label("source"),
            cadence_value("tier").label("tier"),
            cadence_value("target_hours").label("target_hours"),
            hours.label("hours"),
            never_verified.label("never"),
            stale_expression().label("stale"),
            (hours <= cadence_value("target_hours")).label("within_target"),
        )
        # Today's catalogue uses the Binding age rule alone. Measure impact on
        # that unchanged population, rather than silently dropping the new stale rows.
        .where(*open_opportunity_filters(require_recent_verification=False)).cte("visible")
    )
    metrics = [
        func.count().label("visible"),
        func.count().filter(visible.c.never).label("never"),
        func.count().filter(visible.c.stale).label("stale"),
        func.count().filter(visible.c.within_target & ~visible.c.never).label("within"),
        func.max(visible.c.target_hours).label("target_hours"),
        *[
            func.percentile_cont(p).within_group(visible.c.hours).label(label)
            for p, label in ((0.5, "p50"), (0.9, "p90"), (0.99, "p99"))
        ],
    ]
    result = []
    for scope in ("source", "tier"):
        key = visible.c[scope]
        for row in connection.execute(
            select(key.label("key"), *metrics).group_by(key).order_by(key)
        ).mappings():
            result.append({"scope": scope, **row})
    total = connection.execute(select(literal("all").label("key"), *metrics)).mappings().one()
    result.append({"scope": "total", **total})
    return result


def report(rows: list[dict]) -> None:
    for row in rows:
        count = row["visible"]
        if row["scope"] in {"source", "total"}:
            print(
                f"FRESHNESS IMPACT: {row['scope']}={row['key']} currently_visible={count} "
                f"would_be_hidden_or_stale={row['stale']} remaining_visible={count - row['stale']}",
                flush=True,
            )
        if row["scope"] == "total":
            continue
        pct = 100.0 * row["within"] / count if count else 0.0
        quantiles = " ".join(
            f"{key}_hours={float(row[key]):.2f}" if row[key] is not None else f"{key}_hours=unknown"
            for key in ("p50", "p90", "p99")
        )
        print(
            f"FRESHNESS SLO: {row['scope']}={row['key']} visible={count} never={row['never']} "
            f"stale={row['stale']} target_hours={row['target_hours']} within_target={pct:.2f}% {quantiles}",
            flush=True,
        )
    present = {row["key"] for row in rows if row["scope"] == "source"}
    for key in sorted(SOURCE_CADENCE.keys() - present):
        print(f"FRESHNESS SLO: source={key} visible=0 within_target=n/a", flush=True)
        print(
            f"FRESHNESS IMPACT: source={key} currently_visible=0 would_be_hidden_or_stale=0 remaining_visible=0",
            flush=True,
        )
    tiers = {row["key"] for row in rows if row["scope"] == "tier"}
    for key in sorted({1, 2, 3} - tiers):
        print(f"FRESHNESS SLO: tier={key} visible=0 within_target=n/a", flush=True)


def main() -> None:
    engine = None
    try:
        engine = make_engine()
        with engine.connect() as connection, connection.begin():
            # Must precede every SELECT. Both source and tier share one snapshot.
            connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
            connection.execute(text("SET LOCAL statement_timeout = '120s'"))
            rows = measure(connection)
        report(rows)
    except SQLAlchemyError:
        print("FRESHNESS SLO: unavailable errors=1", flush=True)
        raise SystemExit(1) from None
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    main()
