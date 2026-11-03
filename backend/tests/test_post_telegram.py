"""Coverage for Telegram selection, previews and successful-send recording."""

import json
import logging
import uuid
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from core import models
from scripts import post_telegram as telegram


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


@pytest.fixture
def company(db_session: Session, monkeypatch) -> models.Company:
    suffix = uuid.uuid4().hex
    company = models.Company(slug=f"telegram-company-{suffix}", name="Example & Company")
    db_session.add(company)
    db_session.flush()
    original_query = telegram._candidate_query
    monkeypatch.setattr(
        telegram,
        "_candidate_query",
        lambda: original_query().where(models.Opportunity.company_id == company.id),
    )
    return company


def _opportunity(
    db_session: Session,
    company: models.Company,
    *,
    name: str = "Internship",
    category: str = "internship",
    age: int = 1,
    **overrides,
) -> models.Opportunity:
    seen_at = datetime.now(timezone.utc) - timedelta(days=age)
    values = {
        "slug": f"telegram-{uuid.uuid4().hex}",
        "company_id": company.id,
        "title": name,
        "category": category,
        "country": "IN",
        "is_remote": False,
        "location": "Bangalore, Mumbai, Pune",
        "apply_url": "https://example.com/apply",
        "first_seen_at": seen_at,
        "posted_at": seen_at,
        "last_seen_at": seen_at,
    }
    values.update(overrides)
    opportunity = models.Opportunity(**values)
    db_session.add(opportunity)
    db_session.flush()
    return opportunity


def _posts(session: Session) -> list[models.TelegramPost]:
    return list(session.scalars(select(models.TelegramPost)).all())


def test_internships_paid_first_then_newest(db_session: Session, company):
    unknown = _opportunity(db_session, company, age=1)
    older_paid = _opportunity(db_session, company, age=3, meta={"compensation": {"paid": True}})
    newer_paid = _opportunity(
        db_session,
        company,
        age=2,
        meta={"compensation": {"min": 10000, "max": 10000, "currency": "INR", "period": "month"}},
    )
    assert [row.id for row in telegram.select_candidates(db_session)] == [
        newer_paid.id,
        older_paid.id,
        unknown.id,
    ]


def test_internships_stating_an_amount_come_before_paid_without_one(db_session: Session, company):
    newer_paid = _opportunity(db_session, company, age=1, meta={"compensation": {"paid": True}})
    older_amount = _opportunity(
        db_session,
        company,
        age=3,
        meta={"compensation": {"min": 10000, "max": 10000, "currency": "INR", "period": "month"}},
    )
    assert [row.id for row in telegram.select_candidates(db_session)] == [
        older_amount.id,
        newer_paid.id,
    ]


def test_competitions_prize_then_deadline_nulls_last(db_session: Session, company):
    now = datetime.now(timezone.utc)
    unknown = _opportunity(
        db_session, company, category="competition", deadline=now + timedelta(days=1)
    )
    smaller = _opportunity(
        db_session,
        company,
        category="hackathon",
        deadline=now + timedelta(days=1),
        meta={"prize_inr": 10000},
    )
    later = _opportunity(
        db_session,
        company,
        category="competition",
        deadline=now + timedelta(days=5),
        meta={"prize_inr": 50000},
    )
    sooner = _opportunity(
        db_session,
        company,
        category="hackathon",
        deadline=now + timedelta(days=2),
        meta={"prize_inr": 50000},
    )
    assert [row.id for row in telegram.select_candidates(db_session)] == [
        sooner.id,
        later.id,
        smaller.id,
    ]
    db_session.delete(smaller)
    db_session.flush()
    assert telegram.select_candidates(db_session)[-1].id == unknown.id


