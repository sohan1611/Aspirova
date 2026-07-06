"""Integration tests for the offline, templated weekly career report."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import pipeline.weekly_report as weekly_report_module
from core import models
from core.ai_client import GenerationResult
from core.config import get_settings
from pipeline.weekly_report import send_weekly_reports


@pytest.fixture
def db_session(engine):
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture(autouse=True)
def blank_anthropic_key(monkeypatch) -> None:
    # The developer .env can contain a real key. Weekly-report tests must
    # never reach the provider, even when the full suite runs locally.
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "")


@pytest.fixture
def sent_emails(monkeypatch):
    calls: list[dict[str, str]] = []

    def fake_send(to: str, subject: str, html: str, text: str) -> bool:
        calls.append({"to": to, "subject": subject, "html": html, "text": text})
        return True

    monkeypatch.setattr(weekly_report_module.email_client, "send_email", fake_send)
    return calls


def _free_plan(db_session: Session) -> models.Plan:
    plan = db_session.scalar(select(models.Plan).where(models.Plan.key == "free"))
    if plan is None:
        plan = models.Plan(key="free", price_paise=0, billing=None, features={})
        db_session.add(plan)
        db_session.flush()
    plan.features = {**plan.features, "weekly_report": False}
    db_session.flush()
    return plan


def _paid_plan(db_session: Session, tier: str) -> models.Plan:
    plan = models.Plan(
        key=f"{tier}-weekly-report-test-{uuid.uuid4()}",
        price_paise=4900,
        billing="monthly",
        features={"weekly_report": True},
    )
    db_session.add(plan)
    db_session.flush()
    return plan


def _user(db_session: Session, label: str) -> models.User:
    user = models.User(
        email=f"weekly-report-{label}-{uuid.uuid4()}@example.com",
        display_name=f"Weekly {label}",
    )
    db_session.add(user)
    db_session.flush()
    return user


def _subscribe(db_session: Session, user: models.User, plan: models.Plan) -> None:
    db_session.add(models.Subscription(user_id=user.id, plan_id=plan.id, status="active"))
    db_session.flush()


def _company(db_session: Session, suffix: str) -> models.Company:
    company = models.Company(
        slug=f"weekly-report-company-{suffix}",
        name=f"Weekly Report Company {suffix}",
        name_normalized=f"weekly report company {suffix}",
    )
    db_session.add(company)
    db_session.flush()
    return company


def _opportunity(
    db_session: Session,
    *,
    suffix: str,
    title: str,
    company: models.Company,
    now: datetime,
    deadline: datetime | None = None,
    is_hidden: bool = False,
) -> models.Opportunity:
    opportunity = models.Opportunity(
        slug=f"weekly-report-opportunity-{suffix}-{uuid.uuid4()}",
        company_id=company.id,
        title=title,
        apply_url=f"https://example.com/weekly-report/{suffix}",
        deadline=deadline,
        deadline_confidence="explicit" if deadline else "unknown",
        is_hidden=is_hidden,
        status="active",
        first_seen_at=now,
        last_seen_at=now,
    )
    db_session.add(opportunity)
    db_session.flush()
    return opportunity


def test_paid_user_gets_templated_precomputed_report_and_free_user_does_not(
    db_session: Session, sent_emails
) -> None:
    _free_plan(db_session)
    paid_plan = _paid_plan(db_session, "pro_lite")
    paid_user = _user(db_session, "eligible")
    free_user = _user(db_session, "free")
    _subscribe(db_session, paid_user, paid_plan)

    now = datetime.now(timezone.utc)
    suffix = str(uuid.uuid4())
    dream_company = _company(db_session, f"dream-{suffix}")
    other_company = _company(db_session, f"other-{suffix}")
    dream_match = _opportunity(
        db_session,
        suffix=f"dream-{suffix}",
        title=f"Dream Match {suffix}",
        company=dream_company,
        now=now,
    )
    closing = _opportunity(
        db_session,
        suffix=f"closing-{suffix}",
        title=f"Closing Soon {suffix}",
        company=other_company,
        now=now,
        deadline=now + timedelta(seconds=1),
    )
    hidden = _opportunity(
        db_session,
        suffix=f"hidden-{suffix}",
        title=f"Hidden Opportunity {suffix}",
        company=other_company,
        now=now,
        is_hidden=True,
    )
    db_session.add(models.DreamCompany(user_id=paid_user.id, company_id=dream_company.id))
    db_session.flush()

    baseline_usage_id = db_session.scalar(select(func.max(models.AiUsage.id))) or 0
    result = send_weekly_reports(db_session, now=now)

    paid_deliveries = [email for email in sent_emails if email["to"] == paid_user.email]
    assert len(paid_deliveries) == 1
    assert not [email for email in sent_emails if email["to"] == free_user.email]
    assert result["sent"] >= 1
    assert result["skipped_ineligible"] >= 1

    text = paid_deliveries[0]["text"]
    assert "Dream-company matches" in text
    assert "Closing soon" in text
    assert "New hidden opportunities" in text
    assert dream_match.title in text
    assert closing.title in text
    assert hidden.title in text
    assert dream_match.apply_url in text
    assert closing.apply_url in text
    assert hidden.apply_url in text
    assert "AI-assisted overview" not in text

    generation_rows = db_session.scalar(
        select(func.count())
        .select_from(models.AiUsage)
        .where(
            models.AiUsage.id > baseline_usage_id,
            models.AiUsage.feature == "weekly_report.intro",
        )
    )
    assert generation_rows == 0


def test_same_iso_week_rerun_does_not_resend(db_session: Session, sent_emails) -> None:
    _free_plan(db_session)
    plan = _paid_plan(db_session, "pro")
    user = _user(db_session, "dedup")
    _subscribe(db_session, user, plan)
    now = datetime.now(timezone.utc)

    send_weekly_reports(db_session, now=now)
    first_count = sum(email["to"] == user.email for email in sent_emails)
    second_result = send_weekly_reports(db_session, now=now)
    second_count = sum(email["to"] == user.email for email in sent_emails)

    assert first_count == 1
    assert second_count == 1
    assert second_result["skipped_already_sent"] >= 1
    notifications = list(
        db_session.scalars(
            select(models.Notification).where(
                models.Notification.user_id == user.id,
                models.Notification.type == "weekly_report",
                models.Notification.status == "sent",
            )
        ).all()
    )
    assert len(notifications) == 1


def test_keyed_multi_user_run_generates_at_most_one_shared_intro(
    db_session: Session, sent_emails, monkeypatch
) -> None:
    _free_plan(db_session)
    plan = _paid_plan(db_session, "pro")
    first_user = _user(db_session, "cohort-one")
    second_user = _user(db_session, "cohort-two")
    _subscribe(db_session, first_user, plan)
    _subscribe(db_session, second_user, plan)

    monkeypatch.setattr(get_settings(), "anthropic_api_key", "test-only-key")
    monkeypatch.setattr(
        weekly_report_module.ai_budget,
        "is_over_budget",
        lambda *args, **kwargs: False,
    )
    generation_calls: list[str] = []

    def fake_generate(session, *, feature, prompt=None, system=None, messages=None):
        assert session is db_session
        assert feature == "weekly_report.intro"
        generation_calls.append(feature)
        return GenerationResult(
            text="Prioritize the strongest matches first, then check every approaching deadline.",
            input_tokens=10,
            output_tokens=12,
        )

    monkeypatch.setattr(weekly_report_module.ai_client, "generate", fake_generate)

    send_weekly_reports(db_session, now=datetime.now(timezone.utc))

    assert generation_calls == ["weekly_report.intro"]
    for user in (first_user, second_user):
        deliveries = [email for email in sent_emails if email["to"] == user.email]
        assert len(deliveries) == 1
        assert "AI-assisted overview" in deliveries[0]["text"]
        assert "Prioritize the strongest matches" in deliveries[0]["text"]
