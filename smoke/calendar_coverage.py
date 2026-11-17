"""Pure, database-free comparison used by the deploy smoke canary."""

COUNT_BUCKETS = (
    "published_dated",
    "published_rolling",
    "outside_window",
    "closed",
    "retired",
)
ROW_BUCKETS = ("skipped", "pending_import", "unexplained")


def assert_calendar_coverage(coverage: dict, source_rows: int) -> None:
    # Pending import is context, not a failure: the daily refresh owns that gate.
    context = f"Calendar coverage (pending_import allowed): {coverage!r}"
    for field in (*COUNT_BUCKETS, "source_rows", "published_total"):
        value = coverage.get(field)
        assert type(value) is int and value >= 0, f"Invalid {field}; {context}"
    for field in ROW_BUCKETS:
        assert isinstance(coverage.get(field), list), f"Invalid {field}; {context}"
    assert (
        coverage["source_rows"] == source_rows
    ), f"Deployed JSON has {source_rows} rows; {context}"
    assert coverage["unexplained"] == [], context
    assert coverage.get("rows_without_metadata") == 0, context
    assert coverage.get("metadata_without_row") == 0, context
    partition = sum(coverage[field] for field in COUNT_BUCKETS) + sum(
        len(coverage[field]) for field in ROW_BUCKETS
    )
    assert partition == source_rows, f"Bucket sum {partition}; {context}"
    assert coverage["published_total"] == (
        coverage["published_dated"] + coverage["published_rolling"]
    ), context
    assert coverage["published_total"] > 0, context
