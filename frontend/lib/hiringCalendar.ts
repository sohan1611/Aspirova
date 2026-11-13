export type CalendarView = "year" | "month" | "days" | "custom";

export interface CalendarQuery {
  view: CalendarView;
  from: string;
  to: string;
  days: 7 | 30 | 90;
  category: string[];
  status: string;
  q: string;
}

export interface CalendarItem {
  id: string;
  programme: {
    slug: string;
    name: string;
    organiser: string;
    category: string;
    category_label: string;
    url: string;
    eligibility: string | null;
    country: string | null;
    geography: string | null;
  };
  edition: {
    year: number;
    status: string;
    status_label: string;
    opens_at: string | null;
    closes_at: string | null;
    opens_precision: "day" | "month" | null;
    closes_precision: "day" | "month" | null;
    opens_until: string | null;
    closes_from: string | null;
    basis: "official" | "tentative";
  };
  metadata: {
    deadline_rolling: boolean;
    source_cycle_year: number | null;
    row_id: string | null;
    prep_tip: string | null;
    hiring_mode: string | null;
    career_linkage: string | null;
    duration_start: string | null;
    verification_note: string | null;
    confidence: string | null;
    opening_text: string | null;
    deadline_text: string | null;
  };
  verified_at: string | null;
  is_open_now: boolean;
}

export interface CalendarResponse {
  from: string;
  to: string;
  items: CalendarItem[];
  rolling: CalendarItem[];
  months: { month: string; count: number }[];
}

export const CALENDAR_CATEGORIES = [
  ["research_internship", "Research"],
  ["international_research", "International research"],
  ["government_internship", "Government"],
  ["early_career", "Early-career hiring"],
  ["recurring_competition", "Competitions"],
] as const;

const STATUSES = ["open", "announced", "expected", "closed"];

export function validDay(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value &&
    Number(value.slice(0, 4)) >= 1900 && Number(value.slice(0, 4)) <= 9997;
}

export function todayIST(now = new Date()): string {
  return new Date(now.getTime() + 330 * 60_000).toISOString().slice(0, 10);
}

export function currentCycleYear(today: string): number {
  return Math.max(2027, Number(today.slice(0, 4)));
}

export function addDays(day: string, amount: number): string {
  const value = new Date(`${day}T00:00:00Z`);
  value.setUTCDate(value.getUTCDate() + amount);
  return value.toISOString().slice(0, 10);
}

export function monthRange(month: string): { from: string; to: string } {
  const from = `${month}-01`;
  const value = new Date(`${from}T00:00:00Z`);
  value.setUTCMonth(value.getUTCMonth() + 1, 0);
  return { from, to: value.toISOString().slice(0, 10) };
}

export function shiftMonth(month: string, amount: number): string {
  const value = new Date(`${month}-01T00:00:00Z`);
  value.setUTCMonth(value.getUTCMonth() + amount);
  return value.toISOString().slice(0, 7);
}

export function rangeError(from: string, to: string): string | null {
  if (!validDay(from) || !validDay(to)) return "Choose two valid dates.";
  if (from > to) return "The start must be on or before the end.";
  const year = Number(from.slice(0, 4)) + 2;
  const month = from.slice(5, 7);
  const lastDay = Number(monthRange(`${year}-${month}`).to.slice(8, 10));
  const limit = `${year}-${month}-${String(Math.min(Number(from.slice(8, 10)), lastDay)).padStart(2, "0")}`;
  return to > limit ? "Choose a range of at most two years." : null;
}

export function presetRange(view: CalendarView, today: string, options: {
  year?: number; month?: string; days?: 7 | 30 | 90;
} = {}): { from: string; to: string } {
  if (view === "year") {
    const year = options.year ?? currentCycleYear(today);
    return { from: `${year}-01-01`, to: `${year}-12-31` };
  }
  if (view === "month") return monthRange(options.month ?? today.slice(0, 7));
  return { from: today, to: addDays(today, (options.days ?? 30) - 1) };
}

