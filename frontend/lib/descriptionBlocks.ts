export type DescriptionBlock =
  | { type: "heading"; text: string }
  | { type: "list"; items: string[] }
  | { type: "paragraph"; text: string };

const TITLE_HEADING_MAX_LENGTH = 60;
const COLON_HEADING_MAX_LENGTH = 80;
const LIST_MARKER_PATTERN =
  /^\s*(?:(?:[-*]|\u2022|\u00b7|\u2013|\u2014)|(?:\d+[.)]|\(\d+\)))\s+(.+?)\s*$/;
const TERMINAL_SENTENCE_PUNCTUATION = /[.!?]$/;
const COMMON_HEADING_PATTERN =
  /^(?:about us|about the role|benefits|eligibility|job description|key responsibilities|minimum qualifications|preferred qualifications|qualifications|requirements|responsibilities|role overview|skills|what you will do|what you'll do|who you are)$/i;
const SMALL_HEADING_WORDS = new Set([
  "a",
  "an",
  "and",
  "are",
  "as",
  "at",
  "do",
  "for",
  "from",
  "in",
  "of",
  "on",
  "or",
  "the",
  "to",
  "us",
  "with",
  "you",
  "you'll",
  "your",
]);

/**
 * Deterministically exposes structure already present in employer-written text.
 *
 * Examples:
 * parseDescriptionBlocks("Responsibilities:\n- Build APIs\n- Ship features\n\nWe are hiring.")
 *   => heading("Responsibilities:"), list(2), paragraph("We are hiring.")
 * parseDescriptionBlocks("Requirements:\n- Build APIs\n\n- Ship features")
 *   => heading("Requirements:"), list(2)
 * parseDescriptionBlocks("A single flowing paragraph with a dash - inside it and no structure at all.")
 *   => paragraph(...)
 * parseDescriptionBlocks("WHAT YOU WILL DO\n1. Design systems\n2) Write tests\n\nAbout us\nWe are a team.")
 *   => heading("WHAT YOU WILL DO"), list(2), heading("About us"), paragraph("We are a team.")
 */
export function parseDescriptionBlocks(raw: string): DescriptionBlock[] {
  const lines = normalizeLines(raw);
  const blocks: DescriptionBlock[] = [];
  let paragraphLines: string[] = [];

  function flushParagraph() {
    const text = paragraphLines.join("\n").trim();
    if (text) {
      blocks.push({ type: "paragraph", text });
    }
    paragraphLines = [];
  }

  for (let index = 0; index < lines.length; ) {
    const line = lines[index];
    const trimmedLine = line.trim();

    if (!trimmedLine) {
      flushParagraph();
      index += 1;
      continue;
    }

    const listItems: string[] = [];
    let scanIndex = index;
    while (scanIndex < lines.length) {
      const item = getListItem(lines[scanIndex]);
      if (item !== null) {
        listItems.push(item);
        scanIndex += 1;
        continue;
      }

      if (!lines[scanIndex].trim()) {
        scanIndex += 1;
        continue;
      }

      break;
    }

    if (listItems.length >= 2) {
      flushParagraph();
      blocks.push({ type: "list", items: listItems });
      index = scanIndex;
      continue;
    }

    if (isHeadingLine(trimmedLine)) {
      flushParagraph();
      blocks.push({ type: "heading", text: trimmedLine });
      index += 1;
      continue;
    }

    paragraphLines.push(trimmedLine);
    index += 1;
  }

  flushParagraph();
  return blocks;
}

function normalizeLines(raw: string): string[] {
  const lines = raw
    .replace(/\r\n?/g, "\n")
    .split("\n")
    .map((line) => line.replace(/[ \t]+$/g, ""));
  const collapsed: string[] = [];
  let blankRun = 0;

  for (const line of lines) {
    if (line.trim()) {
      blankRun = 0;
      collapsed.push(line);
      continue;
    }

    blankRun += 1;
    if (blankRun <= 2) {
      collapsed.push("");
    }
  }

  return collapsed;
}

function getListItem(line: string): string | null {
  const match = line.match(LIST_MARKER_PATTERN);
  const item = match?.[1]?.trim();
  return item || null;
}

function isHeadingLine(line: string): boolean {
  const text = line.trim();
  if (!text || !/[A-Za-z]/.test(text)) {
    return false;
  }

  if (text.length <= COLON_HEADING_MAX_LENGTH && text.endsWith(":")) {
    return true;
  }

  if (
    text.length > TITLE_HEADING_MAX_LENGTH ||
    TERMINAL_SENTENCE_PUNCTUATION.test(text)
  ) {
    return false;
  }

  return (
    COMMON_HEADING_PATTERN.test(text) ||
    isAllCapsHeading(text) ||
    isTitleCaseHeading(text)
  );
}

function isAllCapsHeading(text: string): boolean {
  const letters = text.match(/[A-Za-z]/g) ?? [];
  return letters.length >= 3 && letters.every((letter) => letter === letter.toUpperCase());
}

function isTitleCaseHeading(text: string): boolean {
  const words = text.match(/[A-Za-z][A-Za-z0-9'./+#-]*/g) ?? [];
  if (words.length === 0 || words.length > 9) {
    return false;
  }

  let significantWords = 0;
  for (const word of words) {
    const lowerWord = word.toLowerCase();
    if (SMALL_HEADING_WORDS.has(lowerWord)) {
      continue;
    }

    significantWords += 1;
    if (!/^[A-Z]/.test(word)) {
      return false;
    }
  }

  return significantWords > 0;
}
