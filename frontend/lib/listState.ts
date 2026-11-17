import { getCountry } from "./countries";
import { ROLE_FILTER_KEYS, roleFilterLabel, type RoleFilterKey } from "./roleSignalQuery";
import { PROGRAMME_CATEGORY_LABELS } from "./programmes";
import type { Facets } from "./types";

/** A failed request can retain a snapshot, but can never become a true zero. */
export type ListState<T> =
  | { status: "results" | "empty"; data: T; loadedAt: number; error: null }
  | { status: "failed"; data: T | null; loadedAt: number | null; error: string };

export function loadedList<T>(data: T, count: number, loadedAt = Date.now()): ListState<T> {
  if (!Number.isSafeInteger(count) || count < 0) throw new Error("Invalid list count");
  return { status: count === 0 ? "empty" : "results", data, loadedAt, error: null };
}

export function failedList<T>(previous: ListState<T> | null, error = "Couldn't load results. Try again."): ListState<T> {
  return { status: "failed", data: previous?.data ?? null, loadedAt: previous?.loadedAt ?? null, error };
}

export async function listJson<T>(response: Response): Promise<T> {
  if (!response.ok) throw new Error(`Couldn't load results: ${response.status}`);
  return response.json();
}

/** Invalidate at request start AND cleanup; ignore late failures and successes. */
export function requestSequence() {
  let current = 0;
  return {
    start: () => ++current,
    isCurrent: (id: number) => id === current,
    cancel: () => { current++; },
  };
}

export function relativeResultTime(loadedAt: number, now = Date.now()): string {
  const minutes = Math.max(0, Math.floor((now - loadedAt) / 60_000));
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? "" : "s"} ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.floor(hours / 24);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

const PRESENTATION = new Set(["page", "cols", "rows", "view", "sort", "from", "to", "period", "item"]);
const FACET_LABELS: Record<string, keyof Facets> = {
  category: "programme_categories", field: "programme_fields", organiser: "programme_organisers",
  institution_type: "programme_institution_types", status: "programme_statuses",
  company: "company_counts", location: "location_counts", comp_type: "comp_types",
  organiser_type: "organiser_types", mode: "modes", registration: "registrations", deadline_within: "deadline_within",
};
const FILTER_NAMES: Record<string, string> = {
  category: "Category", field: "Field", organiser: "Organiser", institution_type: "Institution type",
  status: "Application status", company: "Company", location: "Location", comp_type: "Type",
  organiser_type: "Organizer type", mode: "Mode", registration: "Registration", deadline_within: "Deadline",
};
const FILTER_VALUES: Record<string, Record<string, string>> = {
  category: { internship: "Internships", job: "Jobs", hackathon: "Hackathons", competition: "Competitions", ...PROGRAMME_CATEGORY_LABELS },
  source: { direct: "Direct from company", unstop: "Unstop", remoteok: "RemoteOK", devpost: "Devpost" },
  experience: { early: "Early career", new_grad: "New grad roles" },
  scope: { domestic: "Domestic", abroad: "Abroad", both: "Domestic and abroad" },
  status: { open: "Open now", closed: "Closed", expected: "Tentative", announced: "Official upcoming" },
  mode: { online: "Online", offline: "In person", hybrid: "Hybrid" },
};

function tidyFilterName(value: string): string {
  return value.replace(/[_-]+/g, " ").replace(/\b\w/g, letter => letter.toUpperCase());
}

export function emptyFilterLabel(key: string, value: string, facets?: Facets | null): string {
  if (key === "q") return `Search: ${value}`;
  if (key === "country") return `Country: ${getCountry(value)?.name ?? value.toUpperCase()}`;
  if ((ROLE_FILTER_KEYS as readonly string[]).includes(key)) {
    const label = roleFilterLabel(key as RoleFilterKey, value);
    return key === "role" ? `Role: ${label === value ? tidyFilterName(value) : label}` : label;
  }
  if (key === "remote") return value === "true" ? "Remote" : "On-site";
  if (key === "remote_abroad") return "Remote opportunities abroad";
  if (key === "students") return value === "0" || value === "false" ? "All experience levels" : "For students";
  if (key === "kind") return value === "roles" ? "Jobs and internships" : "Competitions and hackathons";
  if (key === "top") return `Top ${value} companies`;
  if (key === "prize_min") return `Prize pool at least INR ${Number(value).toLocaleString("en-IN")}`;
  const options = facets?.[FACET_LABELS[key]];
  const matchedOption = Array.isArray(options)
    ? options.find(option => typeof option === "object" && option.value === value)
    : undefined;
  const facetLabel = typeof matchedOption === "object" ? matchedOption.label : undefined;
  const label = facetLabel ?? FILTER_VALUES[key]?.[value] ?? (FILTER_NAMES[key] ? tidyFilterName(value) : value);
  return `${FILTER_NAMES[key] ?? tidyFilterName(key)}: ${label}`;
}

export function emptyFilterLinks(pathname: string, query: URLSearchParams, facets?: Facets | null) {
  return [...query.entries()].flatMap(([key, value], index) => {
    if (!value || PRESENTATION.has(key)) return [];
    const next = new URLSearchParams();
    [...query.entries()].forEach(([k, v], i) => { if (i !== index && k !== "page") next.append(k, v); });
    return [{ key: `${key}-${index}`, label: emptyFilterLabel(key, value, facets), href: pathname + (next.size ? `?${next}` : "") }];
  });
}
