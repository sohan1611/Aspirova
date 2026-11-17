import pytest

from core.entity_search import acronyms, match_company, match_programme, normalize


@pytest.mark.parametrize(
    ("query", "name", "expected"),
    [
        ("gsoc", "Google Summer of Code", "acronym"),
        ("rbi", "Reserve Bank of India", "acronym"),
        ("srfp", "Summer Research Fellowship (SRFP)", "acronym"),
        ("srfp", "Summer Fellowship (srfp)", "acronym"),
        ("rbi", "RBI Summer Placement", "acronym"),
        ("sum cod", "Google Summer of Code", "name"),
        ("research summer", "Summer Research Fellowship", "name"),
        ("rbi", "Reflect Orbital", None),
        ("rbi", "Loftorbital", None),
        ("%", "Google Summer of Code", None),
    ],
)
def test_programme_match(query, name, expected):
    assert match_programme(query, slug="unrelated", name=name) == expected


def test_programme_slug_organiser_company_and_priority():
    assert match_programme("GSoC", slug="gsoc", name="Google Summer of Code") == "slug"
    assert match_programme("summer-code", slug="summer-code", name="Other") == "slug"
    assert match_programme("summer code", slug="summer-code", name="Other") == "slug"
    assert (
        match_programme(
            "reserve bank", slug="other", name="Fellowship", organiser="Reserve Bank of India"
        )
        == "organiser"
    )
    assert (
        match_programme("micro", slug="other", name="Fellowship", company="Microsoft") == "company"
    )
    assert (
        match_programme("fellow", slug="other", name="Fellowship", organiser="Fellowship") == "name"
    )


@pytest.mark.parametrize(
    ("query", "name", "expected"),
    [
        ("microsoft", "Microsoft", "exact"),
        ("microsoft", "Microsoft Research", "prefix"),
        ("google", "Google India", "prefix"),
        ("rbi", "Reserve Bank of India", "acronym"),
        ("rbi", "Reflect Orbital", None),
        ("rbi", "Loftorbital", None),
        ("orb", "Reflect Orbital", None),
        ("orbit", "Reflect Orbital", "substring"),
        ("", "Google", None),
    ],
)
def test_company_match(query, name, expected):
    assert match_company(query, name) == expected


def test_normalization_and_matching_accents_and_punctuation():
    assert normalize("  Été & Co—Op (R&D)-2027! ") == "ete co op r d 2027"
    assert normalize("Straße") == "strasse"
    assert match_company("ete co", "Été & Co") == "exact"
    assert match_programme("ete dev", slug="other", name="Été—Developer (Programme)") == "name"


def test_single_character_initials_and_tokens_are_not_acronyms():
    for name in ("Microsoft", "Meta", "MICROSOFT", "RBI Officers Grade B", "Fellowship (B)"):
        assert all(len(acronym) >= 2 for acronym in acronyms(name))
    assert "b" not in acronyms("RBI Officers Grade B")
    assert match_company("m", "Microsoft") == "prefix"
    assert match_company("m", "Meta") == "prefix"
    assert match_programme("b", slug="other", name="RBI Officers Grade B") == "name"
