"""Deterministic, extractive summaries for opportunity descriptions.

The live catalogue already has usable `description_raw` for all but 45 active
rows, with average text around 5,056 characters and only 38 active rows still
containing HTML. That makes a conservative extracted lead useful while model
summary generation remains dormant: absence is acceptable, invention is not.
"""

import re

from bs4 import BeautifulSoup

from core.textclean import fix_multiline_text, fix_text

MIN_SUMMARY_CHARS = 40
TARGET_SUMMARY_CHARS = 120
MAX_SUMMARY_CHARS = 220
SUMMARY_SENTENCE_LIMIT = 2
ELLIPSIS = "\u2026"

HTML_TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")
BULLET_PREFIX_RE = re.compile(r"^\s*(?:[-*]|\d+[.)]|\u2022|\u00b7)\s+")
EMAIL_ONLY_RE = re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.IGNORECASE)
URL_ONLY_RE = re.compile(r"^(?:https?://|www\.)\S+$", re.IGNORECASE)
TERMINAL_PUNCTUATION_RE = re.compile(r"[.!?][\"')\]]*$")
SENTENCE_BOUNDARY_RE = re.compile(r"[.!?][\"')\]]*(?=\s|$)")
WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9'/-]*")
TITLE_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*")
SECTION_LABEL_RE = re.compile(
    r"^(?:"
    r"about\s+(?:the|this)\s+role|"
    r"job description|"
    r"role description|"
    r"position summary|"
    r"job summary|"
    r"the role|"
    r"overview|"
    r"summary|"
    r"description|"
    r"responsibilities"
    r")\s*[:\-\u2013\u2014]\s*",
    re.IGNORECASE,
)

BOILERPLATE_START_RE = re.compile(
    r"^(?:"
    r"about\s+(?:us|the company)\b|"
    r"who we are\b|"
    r"our mission\b|"
    r"our story\b|"
    r"our values\b|"
    r"equal opportunity\b|"
    r"we are an equal\b|"
    r"benefits\b|"
    r"perks\b|"
    r"compensation\b|"
    r"what we offer\b|"
    r"why join\b|"
    r"diversity\b|"
    r"eeo\b|"
    r"applicants\b"
    r")",
    re.IGNORECASE,
)

FIRST_SENTENCE_BOILERPLATE_RE = re.compile(
    r"(?:"
    r"compensation package|"
    r"pay for performance|"
    r"benefits package|"
    r"equal opportunity employer|"
    r"we offer a competitive|"
    r"salary range|"
    r"perks and benefits|"
    r"reasonable accommodation"
    r")",
    re.IGNORECASE,
)

ROLE_PROSE_MARKERS = (
    "you will",
    "you'll",
    "we are looking for",
    "we're looking for",
    "responsible for",
    "the role",
    "this role",
    "as a",
    "join us",
    "seeking",
    "the position",
    "your role",
)
AS_A_ROLE_MARKER_RE = re.compile(r"^as\s+a\b", re.IGNORECASE)

TITLE_TOKEN_STOPWORDS = {
    "a",
    "an",
    "and",
    "apac",
    "at",
    "bangalore",
    "emea",
    "for",
    "from",
    "global",
    "hybrid",
    "india",
    "junior",
    "lead",
    "onsite",
    "principal",
    "remote",
    "senior",
    "staff",
    "sweden",
    "the",
    "this",
    "to",
    "turkey",
    "with",
}

UNICODE_DASH_QUOTE_TRANSLATION = {
    0x00A0: " ",
    0x2010: "-",
    0x2011: "-",
    0x2012: "-",
    0x2013: "-",
    0x2014: "-",
    0x2015: "-",
    0x2212: "-",
    0x2018: "'",
    0x2019: "'",
    0x201A: "'",
    0x201B: "'",
    0x201C: '"',
    0x201D: '"',
    0x201E: '"',
    0x201F: '"',
}

HTML_TEXT_BLOCK_TAGS = (
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "li",
    "p",
)


