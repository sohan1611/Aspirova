from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from api.feed import get_feed
from core import models


class _CaptureResult:
    def unique(self):
        return self

    def all(self) -> list:
        return []


class _CaptureSession:
    statement: Any | None = None

    def execute(self, statement):
        self.statement = statement
        return _CaptureResult()


def _compiled_sql(statement) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": False},
        )
    ).lower()


def test_feed_list_query_does_not_select_heavy_opportunity_columns() -> None:
    db = _CaptureSession()

    response = get_feed(
        category=None,
        kind=None,
        remote=None,
        company=None,
        location=None,
        scope=None,
        country=None,
        remote_abroad=False,
        source=None,
        experience=None,
        top=None,
        sort="student",
        page=1,
        limit=20,
        db=db,
    )

    assert response.model_dump() == {"items": [], "total": 0, "page": 1, "limit": 20}
    assert db.statement is not None
    compiled = _compiled_sql(db.statement)
    assert "description_raw" not in compiled
    assert "search_tsv" not in compiled
    assert "opportunities.embedding" not in compiled
    assert "opportunities.slug" in compiled
    assert "opportunities.title" in compiled
    assert "opportunities.location" in compiled


def test_full_opportunity_entity_select_defers_search_tsv_only() -> None:
    compiled = str(select(models.Opportunity)).lower()

    assert "search_tsv" not in compiled
    assert "description_raw" in compiled
    assert "opportunities.embedding" in compiled
