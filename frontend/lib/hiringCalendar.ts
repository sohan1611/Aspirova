export type CalendarView = "list" | "timeline" | "grid";
export type CalendarPeriod = "next12" | "next30" | "next90" | "month" | "custom" | `year-${number}`;

export interface CalendarQuery {
  view: CalendarView;
  period: CalendarPeriod;
  from: string;
  to: string;
  days: 7 | 30 | 90;
  category: string[];
  status: string;
  q: string;
  closingSoon: boolean;
  officialOnly: boolean;
  item: string;
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
    how_to_apply?: string | null;
    event_window?: string | null;
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
  ["open_source", "Open source"],
  ["government_exam", "Government exams & recruitment"],
] as const;

// Every calendar surface uses the same category colours, including unknown categories.
const CATEGORY_COLOURS: Record<string, string> = {
  research_internship: "#2563eb",
  international_research: "#7c3aed",
  government_internship: "#0f766e",
  early_career: "#c2410c",
  recurring_competition: "#be185d",
  open_source: "#4d7c0f",
  government_exam: "#4338ca",
};

export function categoryColour(category: string): string {
  return CATEGORY_COLOURS[category] ?? "#475569";
}

export function categoryLabel(category: string, fallback?: string | null): string {
  return CALENDAR_CATEGORIES.find(([key]) => key === category)?.[1] ??
    fallback?.replace(/_/g, " ") ?? category.replace(/[_-]/g, " ");
}

const STATUSES = ["open", "announced", "expected", "closed"];
const DAY_FORMAT = new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Kolkata", day: "numeric", month: "short", year: "numeric" });
const MONTH_FORMAT = new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Kolkata", month: "short", year: "numeric" });
const SHORT_DAY_FORMAT = new Intl.DateTimeFormat("en-GB", { timeZone: "UTC", day: "numeric", month: "short" });
const SHORT_MONTH_FORMAT = new Intl.DateTimeFormat("en-GB", { timeZone: "UTC", month: "short" });

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

export function addMonths(day: string, amount: number): string {
  const month = shiftMonth(day.slice(0, 7), amount);
  const last = Number(monthRange(month).to.slice(8));
  return `${month}-${String(Math.min(Number(day.slice(8)), last)).padStart(2, "0")}`;
}