def test_excludes_ineligible_and_old_listings(db_session: Session, company):
    now = datetime.now(timezone.utc)
    for overrides in (
        {"closed_at": now},
        {"status": "inactive"},
        {"deadline": now - timedelta(hours=1)},
        {"is_hidden": True},
        {"country": "US", "is_remote": True},
        {"country": None, "is_remote": False},
        {"meta": {"compensation": {"unpaid": True}}},
        {"meta": {"eligible_experienced_only": True}},
        {"meta": {"eligibility": ["School Students"]}},
        {"category": "job"},
        {"category": "hackathon", "deadline": None},
        {"age": 15},
    ):
        _opportunity(db_session, company, **overrides)
    posted = _opportunity(db_session, company)
    db_session.add(models.TelegramPost(opportunity_id=posted.id, message_id=42))
    db_session.flush()
    domestic = _opportunity(db_session, company, age=13)
    remote = _opportunity(db_session, company, country=None, is_remote=True)
    blank_remote = _opportunity(db_session, company, country="", is_remote=True)
    assert {row.id for row in telegram.select_candidates(db_session)} == {
        domestic.id,
        remote.id,
        blank_remote.id,
    }


def test_category_limits(db_session: Session, company):
    for _ in range(7):
        _opportunity(db_session, company)
    for _ in range(5):
        _opportunity(
            db_session,
            company,
            category="hackathon",
            deadline=datetime.now(timezone.utc) + timedelta(days=1),
        )
    candidates = telegram.select_candidates(db_session)
    assert sum(row.category == "internship" for row in candidates) == 5
    assert sum(row.category == "hackathon" for row in candidates) == 3


def test_message_escapes_values_and_tags_links(db_session: Session, company):
    company.name = "Company & <Team>"
    opportunity = _opportunity(
        db_session,
        company,
        name="Build <apps> & tools",
        location="<Delhi> & NCR; Pune",
        deadline=datetime.now(timezone.utc) + timedelta(days=1),
        meta={"compensation": {"paid": True}},
    )
    message, included = telegram.build_message([opportunity])
    assert included == [opportunity]
    assert "Today on Aspirova" in message
    assert "Build &lt;apps&gt; &amp; tools" in message
    assert "Company &amp; &lt;Team&gt;" in message
    assert "&lt;Delhi&gt; &amp; NCR +1 more" in message
    assert "Paid" in message
    assert "Apply by " in message
    assert (
        f"https://www.aspirova.org/opportunity/{opportunity.slug}"
        "?utm_source=telegram&amp;utm_medium=channel"
    ) in message


def test_length_limit_drops_whole_trailing_items(db_session: Session, company):
    candidates = [_opportunity(db_session, company, name="😀 & long title " * 25) for _ in range(8)]
    message, included = telegram.build_message(candidates)
    assert 0 < len(included) < len(candidates)
    assert len(message.encode("utf-16-le")) // 2 < 4096
    assert message.count("</a>") == len(included)
    for row in included:
        assert row.slug in message
    assert candidates[len(included)].slug not in message


@pytest.mark.parametrize(
    ("pay", "expected"),
    [
        ({"min": 10000, "max": 10000, "currency": "INR", "period": "month"}, "₹10,000/month"),
        ({"min": 600000, "max": 600000, "currency": "INR", "period": "year"}, "₹6 LPA"),
        ({"min": 130000, "max": 130000, "currency": "USD", "period": "year"}, "$130K/year"),
        ({"paid": True}, "Paid"),
        ({"unpaid": True}, None),
    ],
)
def test_pay_format(pay, expected):
    assert telegram.format_pay({"compensation": pay}) == expected


def test_prize_text_escaped(db_session: Session, company):
    opportunity = _opportunity(
        db_session, company, category="hackathon", meta={"prize_text": "₹1,00,000 & <prizes>"}
    )
    message, _ = telegram.build_message([opportunity])
    assert "₹1,00,000 &amp; &lt;prizes&gt;" in message


def test_dry_run_sends_and_records_nothing(db_session: Session, company, caplog):
    _opportunity(db_session, company)
    before = len(_posts(db_session))
    calls = []
    with caplog.at_level(logging.INFO):
        result = telegram.post_telegram(db_session, sender=lambda message: calls.append(message))
    assert result.exit_code == 0
    assert not result.sent
    assert result.items == 1
    assert not calls
    assert len(_posts(db_session)) == before
    assert "Today on Aspirova" in caplog.text


