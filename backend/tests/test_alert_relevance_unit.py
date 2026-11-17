import csv
from html import unescape

import pytest

from core import models
from core.alert_relevance import (
    UNKNOWN_ELIGIBILITY,
    eligibility_for,
    graduation_batches,
    pick_reason,
)
from pipeline.notifications import _render_digest
from scripts import alert_gold_set as gold
from tests.test_alert_reasons import NOW, _opportunity


@pytest.mark.parametrize(
    "text,expected",
    [
        ("2026 batch", [2026]),
        ("graduating in 2027", [2027]),
        ("2025/2026 passouts", [2025, 2026]),
        ("2025, 2026 and 2027 graduates", [2025, 2026, 2027]),
        ("Graduation year: 2026", [2026]),
        ("Batch of <b>2026</b>", [2026]),
        ("2026 batch and 2027 batch", [2026, 2027]),
        ("Apply by 2026-11-30; event in 2027", []),
        ("2026 internship", []),
        ("2025-2027 batch", []),
        ("2025 - 2027 batch", []),
        ("2026 batch not eligible", []),
        ("Not for 2026 batch", []),
        ("2026 graduates preferred", []),
        ("2026 batch excluded", []),
        ("2026 batch or earlier", []),
        ("graduating in 2026 or later", []),
        ("After 2025 batch", []),
        ("2026/27 passouts", []),
    ],
)
def test_conservative_batch_parser(text, expected):
    assert graduation_batches(text) == expected


def test_only_explicit_batch_mismatch_excludes_and_unknown_is_honest():
    user = models.User(graduation_year=2026, field_profile={"country": "IN"})
    opportunity = _opportunity(1, "internship")
    unknown = eligibility_for(opportunity, user)
    assert not unknown.excluded and unknown.text == UNKNOWN_ELIGIBILITY
    opportunity.description_raw = "Open to 2025/2026 passouts"
    matched = eligibility_for(opportunity, user)
    assert not matched.excluded and "Open to 2026 graduates" in matched.text
    opportunity.description_raw = "graduating in 2027"
    assert eligibility_for(opportunity, user).excluded
    user.graduation_year = None
    assert not eligibility_for(opportunity, user).excluded
    assert "Open to" not in eligibility_for(opportunity, user).text


def test_work_authorization_requires_explicit_structured_source_evidence():
    user = models.User(field_profile={"country": "IN"})
    opportunity = _opportunity(1, "internship")
    opportunity.country = "US"
    opportunity.description_raw = "US citizens only; work authorization required"
    assert not eligibility_for(opportunity, user).excluded  # prose/location are insufficient
    opportunity.meta = {"eligibility": ["Undergraduate", "Work authorization required"]}
    assert eligibility_for(opportunity, user).excluded
    user.field_profile = {"country": "US"}
    signal = eligibility_for(opportunity, user)
    assert not signal.excluded and "verify at source" in signal.text
    assert "eligible" not in signal.text.lower()
    user.field_profile = {}
    assert not eligibility_for(opportunity, user).excluded
    opportunity.country = None
    user.field_profile = {"country": "IN"}
    assert not eligibility_for(opportunity, user).excluded
    opportunity.country = "US"
    opportunity.meta = {"eligibility": ["No work authorization required", "All"]}
    assert not eligibility_for(opportunity, user).excluded


def test_reason_and_unknown_label_render_escaped_in_both_parts():
    user = models.User()
    opportunity = _opportunity(1, "internship")
    reason = pick_reason(
        opportunity, user, "skill", "Uses your skill: <Python>", matched_term="python", rank=0.25
    )
    html, text = _render_digest([opportunity], now=NOW, reasons={"1": reason})
    for rendered in (unescape(html), text):
        assert reason["text"] in rendered
        assert UNKNOWN_ELIGIBILITY in rendered
    assert "<Python>" not in html


def test_gold_score_math_false_claims_and_cli_codes(tmp_path, capsys, monkeypatch):
    path = tmp_path / "gold.csv"
    rows = [
        dict(notification_id=1, opportunity_slug="one", relevant="y", eligible_claim_correct="y"),
        dict(notification_id=2, opportunity_slug="two", relevant="n", eligible_claim_correct=""),
        dict(notification_id=3, opportunity_slug="three", relevant="", eligible_claim_correct="n"),
    ]
    gold.write_sample(rows, path)
    monkeypatch.setattr(
        gold, "create_engine", lambda *a, **kw: pytest.fail("score must be offline")
    )
    assert gold.main(["score", str(path)]) == 1
    output = capsys.readouterr().out
    assert "50.00% (1/2 labelled)" in output and "notification 3, opportunity three" in output
    rows[-1]["eligible_claim_correct"] = "y"
    gold.write_sample(rows, path)
    assert gold.main(["score", str(path)]) == 0
    rows[0]["relevant"] = "maybe"
    gold.write_sample(rows, path)
    assert gold.main(["score", str(path)]) == 2
    gold.write_sample([], path)
    assert gold.main(["score", str(path)]) == 2


