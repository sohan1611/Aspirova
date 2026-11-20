import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy import SmallInteger, Text, cast, column, event, select, values
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from api.filters import student_rank_expression
from core.role_level import ROLE_LEVELS, classify_role_level, role_level_expression

FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "role_levels.json").read_text("utf-8"))


def test_postgres_python_parity(engine):
    # Evaluate the actual CASE on Postgres, rather than emulating its regex engine.
    fixtures = values(
        column("slug", Text),
        column("title", Text),
        column("category", Text),
        column("meta", JSONB),
        name="role_fixtures",
    ).data(
        [
            (str(index), row["title"], row.get("category", "job"), row.get("meta"))
            for index, row in enumerate(FIXTURES)
        ]
    )
    with engine.connect() as connection:
        results = connection.execute(
            select(fixtures.c.slug, role_level_expression(fixtures.c, overrides={}))
        ).all()
    assert len(results) >= 60
    for slug, level in results:
        row = FIXTURES[int(slug)]
        assert (
            level
            == classify_role_level(
                row["title"], row.get("category", "job"), row.get("meta"), overrides={}
            )["level"]
            == row["level"]
        ), row["title"]


@pytest.mark.parametrize("override_level", [None, *sorted(ROLE_LEVELS)])
def test_postgres_student_rank_parity(engine, override_level, monkeypatch):
    from core import role_level

    # Each override level is exercised on half of all fixture titles, with the
    # remaining rows checking the normal rules in the very same SQL expression.
    overrides = {
        str(index): {"slug": str(index), "level": override_level, "reason": "Reviewed fixture"}
        for index in range(len(FIXTURES))
        if override_level is not None and index % 2 == 0
    }
    monkeypatch.setattr(role_level, "ROLE_LEVEL_OVERRIDES", overrides)
    fixtures = values(
        column("slug", Text),
        column("title", Text),
        column("category", Text),
        column("meta", JSONB),
        column("role_rank", SmallInteger),
        name="rank_fixtures",
    ).data(
        [
            (str(index), row["title"], row.get("category", "job"), row.get("meta"), None)
            for index, row in enumerate(FIXTURES)
        ]
    )
    # An untyped NULL in VALUES is text; the real column is smallint.
    typed = select(
        fixtures.c.slug,
        fixtures.c.title,
        fixtures.c.category,
        fixtures.c.meta,
        cast(fixtures.c.role_rank, SmallInteger).label("role_rank"),
    ).subquery("typed_rank_fixtures")
    with engine.connect() as connection:
        results = connection.execute(select(typed.c.slug, student_rank_expression(typed.c))).all()
    assert len(results) == len(FIXTURES)
    for slug, rank in results:
        row = FIXTURES[int(slug)]
        level = classify_role_level(
            row["title"], row.get("category", "job"), row.get("meta"), slug
        )["level"]
        assert rank == {"internship": 0, "apprenticeship": 0, "experienced": 2}.get(level, 1), (
            slug,
            row["title"],
            override_level,
        )


def test_orm_fetches_trigger_rank_without_writing_it(engine):
    from core import models

    suffix = uuid.uuid4().hex
    statements = []
    with engine.connect() as connection:
        transaction = connection.begin()

        def capture(conn, cursor, statement, parameters, context, executemany):
            if statement.startswith(("INSERT INTO opportunities", "UPDATE opportunities")):
                statements.append(statement)

        event.listen(connection, "before_cursor_execute", capture)
        try:
            with Session(connection) as session:
                opportunity = models.Opportunity(
                    slug=f"stored-rank-orm-{suffix}",
                    title="Senior Engineer",
                    category="job",
                    apply_url=f"https://example.com/{suffix}",
                )
                session.add(opportunity)
                session.flush()
                assert opportunity.role_rank == 2
                opportunity.title = "Software Intern"
                session.flush()
                assert opportunity.role_rank == 0
        finally:
            event.remove(connection, "before_cursor_execute", capture)
            if transaction.is_active:
                transaction.rollback()
    assert len(statements) == 2
    assert "role_rank" not in statements[0].split(" RETURNING ", 1)[0]
    assert "role_rank" not in statements[1].split(" SET ", 1)[1].split(" WHERE ", 1)[0]


@pytest.mark.parametrize("level", sorted(ROLE_LEVELS))
def test_postgres_python_override_parity(engine, level, monkeypatch):
    from core import role_level

    override = {"slug": "checked", "level": level, "reason": "Employer confirmed level"}
    overrides = {"checked": override}
    monkeypatch.setattr(role_level, "ROLE_LEVEL_OVERRIDES", overrides)
    fixtures = values(
        column("slug", Text),
        column("title", Text),
        column("category", Text),
        column("meta", JSONB),
        name="override_fixture",
    ).data([("checked", "Senior Intern", "internship", {"eligible_experienced_only": True})])
    with engine.connect() as connection:
        assert (
            connection.scalar(select(role_level_expression(fixtures.c)))
            == classify_role_level(
                "Senior Intern",
                "internship",
                {"eligible_experienced_only": True},
                "checked",
            )["level"]
            == level
        )