def test_success_records_message_id_and_only_one_post_a_day(db_session: Session, company):
    opportunity = _opportunity(db_session, company)
    calls = []

    def send(message: str) -> int:
        calls.append(message)
        return 1234567890123

    result = telegram.post_telegram(db_session, apply=True, sender=send)
    assert result.exit_code == 0
    assert result.sent
    row = db_session.scalar(
        select(models.TelegramPost).where(models.TelegramPost.opportunity_id == opportunity.id)
    )
    assert row.message_id == 1234567890123
    _opportunity(db_session, company)
    telegram.post_telegram(db_session, apply=True, sender=send)
    assert len(calls) == 1


def test_failed_send_records_nothing(db_session: Session, company, caplog):
    opportunity = _opportunity(db_session, company)
    token = "private-bot-token"

    def fail(message: str) -> int:
        raise httpx.ConnectError(f"https://api.telegram.org/bot{token}/sendMessage")

    result = telegram.post_telegram(db_session, apply=True, sender=fail)
    assert result.exit_code == 1
    assert not result.sent
    assert (
        db_session.scalar(
            select(models.TelegramPost).where(models.TelegramPost.opportunity_id == opportunity.id)
        )
        is None
    )
    assert token not in caplog.text


def test_no_candidates_does_not_send(db_session: Session, company):
    calls = []
    result = telegram.post_telegram(
        db_session, apply=True, sender=lambda message: calls.append(message)
    )
    assert result.exit_code == 0
    assert result.items == 0
    assert not calls


@pytest.mark.parametrize("network_failure", [False, True])
def test_http_errors_never_expose_token(network_failure, caplog):
    token = "private-bot-token"

    def respond(request: httpx.Request) -> httpx.Response:
        if network_failure:
            raise httpx.ConnectError(str(request.url), request=request)
        return httpx.Response(403, json={"ok": False, "description": f"Forbidden {token}"})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with caplog.at_level(logging.DEBUG):
            with pytest.raises(telegram.TelegramSendError) as error:
                telegram._http_sender(client, token, "@channel")("Example")
    assert token not in str(error.value)
    assert token not in caplog.text
    if not network_failure:
        assert "403" in caplog.text
        assert "Forbidden" in caplog.text


def test_http_payload_and_message_id():
    payloads = []

    def respond(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 81}})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        assert telegram._http_sender(client, "test-token", "@channel")("Hello") == 81
    assert payloads == [
        {
            "chat_id": "@channel",
            "text": "Hello",
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
    ]


@pytest.mark.parametrize("arguments", [[], ["--dry-run"]])
def test_cli_defaults_to_dry_run(monkeypatch, arguments):
    monkeypatch.setattr("sys.argv", ["post_telegram", *arguments])
    monkeypatch.setattr(telegram, "get_settings", lambda: SimpleNamespace())
    engine = object()
    session = object()
    monkeypatch.setattr(telegram, "make_engine", lambda: engine)
    monkeypatch.setattr(telegram, "Session", lambda _: nullcontext(session))
    calls = []

    def preview(db, *, apply=False, sender=None):
        calls.append((db, apply, sender))
        return telegram.TelegramResult()

    monkeypatch.setattr(telegram, "post_telegram", preview)
    assert telegram.main() == 0
    assert calls == [(session, False, None)]


@pytest.mark.parametrize(("token", "channel"), [("", "@channel"), ("test-token", "")])
def test_apply_requires_credentials_before_selection(monkeypatch, caplog, token, channel):
    monkeypatch.setattr("sys.argv", ["post_telegram", "--apply"])
    monkeypatch.setattr(
        telegram,
        "get_settings",
        lambda: SimpleNamespace(telegram_bot_token=token, telegram_channel_id=channel),
    )

    def unexpected_engine():
        pytest.fail("Missing credentials must fail before accessing the database")

    monkeypatch.setattr(telegram, "make_engine", unexpected_engine)
    assert telegram.main() == 1
    assert "requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHANNEL_ID" in caplog.text
