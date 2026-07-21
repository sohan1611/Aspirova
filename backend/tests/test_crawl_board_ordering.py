from dataclasses import fields
from datetime import datetime, timezone
from random import Random

from crawlers.runner import _AtsJob, _order_ats_jobs


def _job(*, company_id: int, source_id: int, board_token: str) -> _AtsJob:
    values = {field.name: f"{field.name}-value" for field in fields(_AtsJob) if field.init}
    values.update(
        company_id=company_id,
        source_id=source_id,
        board_token=board_token,
    )
    return _AtsJob(**values)


def _board_tokens(jobs: list[_AtsJob]) -> list[str]:
    return [job.board_token for job in jobs]


def test_never_crawled_boards_sort_before_previously_crawled_boards() -> None:
    never_crawled = _job(company_id=10, source_id=1, board_token="never")
    crawled = _job(company_id=99, source_id=2, board_token="crawled")

    ordered = _order_ats_jobs(
        [crawled, never_crawled],
        {
            (crawled.source_id, crawled.board_token): datetime(2026, 7, 1, tzinfo=timezone.utc),
        },
    )

    assert _board_tokens(ordered) == ["never", "crawled"]


def test_never_crawled_boards_sort_by_descending_company_id() -> None:
    jobs = [
        _job(company_id=10, source_id=1, board_token="ten"),
        _job(company_id=30, source_id=2, board_token="thirty"),
        _job(company_id=20, source_id=3, board_token="twenty"),
    ]

    ordered = _order_ats_jobs(jobs, {})

    assert _board_tokens(ordered) == ["thirty", "twenty", "ten"]


def test_crawled_boards_keep_stalest_first() -> None:
    newer = _job(company_id=99, source_id=1, board_token="newer")
    older = _job(company_id=1, source_id=2, board_token="older")

    ordered = _order_ats_jobs(
        [newer, older],
        {
            (newer.source_id, newer.board_token): datetime(2026, 7, 2, tzinfo=timezone.utc),
            (older.source_id, older.board_token): datetime(2026, 7, 1, tzinfo=timezone.utc),
        },
    )

    assert _board_tokens(ordered) == ["older", "newer"]


def test_equal_crawled_timestamps_sort_by_descending_company_id() -> None:
    lower_id = _job(company_id=10, source_id=1, board_token="lower")
    higher_id = _job(company_id=20, source_id=2, board_token="higher")
    timestamp = datetime(2026, 7, 1, tzinfo=timezone.utc)

    ordered = _order_ats_jobs(
        [lower_id, higher_id],
        {
            (lower_id.source_id, lower_id.board_token): timestamp,
            (higher_id.source_id, higher_id.board_token): timestamp,
        },
    )

    assert _board_tokens(ordered) == ["higher", "lower"]


def test_ats_job_ordering_orders_mixed_jobs_end_to_end() -> None:
    jobs = [
        _job(company_id=10, source_id=1, board_token="newer-crawled"),
        _job(company_id=50, source_id=2, board_token="never-newest"),
        _job(company_id=30, source_id=3, board_token="same-time-lower-id"),
        _job(company_id=40, source_id=4, board_token="never-older"),
        _job(company_id=60, source_id=5, board_token="oldest-crawled"),
        _job(company_id=35, source_id=6, board_token="same-time-higher-id"),
    ]
    timestamp = datetime(2026, 7, 2, tzinfo=timezone.utc)

    ordered = _order_ats_jobs(
        jobs,
        {
            (1, "newer-crawled"): datetime(2026, 7, 3, tzinfo=timezone.utc),
            (3, "same-time-lower-id"): timestamp,
            (5, "oldest-crawled"): datetime(2026, 7, 1, tzinfo=timezone.utc),
            (6, "same-time-higher-id"): timestamp,
        },
    )

    assert _board_tokens(ordered) == [
        "never-newest",
        "never-older",
        "oldest-crawled",
        "same-time-higher-id",
        "same-time-lower-id",
        "newer-crawled",
    ]


def test_ats_job_ordering_is_deterministic_after_shuffle() -> None:
    jobs = [
        _job(company_id=10, source_id=1, board_token="a"),
        _job(company_id=40, source_id=2, board_token="b"),
        _job(company_id=30, source_id=3, board_token="c"),
        _job(company_id=20, source_id=4, board_token="d"),
    ]
    last_crawled_by_board = {
        (1, "a"): datetime(2026, 7, 3, tzinfo=timezone.utc),
        (3, "c"): datetime(2026, 7, 1, tzinfo=timezone.utc),
    }
    shuffled = jobs.copy()
    Random(7).shuffle(shuffled)

    expected = _board_tokens(_order_ats_jobs(jobs, last_crawled_by_board))

    assert _board_tokens(_order_ats_jobs(jobs, last_crawled_by_board)) == expected
    assert _board_tokens(_order_ats_jobs(shuffled, last_crawled_by_board)) == expected