export function parseCalendarParams(params: URLSearchParams, today: string): CalendarQuery {
  const rawView = params.get("view");
  const view: CalendarView = rawView === "month" || rawView === "days" || rawView === "custom" ? rawView : "year";
  const days = params.get("days") === "7" ? 7 : params.get("days") === "90" ? 90 : 30;
  const rawYear = Number(params.get("year"));
  const year = Number.isInteger(rawYear) && rawYear >= 1900 && rawYear <= 9997 ? rawYear : currentCycleYear(today);
  const month = params.get("month") ?? today.slice(0, 7);
  const defaults = presetRange(view, today, { year, month: validDay(`${month}-01`) ? month : today.slice(0, 7), days });
  const from = params.get("from") ?? defaults.from;
  const to = params.get("to") ?? defaults.to;
  const valid = !rangeError(from, to);
  // Fixed-size views have a canonical shape, even for hand-edited URLs.
  let range = valid ? { from, to } : defaults;
  if (view === "year") range = presetRange(view, today, { year: Number(range.from.slice(0, 4)) });
  if (view === "month") range = monthRange(range.from.slice(0, 7));
  const categories = new Set<string>(CALENDAR_CATEGORIES.map(([key]) => key));
  return {
    view, ...range, days,
    category: [...new Set(params.getAll("category").filter((key) => categories.has(key)))],
    status: STATUSES.includes(params.get("status") ?? "") ? params.get("status")! : "",
    q: (params.get("q") ?? "").trim().slice(0, 200),
  };
}

export function calendarParams(query: CalendarQuery, api = false): URLSearchParams {
  const params = new URLSearchParams({ from: query.from, to: query.to });
  if (!api) {
    params.set("view", query.view);
    params.set("days", String(query.days));
  }
  for (const category of query.category) params.append("category", category);
  if (query.status) params.set("status", query.status);
  if (query.q) params.set("q", query.q);
  return params;
}

export function calendarDays(month: string): (string | null)[] {
  const { from, to } = monthRange(month);
  const offset = (new Date(`${from}T00:00:00Z`).getUTCDay() + 6) % 7;
  const cells: (string | null)[] = Array.from({ length: offset }, () => null);
  for (let day = from; day <= to; day = addDays(day, 1)) cells.push(day);
  while (cells.length % 7) cells.push(null);
  return cells;
}

export function itemDate(value: string): string {
  return todayIST(new Date(value));
}

export function openingInMonth(item: CalendarItem, month: string): boolean {
  if (!item.edition.opens_at) return false;
  const first = itemDate(item.edition.opens_at).slice(0, 7);
  const last = item.edition.opens_precision === "month" && item.edition.opens_until
    ? itemDate(item.edition.opens_until).slice(0, 7) : first;
  return first <= month && month <= last;
}

export function dateLabel(value: string, precision: "day" | "month" = "day"): string {
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Kolkata", month: "short", year: "numeric",
    ...(precision === "day" ? { day: "numeric" } : {}),
  }).format(new Date(value));
}

export function programmeSummaryName(programme: Pick<CalendarItem["programme"], "name" | "organiser">): string {
  const name = programme.name.trim();
  const organiser = programme.organiser.trim();
  if (!organiser) return name;
  const aliases = [
    organiser,
    organiser.replace(/\([^)]*\)|\[[^\]]*\]/g, "").trim(),
    ...Array.from(organiser.matchAll(/[([]([a-z][a-z0-9&.-]{1,11})[)\]]/gi), (match) => match[1]),
  ];
  const normalizedName = ` ${name.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim()} `;
  const includesOrganiser = aliases.some((alias) => {
    const normalizedAlias = alias.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
    return normalizedAlias.length > 0 && normalizedName.includes(` ${normalizedAlias} `);
  });
  return includesOrganiser ? name : `${organiser} · ${name}`;
}

export function windowText(item: CalendarItem): string {
  const edition = item.edition;
  function boundary(value: string | null, other: string | null, precision: "day" | "month" | null): string | null {
    if (!value || !precision) return null;
    const text = dateLabel(value, precision);
    if (precision === "month" && other && itemDate(value).slice(0, 7) !== itemDate(other).slice(0, 7)) {
      return `${dateLabel(other, precision)} – ${text}`;
    }
    return text;
  }
  const opening = boundary(edition.opens_at, null, edition.opens_precision);
  const openingEnd = edition.opens_until && edition.opens_at &&
    itemDate(edition.opens_until).slice(0, 7) !== itemDate(edition.opens_at).slice(0, 7)
    ? ` – ${dateLabel(edition.opens_until, "month")}` : "";
  const deadline = boundary(edition.closes_at, edition.closes_from, edition.closes_precision);
  const deadlineText = item.metadata?.deadline_rolling
    ? "Deadline: rolling — apply early" : deadline && `Deadline ${deadline}`;
  return [opening && `Opens ${opening}${openingEnd}`, deadlineText].filter(Boolean).join(" · ") ||
    "Timing depends on the individual vacancy, institution or lab.";
}

export async function fetchCalendar(query: CalendarQuery, options?: RequestInit): Promise<CalendarResponse> {
  const base = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  const response = await fetch(`${base}/calendar?${calendarParams(query, true)}`, options);
  if (!response.ok) throw new Error("The calendar could not be loaded.");
  return response.json();
}
