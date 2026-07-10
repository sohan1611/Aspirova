from core import models
from scripts.backfill_domains import _is_confident_match


def _company(name: str) -> models.Company:
    return models.Company(slug="matcher-test-company", name=name)


def test_confident_match_accepts_trailing_legal_suffix() -> None:
    assert _is_confident_match(_company("Acme Solutions Ltd"), "Acme Solutions")


def test_confident_match_strips_repeated_comparison_only_suffixes() -> None:
    assert _is_confident_match(
        _company("Acme Solutions Holdings Group"),
        "Acme Solutions Group Holdings",
    )


def test_confident_match_rejects_different_name_with_shared_first_token() -> None:
    assert not _is_confident_match(
        _company("Acme Solutions Ltd"),
        "Acme Industries",
    )
