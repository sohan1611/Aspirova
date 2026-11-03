"""Read-only local report of anonymous action totals. Never run in public CI."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text

from core import models
from core.db import make_engine, verify_connection_guards


def main() -> None:
    today = datetime.now(UTC).date()
    start = today - timedelta(days=29)
    engine = make_engine()
    verify_connection_guards(engine)
    with engine.connect() as connection:
        connection.execute(text("SET TRANSACTION READ ONLY"))
        rows = connection.execute(
            select(
                models.OpportunityActionCount.day,
                models.OpportunityActionCount.action,
                func.sum(models.OpportunityActionCount.count),
            )
            .where(models.OpportunityActionCount.day.between(start, today))
            .group_by(models.OpportunityActionCount.day, models.OpportunityActionCount.action)
            .order_by(models.OpportunityActionCount.day, models.OpportunityActionCount.action)
        ).all()
        totals = {(day, action): count for day, action, count in rows}
        print("day (UTC)  apply  gate")
        for offset in range(30):
            day = start + timedelta(days=offset)
            print(f"{day}  {totals.get((day, 'apply'), 0)}  {totals.get((day, 'gate'), 0)}")
        views = connection.scalar(select(func.sum(models.OpportunityViewCount.views))) or 0
        print(f"Views (all time; daily views are not stored): {views}")


if __name__ == "__main__":
    main()
