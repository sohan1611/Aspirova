"""Budget accounting has no per-email database work."""

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from core.config import Settings, get_settings
from core.email_budget import EmailBudget, utc_midnight


def test_snapshot_queries_once_and_checks_are_local(monkeypatch):
    monkeypatch.setattr(get_settings(), "email_daily_budget", 10)
    monkeypatch.setattr(get_settings(), "email_digest_reserve", 3)
    session = Mock()
    session.scalar.return_value = 0
    budget = EmailBudget.for_step(session, datetime(2035, 1, 2, tzinfo=timezone.utc))
    for _ in range(7):
        assert budget.can_send("digest")
        budget.record_sent()
    for _ in range(100):
        assert not budget.can_send("digest")
        assert budget.remaining() == 3
    for kind in ("closing_soon", "saved_search_alert", "weekly_report"):
        assert budget.can_send(kind)
        budget.record_sent()
    assert not budget.can_send("instant_alert")
    assert budget.remaining() == 0
    session.scalar.assert_called_once()


@pytest.mark.parametrize("total,reserve", [(0, 0), (2, 10)])
def test_reserve_cannot_make_digest_allowance_negative(total, reserve):
    budget = EmailBudget(0, total, reserve)
    assert not budget.can_send("digest")
    assert budget.can_send("closing_soon") == (total > 0)


def test_utc_midnight_uses_utc_day():
    local = datetime(2035, 1, 2, 0, 30, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    assert utc_midnight(local) == datetime(2035, 1, 1, tzinfo=timezone.utc)
    assert utc_midnight(datetime(2035, 1, 2, 3)) == datetime(2035, 1, 2, tzinfo=timezone.utc)


def test_budget_settings_are_env_driven(monkeypatch):
    monkeypatch.setenv("EMAIL_DAILY_BUDGET", "10")
    monkeypatch.setenv("EMAIL_DIGEST_RESERVE", "3")
    settings = Settings(_env_file=None)
    assert (settings.email_daily_budget, settings.email_digest_reserve) == (10, 3)
