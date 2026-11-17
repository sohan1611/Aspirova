"""Offline pass/fail cases; these tests never request a browser or database."""

import json
from copy import deepcopy

import pytest

from calendar_coverage import (
    assert_calendar_coverage,
    source_digest,
    wait_for_deployed_coverage,
)


def test_source_digest_pinned_sample() -> None:
    # Keep this pair and digest identical to the backend test.
    source = {"b": 2, "a": "é"}
    metadata = {"z": [1, True], "a": None}
    assert source_digest(source, metadata) == "4e770686f9d61150"
    reformatted = [
        json.loads(json.dumps(value, indent=2).replace("\n", "\r\n"))
        for value in (source, metadata)
    ]
    assert source_digest(*reformatted) == "4e770686f9d61150"
    assert source_digest({"a": "é", "b": 2}, {"a": None, "z": [1, True]}) == (
        "4e770686f9d61150"
    )
    assert source_digest(source, {**metadata, "changed": True}) != "4e770686f9d61150"


class FakePoller:
    def __init__(self, responses: list) -> None:
        self.responses = iter(responses)
        self.now = 0.0
        self.polls = 0
        self.waits = []

    def fetch(self) -> tuple[int, dict | None]:
        self.polls += 1
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response

    def sleep(self, seconds: float) -> None:
        self.waits.append(seconds)
        self.now += seconds

    def wait(self, expected: str = "deployed", **kwargs) -> dict:
        return wait_for_deployed_coverage(
            self.fetch,
            expected,
            sleep=self.sleep,
            clock=lambda: self.now,
            **kwargs,
        )


@pytest.mark.parametrize(
    "initial",
    [None, (404, None), (200, {"source_digest": "old"}), TimeoutError("retry")],
    ids=["first-poll", "404", "old-digest", "fetch-exception"],
)
def test_wait_for_deployed_coverage(initial, capsys) -> None:
    body = {"source_digest": "deployed"}
    responses = [(200, body)]
    if initial is not None:
        responses.insert(0, initial)
    poller = FakePoller(responses)
    assert poller.wait() is body
    assert poller.polls == len(responses)
    assert poller.waits == ([] if initial is None else [20])
    output = capsys.readouterr().out
    assert output == (
        ""
        if initial is None
        else "Calendar API served deployed data after 20.0s (2 polls)\n"
    )


@pytest.mark.parametrize(
    "response,last_status,last_digest",
    [
        ((200, {"source_digest": "old"}), "200", "old"),
        ((404, None), "404", "None"),
        ((200, {}), "200", "None"),
        (ConnectionError("offline"), "None", "None"),
        ((503, {"source_digest": "deployed"}), "503", "deployed"),
    ],
)
def test_wait_timeout_diagnoses_last_poll(response, last_status, last_digest) -> None:
    poller = FakePoller([response] * 3)
    with pytest.raises(AssertionError) as caught:
        poller.wait(timeout_s=25)
    message = str(caught.value)
    assert "expected digest deployed" in message
    assert f"last status {last_status}" in message
    assert f"last digest {last_digest}" in message
    assert "API never served the deployed calendar data" in message
    assert "check the Render deploy" in message
    assert poller.polls == 3
    assert poller.waits == [20, 5]


def healthy() -> dict:
    return {
        "source_rows": 10,
        "published_dated": 2,
        "published_rolling": 1,
        "outside_window": 2,
        "closed": 1,
        "retired": 1,
        "skipped": [{"row_id": "8", "slug": "skip", "reason": "category"}],
        "pending_import": [
            {"row_id": "9", "slug": "pending"},
            {"row_id": "10", "slug": "pending-too"},
        ],
        "unexplained": [],
        "published_total": 3,
        "rows_without_metadata": 0,
        "metadata_without_row": 0,
    }


def test_pending_import_is_allowed() -> None:
    assert_calendar_coverage(healthy(), 10)


@pytest.mark.parametrize(
    "change",
    [
        {"source_rows": 11},
        {"unexplained": [{"row_id": "bad", "slug": "bad"}]},
        {"rows_without_metadata": 1},
        {"metadata_without_row": 1},
        {"retired": 2},
        {"published_total": 4},
        {
            "published_dated": 0,
            "published_rolling": 0,
            "published_total": 0,
            "retired": 4,
        },
        {"published_dated": -1},
        {"published_dated": True},
        {"skipped": 1},
    ],
)
def test_bad_coverage_fails_with_pending_context(change: dict) -> None:
    coverage = deepcopy(healthy())
    coverage.update(change)
    with pytest.raises(AssertionError, match="pending_import"):
        assert_calendar_coverage(coverage, 10)


def test_checkout_count_must_match() -> None:
    with pytest.raises(AssertionError, match="Deployed JSON has 12 rows"):
        assert_calendar_coverage(healthy(), 12)