def test_sample_columns_exclude_contact_identity_and_quote_formulas(tmp_path):
    path = tmp_path / "gold.csv"
    gold.write_sample(
        [{"title": "=HYPERLINK(1)", "email": "private", "display_name": "private"}], path
    )
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        assert tuple(reader.fieldnames) == gold.COLUMNS
        assert not {"email", "name", "display_name", "user_id"}.intersection(reader.fieldnames)
        assert next(reader)["title"].startswith("'=")
    assert "private" not in path.read_text(encoding="utf-8")


def test_sample_is_one_select_with_no_user_contact_columns():
    from sqlalchemy.dialects import postgresql

    statements = []

    class Session:
        def execute(self, query):
            statements.append(str(query.compile(dialect=postgresql.dialect())))
            return self

        def all(self):
            return []

    assert gold.sample_rows(Session(), 100) == []
    assert len(statements) == 1
    assert "jsonb_each" in statements[0]
    assert "users" not in statements[0] and "email" not in statements[0]


def test_sample_cli_uses_read_only_transaction(tmp_path, monkeypatch):
    observed = {}

    class Context:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execution_options(self, **options):
            observed.update(options)
            return self

        def begin(self):
            return self

        def connect(self):
            return self

        def dispose(self):
            observed["disposed"] = True

    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://localhost/fixture_only")
    monkeypatch.setattr(gold, "create_engine", lambda *args, **kwargs: Context())
    monkeypatch.setattr(gold, "Session", lambda **kwargs: Context())
    monkeypatch.setattr(gold, "sample_rows", lambda *args: [])
    assert gold.main(["sample", "--n", "100", "--out", str(tmp_path / "gold.csv")]) == 0
    assert observed == {"postgresql_readonly": True, "disposed": True}


def test_profile_queries_bound_transfer_and_defer_term_evidence_until_final_picks():
    from types import SimpleNamespace

    from sqlalchemy.dialects import postgresql

    from pipeline import notifications as worker

    source = _opportunity(1, "internship")
    source.apply_url = "https://arbeitnow.com/jobs/intern"
    direct = _opportunity(2, "internship")
    direct.title = source.title
    direct.company = source.company
    direct.apply_url = "https://jobs.lever.co/example/intern"
    user = models.User(
        field_profile={"stream": "engineering", "divisions": ["cse"], "interests": ["data_science"]}
    )
    statements = []

    class Result:
        def __init__(self, rows):
            self.rows = rows

        def unique(self):
            return self

        def all(self):
            return self.rows

    class Session:
        def execute(self, query):
            statements.append(query.compile(dialect=postgresql.dialect()))
            if len(statements) == 1:
                assert query._limit_clause.value == 60
                return Result([SimpleNamespace(Opportunity=source, profile_rank=0.5)])
            return Result([SimpleNamespace(id=source.id, matched_term_index=0)])

        def scalars(self, query):
            statements.append(query.compile(dialect=postgresql.dialect()))
            return Result([source, direct])

    session = Session()
    rows, evidence, blocked = worker._profile_recent_opportunities(
        session, user, NOW, NOW, frozenset(), "IN"
    )
    assert [o.id for o in rows] == [direct.id] and not blocked
    assert len(statements) == 2
    assert "description_raw" not in str(statements[0])
    assert "embedding" not in str(statements[0]) and "summary" not in str(statements[0])
    assert "matched_term_index" not in str(statements[0])
    assert "description_raw" in str(statements[1])
    reasons = worker._profile_pick_reasons(session, user, rows, evidence)
    assert len(statements) == 3
    assert "matched_term_index" in str(statements[2])
    assert "description_raw" not in str(statements[2])
    assert reasons[direct.id]["code"] == "profile_interest"
    assert reasons[direct.id]["matched_term"] == "data science"
    assert reasons[direct.id]["match_source_id"] == source.id
    assert reasons[direct.id]["rank"] == 0.5
