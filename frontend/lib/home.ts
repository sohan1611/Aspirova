import type { CalendarItem } from "./hiringCalendar";
import type { OpportunityListItem, SavedOpportunityItem } from "./types";

export const HOME_CATEGORIES = [
  ["/internships", "Internships"], ["/jobs", "Jobs"], ["/remote", "Remote"],
  ["/competitions", "Competitions"], ["/scholarships", "Scholarships"], ["/research", "Research"],
] as const;

export function closingSoonItems(items: readonly OpportunityListItem[], now: number): OpportunityListItem[] {
  return items.filter(item => item.status === "active" && !item.is_hidden && !item.safety && !item.meta?.safety
    && item.deadline_confidence === "explicit" && item.deadline && Date.parse(item.deadline) >= now
    && !item.closed_at)
    .sort((a, b) => Date.parse(a.deadline!) - Date.parse(b.deadline!) || a.slug.localeCompare(b.slug)).slice(0, 6);
}

export function calendarPreviewItems(items: readonly CalendarItem[], now: number): CalendarItem[] {
  const boundary = (item: CalendarItem) => Date.parse(item.edition.opens_at || item.edition.closes_at || "");
  const ordered = items.filter(item => item.edition.status !== "closed"
    && Number.isFinite(boundary(item))
    && (item.edition.closes_at ? Date.parse(item.edition.closes_at) >= now : boundary(item) >= now || item.is_open_now))
    .sort((a, b) => Number(a.edition.basis !== "official") - Number(b.edition.basis !== "official")
      || Math.max(now, boundary(a)) - Math.max(now, boundary(b)) || a.id.localeCompare(b.id));
  return ordered.filter((item, i) => ordered.findIndex(other => other.programme.slug === item.programme.slug) === i).slice(0, 3);
}

export interface DeskDeadline {
  kind: "listing" | "programme";
  slug: string;
  title: string;
  deadline: string;
  confidence: "explicit";
}

export interface DeskBlock<T> {
  items: T[];
  count: number;
  reason: string | null;
}

export interface HomeDesk {
  matches: DeskBlock<OpportunityListItem>;
  deadlines: DeskBlock<DeskDeadline>;
  followed: DeskBlock<OpportunityListItem>;
  applications: DeskBlock<SavedOpportunityItem>;
  warnings: DeskBlock<SavedOpportunityItem>;
}

export const DESK_BLOCKS = ["matches", "deadlines", "followed", "applications", "warnings"] as const;
export type DeskKey = typeof DESK_BLOCKS[number];

// Validate each envelope separately so a missing/broken block cannot hide its neighbours.
export function validDeskBlock(value: unknown): value is DeskBlock<unknown> {
  if (!value || typeof value !== "object") return false;
  const block = value as Partial<DeskBlock<unknown>>;
  return Array.isArray(block.items) && typeof block.count === "number" && Number.isFinite(block.count);
}