def summarise_description(
    description: str | None,
    *,
    title: str | None = None,
) -> str | None:
    """Extract a concise lead from existing prose without generating new facts."""
    cleaned = _clean_description(description)
    if cleaned is None:
        return None

    title_key = _canonical_text(title)
    title_tokens = _significant_title_tokens(title)
    candidates = [
        block for block in _split_blocks(cleaned) if _is_usable_prose_block(block, title_key)
    ]
    if not candidates:
        return None

    for block in _ordered_candidates(candidates, title_tokens):
        summary = _summary_from_block(block)
        if summary is not None:
            return summary
    return None


def _clean_description(description: str | None) -> str | None:
    if description is None:
        return None

    text = _strip_html(description)
    cleaned = fix_multiline_text(text)
    if not cleaned:
        return None
    return cleaned.translate(UNICODE_DASH_QUOTE_TRANSLATION)


def _strip_html(text: str) -> str:
    if not HTML_TAG_RE.search(text):
        return text

    soup = BeautifulSoup(text, "html.parser")
    for tag in soup.find_all(("script", "style")):
        tag.decompose()
    for tag in soup.find_all("br"):
        tag.replace_with("\n")

    blocks = [
        " ".join(tag.get_text(" ", strip=True).split())
        for tag in soup.find_all(HTML_TEXT_BLOCK_TAGS)
    ]
    blocks = [block for block in blocks if block]
    if blocks:
        return "\n".join(blocks)
    return soup.get_text("\n")


def _split_blocks(text: str) -> list[str]:
    return [
        re.sub(r"[ \t]+", " ", block).strip() for block in re.split(r"\n+", text) if block.strip()
    ]


def _is_usable_prose_block(block: str, title_key: str | None) -> bool:
    if _is_heading(block):
        return False
    if BOILERPLATE_START_RE.search(block):
        return False
    if _first_sentence_matches(block, FIRST_SENTENCE_BOILERPLATE_RE):
        return False
    if _is_mostly_bullet_list(block):
        return False
    if URL_ONLY_RE.fullmatch(block) or EMAIL_ONLY_RE.fullmatch(block):
        return False
    if title_key is not None and _canonical_text(block) == title_key:
        return False
    return _has_enough_words(block)


def _is_heading(block: str) -> bool:
    return len(block) < 60 and TERMINAL_PUNCTUATION_RE.search(block) is None


def _is_mostly_bullet_list(block: str) -> bool:
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    if not lines:
        return False

    bullet_lines = sum(1 for line in lines if BULLET_PREFIX_RE.match(line))
    return bullet_lines / len(lines) >= 0.5


def _has_enough_words(block: str) -> bool:
    words = WORD_RE.findall(block)
    return len(words) >= 4


def _looks_like_role_prose(block: str) -> bool:
    return _first_sentence_has_role_marker(_first_sentence(block))


def _ordered_candidates(candidates: list[str], title_tokens: set[str]) -> list[str]:
    qualified = _qualified_candidates(candidates, title_tokens)
    ordered: list[str] = []
    used_indexes: set[int] = set()

    for index, block in enumerate(qualified):
        if _looks_like_role_prose(block):
            ordered.append(block)
            used_indexes.add(index)

    for index, block in enumerate(qualified):
        if index not in used_indexes and len(block) >= 80:
            ordered.append(block)
            used_indexes.add(index)

    for index, block in enumerate(qualified):
        if index not in used_indexes:
            ordered.append(block)

    return ordered


def _qualified_candidates(candidates: list[str], title_tokens: set[str]) -> list[str]:
    qualified: list[str] = []
    for block in candidates:
        block = _strip_section_label(block)
        if len(block) < MIN_SUMMARY_CHARS:
            continue
        # Employer boilerplate varies without bound; first-sentence role evidence
        # is the conservative gate that keeps wrong card summaries out.
        if _qualifies_as_role_summary(block, title_tokens):
            qualified.append(block)
    return qualified


def _qualifies_as_role_summary(block: str, title_tokens: set[str]) -> bool:
    """Require the block to name the job, not merely address a reader.

    A role marker alone is not enough, because employer boilerplate is written in
    the same second person. Measured over random production rows, "you'll",
    "you will" and "we're looking for" all appear in pure culture prose:

        "A career at Roblox means you'll be working to shape the future of
         human interaction..."                       (Senior Fullstack Engineer)
        "Working at Samsara means you'll help define the future of physical
         operations..."      (emitted verbatim on TWO different Samsara roles)
        "At Pinterest, AI isn't just a feature, ... we're looking for candidates
         who are excited to be a part of that."           (Sr. SWE, Backend)

    Every one of those omits the job title, and every correct summary in the same
    sample contained it. So the title token is the load-bearing signal and the
    marker is only a fallback for the rare title that yields no usable tokens -
    the identical-summary-on-two-cards failure is what a marker-only rule buys.
    """
    first_sentence = _first_sentence(block)
    if title_tokens:
        return _first_sentence_has_title_token(first_sentence, title_tokens)
    return _first_sentence_has_role_marker(first_sentence)


