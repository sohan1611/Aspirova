import type { ProgrammeListItem } from "@/lib/types";

export type ProgrammeWindow = {
  kind: "confirmed" | "typical";
  /** Calendar months, inclusive, numbered January = 1 through December = 12. */
  segments: [number, number][];
  label: string;
  status?: string;
};

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const MONTH_PATTERN = MONTHS.join("|").toLowerCase();
const OPENS_MONTH = new RegExp(`\\bopens?\\s+(?:in\\s+)?(${MONTH_PATTERN})\\b(?:\\s*(?:or|and|to|-)\\s*(${MONTH_PATTERN})\\b)?`);

function segments(start: number, end: number): [number, number][] {
  return start <= end ? [[start, end]] : [[start, 12], [1, end]];
}

function typical(start: number, end: number): ProgrammeWindow {
  return {
    kind: "typical",
    segments: segments(start, end),
    label: `Usually ${MONTHS[start - 1]}${start === end ? "" : ` to ${MONTHS[end - 1]}`}`,
  };
}

/** Uses only dates or explicit seasonal prose; never infers an application window from work dates. */
export function programmeWindow(programme: Pick<ProgrammeListItem, "current_edition" | "typical_window">, now: Date = new Date()): ProgrammeWindow | null {
  const edition = programme.current_edition;
  if (edition?.opens_at) {
    const opens = new Date(edition.opens_at);
    const closes = edition.closes_at ? new Date(edition.closes_at) : opens;
    if (!Number.isFinite(opens.getTime()) || !Number.isFinite(closes.getTime()) || closes < opens) return null;
    const start = opens.getUTCMonth() + 1;
    const end = closes.getUTCMonth() + 1;
    const date = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", timeZone: "UTC" }).format(opens);
    return {
      kind: "confirmed",
      segments: segments(start, end),
      label: edition.status === "open" ? "Open now" : edition.status === "announced" ? `${opens.getTime() < now.getTime() ? "Opened" : "Opens"} ${date}` : edition.status === "closed" ? "Closed" : edition.status.replace(/_/g, " "),
      status: edition.status,
    };
  }

  const text = programme.typical_window?.toLowerCase() ?? "";
  const explicit = OPENS_MONTH.exec(text);
  if (explicit) {
    const start = MONTHS.findIndex((month) => month.toLowerCase() === explicit[1]) + 1;
    const end = explicit[2] ? MONTHS.findIndex((month) => month.toLowerCase() === explicit[2]) + 1 : start;
    return typical(start, end);
  }
  if (/\bturn of the year\b/.test(text)) return typical(12, 1);
  if (/\b(?:early part of the year|earlier part of the year|early in the year)\b/.test(text)) return typical(1, 3);
  if (/\bin the winter\b/.test(text)) return typical(12, 2);
  if (/\blate in the year\b/.test(text)) return typical(10, 12);
  if (/\bin (?:the )?autumn\b/.test(text)) return typical(9, 11);
  if (/\bsecond half of the year\b/.test(text)) return typical(7, 12);
  if (/\bmiddle of the year\b/.test(text)) return typical(5, 7);
  return null;
}

/** Expected outputs are literal, so reviewers can compare them against the pure function. */
export const PROGRAMME_WINDOW_EXAMPLES: { typical_window: string; expected: ProgrammeWindow | null }[] = [
  { typical_window: "applications usually open in January or February", expected: { kind: "typical", segments: [[1, 2]], label: "Usually January to February" } },
  { typical_window: "applications usually open in the early part of the year for a summer internship", expected: { kind: "typical", segments: [[1, 3]], label: "Usually January to March" } },
  { typical_window: "applications usually open in the winter for a summer placement", expected: { kind: "typical", segments: [[12, 12], [1, 2]], label: "Usually December to February" } },
  { typical_window: "applications usually open around the turn of the year for a forum held in the autumn", expected: { kind: "typical", segments: [[12, 12], [1, 1]], label: "Usually December to January" } },
  { typical_window: "applications usually open late in the year for fellowships in the following calendar year", expected: { kind: "typical", segments: [[10, 12]], label: "Usually October to December" } },
  { typical_window: "applications usually open in autumn for the following year's internships", expected: { kind: "typical", segments: [[9, 11]], label: "Usually September to November" } },
  { typical_window: "registration and the qualification round usually fall in the second half of the year", expected: { kind: "typical", segments: [[7, 12]], label: "Usually July to December" } },
  { typical_window: "applications usually open in the middle of the year for a cohort starting later that year", expected: { kind: "typical", segments: [[5, 7]], label: "Usually May to July" } },
  { typical_window: "applications usually open before the May-July summer period", expected: null },
  { typical_window: "fellowship work takes place during the July-August summer period", expected: null },
  { typical_window: "registration opens in the autumn with rounds running into the following year", expected: { kind: "typical", segments: [[9, 11]], label: "Usually September to November" } },
  { typical_window: "openings are posted through the year, with many internships running over the summer", expected: null },
  { typical_window: "annual programme timeline varies by year", expected: null },
  { typical_window: "applications usually close early in the year for the summer programme", expected: { kind: "typical", segments: [[1, 3]], label: "Usually January to March" } },
];