export function clampRange(from: string, to: string): { from: string; to: string } {
  const limit = addMonths(from, 24);
  return { from, to: to > limit ? limit : to };
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

export function presetRange(view: "year" | "month" | "days" | "custom", today: string, options: {
  year?: number; month?: string; days?: 7 | 30 | 90;
} = {}): { from: string; to: string } {
  if (view === "year") {
    const year = options.year ?? currentCycleYear(today);
    return { from: `${year}-01-01`, to: `${year}-12-31` };
  }
  if (view === "month") return monthRange(options.month ?? today.slice(0, 7));
  return { from: today, to: addDays(today, (options.days ?? 30) - 1) };
}

export function periodRange(period: CalendarPeriod, today: string): { from: string; to: string } {
  if (period === "month") return monthRange(today.slice(0, 7));
  if (period.startsWith("year-")) return presetRange("year", today, { year: Number(period.slice(5)) });
  if (period === "next12") return { from: today, to: addDays(addMonths(today, 12), -1) };
  return { from: today, to: addDays(today, period === "next90" ? 89 : 29) };
}

export function periodLabel(query: CalendarQuery): string {
  if (query.period.startsWith("year-")) return `Year ${query.period.slice(5)}`;
  return {
    next12: "Next 12 months", next30: "Next 30 days", next90: "Next 90 days",
    month: "This month", custom: "Custom range"
  }[query.period as "next12" | "next30" | "next90" | "month" | "custom"];
}

export function stepPeriod(query: CalendarQuery, direction: number): CalendarQuery {
  if (query.period.startsWith("year-")) {
    const year = Math.max(1900, Math.min(9997, Number(query.from.slice(0, 4)) + direction));
    return { ...query, period: `year-${year}`, ...presetRange("year", query.from, { year }) };
  }
  if (query.period === "month") return { ...query, ...monthRange(shiftMonth(query.from.slice(0, 7), direction)) };
  const length = Math.round((Date.parse(query.to) - Date.parse(query.from)) / 86_400_000) + 1;
  const range = query.period === "next12"
    ? { from: addMonths(query.from, 12 * direction), to: addMonths(query.to, 12 * direction) }
    : { from: addDays(query.from, direction * length), to: addDays(query.to, direction * length) };
  return { ...query, ...clampRange(range.from, range.to) };
}

export function parseCalendarParams(params: URLSearchParams, today: string): CalendarQuery {
  const rawView = params.get("view");
  const view: CalendarView = rawView === "timeline" ? "timeline" : rawView === "grid" || rawView === "month" ? "grid" : "list";
  const days = params.get("days") === "7" ? 7 : params.get("days") === "90" ? 90 : 30;
  const rawYear = Number(params.get("year"));
  const year = Number.isInteger(rawYear) && rawYear >= 1900 && rawYear <= 9997 ? rawYear : currentCycleYear(today);
  const month = params.get("month") ?? today.slice(0, 7);
  const rawPeriod = params.get("period");
  let period: CalendarPeriod = "next12";
  if (rawPeriod === "next12" || rawPeriod === "next30" || rawPeriod === "next90" || rawPeriod === "month" || rawPeriod === "custom") period = rawPeriod;
  else if (/^year-\d{4}$/.test(rawPeriod ?? "") && validDay(`${rawPeriod!.slice(5)}-01-01`)) period = rawPeriod as CalendarPeriod;
  else if (rawView === "year") period = `year-${year}`;
  else if (rawView === "month") period = "month";
  else if (rawView === "days") period = days === 7 ? "custom" : days === 90 ? "next90" : "next30";
  else if (rawView === "custom") period = "custom";
  let defaults = periodRange(period, today);
  if (rawView === "month" && validDay(`${month}-01`)) defaults = monthRange(month);
  if (rawView === "days") defaults = presetRange("days", today, { days });
  const from = params.get("from") ?? defaults.from;
  const to = params.get("to") ?? defaults.to;
  let range = validDay(from) && validDay(to) && from <= to ? clampRange(from, to) : defaults;
  if (rawView === "year") {
    period = `year-${Number(range.from.slice(0, 4))}`;
    range = presetRange("year", today, { year: Number(range.from.slice(0, 4)) });
  }
  if (rawView === "month") range = monthRange(range.from.slice(0, 7));
  return {
    view, period, ...range, days,
    category: [...new Set(params.getAll("category").map((key) => key.trim()).filter(Boolean))],
    status: STATUSES.includes(params.get("status") ?? "") ? params.get("status")! : "",
    q: (params.get("q") ?? "").trim().slice(0, 200),
    closingSoon: params.get("closingSoon") === "1",
    officialOnly: params.get("official") === "1",
    item: (params.get("item") ?? "").slice(0, 300),
  };
}

export function calendarParams(query: CalendarQuery, api = false): URLSearchParams {
  const params = new URLSearchParams({ from: query.from, to: query.to });
  if (!api) {
    params.set("view", query.view);
    params.set("period", query.period);
    params.set("days", String(query.days));
    if (query.closingSoon) params.set("closingSoon", "1");
    if (query.officialOnly) params.set("official", "1");
    if (query.item) params.set("item", query.item);
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
  return (precision === "day" ? DAY_FORMAT : MONTH_FORMAT).format(new Date(value));
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

export interface RegistrationEvent {
  item: CalendarItem;
  kind: "opens" | "closes";
  from: string;
  to: string;
  precision: "day" | "month";
  label: string;
}

export function shortDate(day: string, precision: "day" | "month" = "day"): string {
  return (precision === "day" ? SHORT_DAY_FORMAT : SHORT_MONTH_FORMAT).format(new Date(`${day.slice(0, 10)}T12:00:00Z`));
}

export function registrationEvents(item: CalendarItem): RegistrationEvent[] {
  const edition = item.edition;
  const boundaries = [
    { kind: "opens" as const, value: edition.opens_at, other: edition.opens_until, precision: edition.opens_precision },
    { kind: "closes" as const, value: edition.closes_at, other: edition.closes_from, precision: edition.closes_precision },
  ];
  return boundaries.flatMap(({ kind, value, other, precision }) => {
    if (!value || !precision || (kind === "closes" && item.metadata.deadline_rolling)) return [];
    const day = itemDate(value);
    const otherDay = precision === "month" && other ? itemDate(other) : day;
    const from = kind === "closes" ? otherDay : day;
    const to = kind === "closes" ? day : otherDay;
    const suffix = precision === "month" && from.slice(0, 7) !== to.slice(0, 7) ? `–${shortDate(to, "month")}` : "";
    return [{
      item, kind, from, to, precision,
      label: `${edition.basis === "tentative" ? "~" : ""}${shortDate(from, precision)}${suffix}`
    }];
  });
}

export function keyDatesText(item: CalendarItem, events = registrationEvents(item)): string {
  if (item.metadata.deadline_rolling) {
    const opening = events.find((event) => event.kind === "opens") ?? registrationEvents(item).find((event) => event.kind === "opens");
    return `${opening ? `Opens ${opening.label} · ` : ""}deadline rolling, apply early`;
  }
  if (!events.length) return "Registration dates vary by vacancy or programme";
  return `${events.map((event) => `Registration ${event.kind} ${event.label}`).join(" · ")} · ${item.edition.basis}`;
}

export function monthsInRange(range: { from: string; to: string }): string[] {
  const months: string[] = [];
  for (let month = range.from.slice(0, 7); month <= range.to.slice(0, 7); month = shiftMonth(month, 1)) months.push(month);
  return months;
}

export interface RegistrationRow {
  item: CalendarItem;
  events: RegistrationEvent[];
}

export function registrationMonths(items: CalendarItem[], range: { from: string; to: string }) {
  const entries = items.map((item) => ({ item, events: registrationEvents(item) }));
  return monthsInRange(range).map((month) => {
    const rows: RegistrationRow[] = [];
    for (const entry of entries) {
      const events = entry.events.filter((event) => event.precision === "month"
        ? event.from.slice(0, 7) <= month && event.to.slice(0, 7) >= month
        : event.from.startsWith(month) && event.from >= range.from && event.from <= range.to);
      if (events.length) rows.push({ item: entry.item, events });
    }
    rows.sort((left, right) => left.events[0].from.localeCompare(right.events[0].from) || left.item.programme.name.localeCompare(right.item.programme.name));
    return { month, rows };
  });
}

export interface RecurringRow {
  item: CalendarItem;
  occurrences: CalendarItem[];
  rule: string;
}

export function collapseRecurrences(items: CalendarItem[], today: string): { dated: CalendarItem[]; recurring: RecurringRow[] } {
  const byProgramme = new Map<string, CalendarItem[]>();
  for (const item of items) {
    const key = item.programme.slug;
    byProgramme.set(key, [...(byProgramme.get(key) ?? []), item]);
  }
  const dated: CalendarItem[] = [];
  const recurring: RecurringRow[] = [];
  for (const occurrences of byProgramme.values()) {
    const years = occurrences.map((item) => item.edition.year);
    const monthly = /every month|each month|monthly/i.test(occurrences[0].metadata.opening_text ?? "");
    // The API occurrence suffix distinguishes independent windows within one edition.
    const repeated = new Set(years).size < occurrences.length || occurrences.some((item) => /:[1-9]\d*$/.test(item.id));
    if (!monthly && !repeated) {
      dated.push(...occurrences);
      continue;
    }
    const ordered = [...occurrences].sort((left, right) => {
      if (left.is_open_now !== right.is_open_now) return left.is_open_now ? -1 : 1;
      const leftDay = left.edition.closes_at ? itemDate(left.edition.closes_at) : "9999";
      const rightDay = right.edition.closes_at ? itemDate(right.edition.closes_at) : "9999";
      if ((leftDay >= today) !== (rightDay >= today)) return leftDay >= today ? -1 : 1;
      return leftDay.localeCompare(rightDay);
    });
    const item = ordered[0];
    const rule = [item.metadata.opening_text, item.metadata.deadline_text && `Closes ${item.metadata.deadline_text}`].filter(Boolean).join(" · ");
    recurring.push({ item, occurrences, rule: rule || "Recurring registration windows. Check the official call for each intake." });
  }
  return { dated, recurring };
}

export function daysUntilDeadline(item: CalendarItem, today: string): number | null {
  if (item.metadata.deadline_rolling || !item.edition.closes_at || item.edition.closes_precision !== "day") return null;
  return Math.round((Date.parse(itemDate(item.edition.closes_at)) - Date.parse(today)) / 86_400_000);
}

export function isClosingSoon(item: CalendarItem, today: string): boolean {
  const days = daysUntilDeadline(item, today);
  return item.edition.status !== "closed" && days !== null && days >= 0 && days <= 30;
}

export function selectOpenNow(items: CalendarItem[], today: string): CalendarItem[] {
  const ordered = items.filter((item) => item.is_open_now && (daysUntilDeadline(item, today) ?? 0) >= 0)
    .sort((left, right) => {
      const leftDeadline = !left.metadata.deadline_rolling && left.edition.closes_at ? Date.parse(left.edition.closes_at) : Infinity;
      const rightDeadline = !right.metadata.deadline_rolling && right.edition.closes_at ? Date.parse(right.edition.closes_at) : Infinity;
      return leftDeadline - rightDeadline || left.programme.name.localeCompare(right.programme.name);
    });
  return ordered.filter((item, index) => ordered.findIndex((other) => other.programme.slug === item.programme.slug) === index);
}

export function filterCalendarItems(items: CalendarItem[], query: CalendarQuery, today: string): CalendarItem[] {
  const term = query.q.toLocaleLowerCase();
  return items.filter((item) => (!query.category.length || query.category.includes(item.programme.category)) &&
    (!term || `${item.programme.name} ${item.programme.organiser}`.toLocaleLowerCase().includes(term)) &&
    (!query.status || (query.status === "open" ? item.is_open_now : item.edition.status === query.status)) &&
    (!query.closingSoon || isClosingSoon(item, today)) &&
    (!query.officialOnly || item.edition.basis === "official"));
}

export function howToApply(item: CalendarItem, hasOfficialLink = Boolean(item.programme.url)): string[] {
  const supplied = item.metadata.how_to_apply?.trim();
  if (supplied) return supplied.split(/\r?\n/).map((line) => line.replace(/^\s*(?:[-*•]\s+|\d+[.)]\s+)/, "").trim()).filter(Boolean);
  return [
    hasOfficialLink ? "Open the official site and find the current cycle’s application notice." : "Find the current application notice on the organiser’s official website.",
    item.programme.eligibility ? `Check the current notice against the listed eligibility, ${item.programme.eligibility}` : "Check the current notice for course, graduation year, location and other eligibility requirements.",
    item.metadata.hiring_mode ? `Follow the published application and selection route. ${item.metadata.hiring_mode}` : "Follow the application instructions in the current notice and retain your submission acknowledgement.",
  ];
}

export function officialDeadline(item: CalendarItem): string | null {
  return item.edition.basis === "official" && item.edition.closes_precision === "day" && !item.metadata.deadline_rolling
    ? item.edition.closes_at : null;
}

export function monthPrecisionItems(items: CalendarItem[], month: string): CalendarItem[] {
  return items.filter((item) => {
    const { opens_at, closes_at, opens_precision, closes_precision } = item.edition;
    if (opens_precision !== "month" && closes_precision !== "month") return false;
    const from = opens_at ? itemDate(opens_at).slice(0, 7) : closes_at ? itemDate(closes_at).slice(0, 7) : "9999";
    const to = item.metadata.deadline_rolling ? "9999" : closes_at ? itemDate(closes_at).slice(0, 7) : item.edition.opens_until ? itemDate(item.edition.opens_until).slice(0, 7) : from;
    return from <= month && to >= month;
  });
}

export function timelineWindow(item: CalendarItem, months: string[]): { start: number; end: number; rolling: boolean; deadline: number | null } | null {
  if (!months.length) return null;
  const { opens_at, closes_at } = item.edition;
  const startMonth = opens_at ? itemDate(opens_at).slice(0, 7) : !item.metadata.deadline_rolling && closes_at ? itemDate(closes_at).slice(0, 7) : null;
  if (!startMonth) return null;
  const rolling = item.metadata.deadline_rolling;
  const endMonth = rolling ? months[months.length - 1] : closes_at ? itemDate(closes_at).slice(0, 7) : item.edition.opens_until ? itemDate(item.edition.opens_until).slice(0, 7) : startMonth;
  if (startMonth > months[months.length - 1] || endMonth < months[0]) return null;
  const start = Math.max(0, months.findIndex((month) => month >= startMonth));
  const last = months.findLastIndex((month) => month <= endMonth);
  const deadline = officialDeadline(item);
  return { start, end: Math.max(start, last), rolling, deadline: deadline ? months.indexOf(itemDate(deadline).slice(0, 7)) : null };
}

export function eventsOnDay(items: CalendarItem[], day: string): RegistrationEvent[] {
  return items.flatMap(registrationEvents).filter((event) => event.precision === "day" && event.from === day);
}

export async function fetchCalendar(query: CalendarQuery, options?: RequestInit): Promise<CalendarResponse> {
  const base = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  // Fetch the complete period so search, facets and quick filters are immediate and local.
  const bounded = { ...query, ...clampRange(query.from, query.to), category: [], status: "", q: "" };
  const response = await fetch(`${base}/calendar?${calendarParams(bounded, true)}`, options);
  if (!response.ok) throw new Error("The calendar could not be loaded.");
  return response.json();
}
