"""Offline tests for retrying paid upgrades with failed Razorpay plan edits."""

from types import SimpleNamespace
from typing import Any

import pytest

from scripts.reconcile_upgrades import reconcile_upgrades


@pytest.fixture(scope="session", autouse=True)
def _purge_isolation_test_residue():
    """Override the repository-wide DB cleanup fixture for this DB-free module."""

    yield


UpgradeRow = tuple[SimpleNamespace, SimpleNamespace, SimpleNamespace]


class FakeResult:
    def __init__(self, rows: list[UpgradeRow]) -> None:
        self._rows = rows

    def all(self) -> list[UpgradeRow]:
        return self._rows


class FakeSession:
    """In-memory subset of Session used by reconciliation."""

    def __init__(self, rows: list[UpgradeRow]) -> None:
        self.rows = rows
        self.commit_calls = 0
        self.statements: list[Any] = []

    def execute(self, statement: Any) -> FakeResult:
        self.statements.append(statement)
        return FakeResult([row for row in self.rows if row[0].status == "applied_with_error"])

    def commit(self) -> None:
        self.commit_calls += 1


class FakeRazorpaySubscription:
    def __init__(self, parent: "FakeRazorpayClient") -> None:
        self._parent = parent

    def edit(self, subscription_id: str | None, payload: dict[str, Any]) -> None:
        self._parent.edit_calls.append((subscription_id, payload))
        if subscription_id in self._parent.fail_subscription_ids:
            raise RuntimeError("simulated Razorpay subscription edit failure")


class FakeRazorpayClient:
    def __init__(self, fail_subscription_ids: set[str | None] | None = None) -> None:
        self.edit_calls: list[tuple[str | None, dict[str, Any]]] = []
        self.fail_subscription_ids = fail_subscription_ids or set()
        self.subscription = FakeRazorpaySubscription(self)


def _row(upgrade_id: int, *, status: str = "applied_with_error") -> UpgradeRow:
    upgrade = SimpleNamespace(id=upgrade_id, status=status)
    subscription = SimpleNamespace(razorpay_sub_id=f"sub_reconcile_{upgrade_id}")
    target_plan = SimpleNamespace(
        key=f"pro_reconcile_{upgrade_id}",
        razorpay_plan_id=f"plan_reconcile_{upgrade_id}",
    )
    return upgrade, subscription, target_plan


def test_reconcile_success_marks_upgrade_applied(capsys) -> None:
    row = _row(101)
    upgrade, subscription, target_plan = row
    session = FakeSession([row])
    client = FakeRazorpayClient()

    assert reconcile_upgrades(session, client) == (1, 1, 0)
    assert upgrade.status == "applied"
    assert session.commit_calls == 1
    assert client.edit_calls == [
        (
            subscription.razorpay_sub_id,
            {
                "plan_id": target_plan.razorpay_plan_id,
                "schedule_change_at": "cycle_end",
            },
        )
    ]
    assert "upgrade 101: applied_with_error -> applied" in capsys.readouterr().out


def test_reconcile_failure_keeps_applied_with_error(capsys) -> None:
    row = _row(102)
    upgrade, subscription, _target_plan = row
    session = FakeSession([row])
    client = FakeRazorpayClient({subscription.razorpay_sub_id})

    assert reconcile_upgrades(session, client) == (1, 0, 1)
    assert upgrade.status == "applied_with_error"
    assert session.commit_calls == 0
    assert len(client.edit_calls) == 1
    assert "simulated Razorpay subscription edit failure" in capsys.readouterr().out


def test_reconcile_ignores_other_statuses() -> None:
    retry_row = _row(103)
    other_rows = [
        _row(104, status="applied"),
        _row(105, status="pending"),
        _row(106, status="paid"),
        _row(107, status="failed"),
    ]
    session = FakeSession([retry_row, *other_rows])
    client = FakeRazorpayClient()

    assert reconcile_upgrades(session, client) == (1, 1, 0)
    assert retry_row[0].status == "applied"
    assert [row[0].status for row in other_rows] == ["applied", "pending", "paid", "failed"]
    assert len(client.edit_calls) == 1
    assert "applied_with_error" in session.statements[0].compile().params.values()


def test_reconcile_dry_run_does_not_call_razorpay_or_change_status(capsys) -> None:
    first_row = _row(108)
    second_row = _row(109)
    session = FakeSession([first_row, second_row])
    client = FakeRazorpayClient()

    assert reconcile_upgrades(session, client, dry_run=True) == (2, 0, 2)
    assert [first_row[0].status, second_row[0].status] == [
        "applied_with_error",
        "applied_with_error",
    ]
    assert session.commit_calls == 0
    assert client.edit_calls == []
    output = capsys.readouterr().out
    assert "would retry upgrade 108" in output
    assert "would retry upgrade 109" in output


def test_reconcile_continues_after_first_failure() -> None:
    first_row = _row(110)
    second_row = _row(111)
    first_upgrade, first_subscription, _first_target_plan = first_row
    second_upgrade, second_subscription, _second_target_plan = second_row
    session = FakeSession([first_row, second_row])
    client = FakeRazorpayClient({first_subscription.razorpay_sub_id})

    assert reconcile_upgrades(session, client) == (2, 1, 1)
    assert first_upgrade.status == "applied_with_error"
    assert second_upgrade.status == "applied"
    assert [call[0] for call in client.edit_calls] == [
        first_subscription.razorpay_sub_id,
        second_subscription.razorpay_sub_id,
    ]
    assert session.commit_calls == 1