def _first_sentence_has_role_marker(first_sentence: str) -> bool:
    folded = first_sentence.casefold()
    if any(marker in folded for marker in ROLE_PROSE_MARKERS if marker != "as a"):
        return True
    return AS_A_ROLE_MARKER_RE.search(first_sentence) is not None


def _first_sentence_has_title_token(first_sentence: str, title_tokens: set[str]) -> bool:
    if not title_tokens:
        return False

    return any(
        re.search(rf"\b{re.escape(token)}\b", first_sentence, flags=re.IGNORECASE)
        for token in title_tokens
    )


def _summary_from_block(block: str) -> str | None:
    block = _strip_section_label(block)
    if len(block) < MIN_SUMMARY_CHARS:
        return None

    summary = _cap_summary(_lead_sentences(block))
    if len(summary) < MIN_SUMMARY_CHARS:
        return None
    return summary


def _strip_section_label(block: str) -> str:
    return SECTION_LABEL_RE.sub("", block, count=1).strip()


def _first_sentence_matches(block: str, pattern: re.Pattern[str]) -> bool:
    return pattern.search(_first_sentence(block)) is not None


def _first_sentence(block: str) -> str:
    sentences = _sentences(block)
    return sentences[0] if sentences else block


def _lead_sentences(block: str) -> str:
    # A sentence ending in a colon introduces a list that the summary will not
    # carry, so it reads as cut off: "We're looking for a strong engineer who can
    # build agentic products that scale. You will work with:" - observed verbatim
    # in production. Stop before it rather than trail a dangling lead-in.
    sentences = [sentence for sentence in _sentences(block) if not sentence.rstrip().endswith(":")]
    chosen: list[str] = []
    for sentence in sentences:
        chosen.append(sentence)
        summary = " ".join(chosen)
        if len(summary) >= TARGET_SUMMARY_CHARS or len(chosen) >= SUMMARY_SENTENCE_LIMIT:
            return summary
    return " ".join(chosen)


def _sentences(block: str) -> list[str]:
    return [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", block) if sentence.strip()]


def _cap_summary(summary: str) -> str:
    summary = re.sub(r"\s+", " ", summary).strip()
    if len(summary) <= MAX_SUMMARY_CHARS:
        return summary

    sentence_boundary = _last_sentence_boundary(summary)
    if sentence_boundary is not None:
        return summary[:sentence_boundary].strip()

    cut_at = summary.rfind(" ", 0, MAX_SUMMARY_CHARS)
    if cut_at < MIN_SUMMARY_CHARS:
        cut_at = MAX_SUMMARY_CHARS - len(ELLIPSIS)
    return summary[:cut_at].rstrip(" ,;:-") + ELLIPSIS


def _last_sentence_boundary(summary: str) -> int | None:
    boundary = None
    for match in SENTENCE_BOUNDARY_RE.finditer(summary):
        if match.end() <= MAX_SUMMARY_CHARS:
            boundary = match.end()
        else:
            break
    return boundary


def _canonical_text(value: str | None) -> str | None:
    normalized = fix_text(value)
    if not normalized:
        return None

    normalized = normalized.translate(UNICODE_DASH_QUOTE_TRANSLATION).casefold()
    key = re.sub(r"[^a-z0-9]+", " ", normalized).strip()
    return key or None


def _significant_title_tokens(title: str | None) -> set[str]:
    normalized = fix_text(title)
    if not normalized:
        return set()

    normalized = normalized.translate(UNICODE_DASH_QUOTE_TRANSLATION).casefold()
    return {
        token
        for token in TITLE_TOKEN_RE.findall(normalized)
        if len(token) >= 4 and token not in TITLE_TOKEN_STOPWORDS
    }
