"""Unit coverage for HTML-to-text structure preservation without network access."""

import pytest

from crawlers.common import extract_text


@pytest.fixture
def html_samples() -> dict[str, str]:
    return {
        "list": (
            "<ul><li>First requirement</li><li>Second requirement</li>"
            "<li>Third requirement</li></ul>"
        ),
        "paragraphs": "<p>First paragraph.</p><p>Second paragraph.</p>",
        "line_break": "<p>Line one<br>Line two</p>",
        "inline": (
            '<p>A sentence with an <a href="https://example.test">inline link</a> '
            "and <strong>bold text</strong>.</p>"
        ),
        "double_encoded": "&lt;p&gt;A &amp;amp; B&lt;/p&gt;",
        "plain": "Already plain text\nwith its original line break.",
        "extra_newlines": "<p>First</p><p></p><p></p><p>Last</p>",
        "trailing_space": "<p>First line  </p><div>Second line\t</div>",
    }


def test_extract_text_formats_each_list_item_as_a_bullet(html_samples: dict[str, str]) -> None:
    assert extract_text(html_samples["list"]) == (
        "- First requirement\n- Second requirement\n- Third requirement"
    )


def test_extract_text_keeps_sibling_list_items_on_consecutive_lines() -> None:
    raw_html = (
        "<ul><li><div>First requirement</div></li>" "<li><div>Second requirement</div></li></ul>"
    )

    assert extract_text(raw_html) == "- First requirement\n- Second requirement"


def test_extract_text_preserves_paragraph_boundaries(html_samples: dict[str, str]) -> None:
    assert extract_text(html_samples["paragraphs"]) == "First paragraph.\nSecond paragraph."


def test_extract_text_converts_br_to_a_newline(html_samples: dict[str, str]) -> None:
    assert extract_text(html_samples["line_break"]) == "Line one\nLine two"


def test_extract_text_keeps_inline_elements_on_one_line(html_samples: dict[str, str]) -> None:
    assert extract_text(html_samples["inline"]) == "A sentence with an inline link and bold text."


def test_extract_text_unescapes_double_encoded_html(html_samples: dict[str, str]) -> None:
    assert extract_text(html_samples["double_encoded"]) == "A & B"


def test_extract_text_keeps_plain_text_structure(html_samples: dict[str, str]) -> None:
    assert extract_text(html_samples["plain"]) == html_samples["plain"]


def test_extract_text_preserves_existing_empty_input_behavior() -> None:
    assert extract_text(None) == ""
    assert extract_text("") == ""


def test_extract_text_collapses_extra_blank_lines_and_trailing_space(
    html_samples: dict[str, str],
) -> None:
    assert extract_text(html_samples["extra_newlines"]) == "First\n\nLast"
    assert extract_text(html_samples["trailing_space"]) == "First line\nSecond line"
