import { getCountry } from "./countries";
import { parseRoleSignalParams } from "./roleSignalQuery";
import type { SavedSearchParams } from "./types";

const STRING_KEYS = ["q", "category", "kind", "scope", "country", "source", "experience", "registration", "status"] as const;
const LIST_KEYS = ["location", "comp_type", "organiser_type", "mode"] as const;
const NUMBER_KEYS = ["deadline_within", "prize_min"] as const;

export interface SearchParamReader {
  get(name: string): string | null;
  getAll(name: string): string[];
}

export function getSavedSearchParams(search: SearchParamReader): SavedSearchParams {
  const roleParams = parseRoleSignalParams(search);
  delete roleParams.posted_within;
  const params: SavedSearchParams = { ...roleParams };
  for (const key of STRING_KEYS) {
    const value = search.get(key)?.trim();
    if (value) Object.assign(params, { [key]: value });
  }
  const remote = search.get("remote");
  if (remote === "true" || remote === "false") params.remote = remote === "true";
  for (const key of LIST_KEYS) {
    const values = search.getAll(key).map((value) => value.trim()).filter(Boolean);
    if (values.length) params[key] = values;
  }
  for (const key of NUMBER_KEYS) {
    const raw = search.get(key);
    if (raw?.trim() && Number.isSafeInteger(Number(raw)) && Number(raw) >= 0) {
      params[key] = Number(raw);
    }
  }
  return params;
}

export function savedSearchParamsFromQuery(query: object): SavedSearchParams {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value == null) continue;
    for (const item of Array.isArray(value) ? value : [value]) search.append(key, String(item));
  }
  return getSavedSearchParams(search);
}

export function hasSavedSearchParams(search: SearchParamReader): boolean {
  return Object.keys(getSavedSearchParams(search)).length > 0;
}

export function savedSearchSummary(params: SavedSearchParams): string {
  const parts: string[] = [];
  if (params.q) parts.push(`“${params.q}”`);
  if (params.category) parts.push(params.category);
  else if (params.kind) parts.push(params.kind);
  if (params.role) parts.push(params.role);
  if (params.paid === true) parts.push("paid");
  if (params.paid === false) parts.push("unpaid or pay not stated");
  if (params.remote === true) parts.push("remote");
  if (params.remote === false) parts.push("on-site");
  if (params.country) parts.push(getCountry(params.country)?.name ?? params.country.toUpperCase());
  else if (params.scope) parts.push(params.scope);
  if (params.source) parts.push(params.source);
  if (params.experience === "early") parts.push("early career");
  if (params.min_stipend != null) parts.push(`at least ₹${params.min_stipend.toLocaleString("en-IN")}/month`);
  if (params.part_time === true) parts.push("part-time");
  if (params.max_duration != null) parts.push(`up to ${params.max_duration} months`);
  if (params.job_offer === true) parts.push("job offer possible");
  for (const key of LIST_KEYS) parts.push(...(params[key] ?? []).map((value) => value.replaceAll("_", " ")));
  if (params.registration) parts.push(`${params.registration} registration`);
  if (params.deadline_within != null) parts.push(`closing within ${params.deadline_within} days`);
  if (params.prize_min != null) parts.push(`prize at least ₹${params.prize_min.toLocaleString("en-IN")}`);
  if (params.status) parts.push(params.status);
  return parts.join(" · ") || "All opportunities";
}

export function savedSearchHref(params: SavedSearchParams): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value == null) continue;
    for (const item of Array.isArray(value) ? value : [value]) search.append(key, String(item));
  }
  const path = params.kind === "competitions" ? "/competitions" : "/";
  const query = search.toString();
  return query ? `${path}?${query}` : path;
}

export function canonicalSavedSearchParams(params: SavedSearchParams): string {
  const normalized = savedSearchParamsFromQuery(params);
  return JSON.stringify(Object.fromEntries(
    Object.entries(normalized).sort(([left], [right]) => left.localeCompare(right)).map(
      ([key, value]) => [key, Array.isArray(value) ? [...value].sort() : value],
    ),
  ));
}

export function savedSearchEditHref(params: SavedSearchParams, id: number): string {
  const [pathname, query] = savedSearchHref(params).split("?");
  const search = new URLSearchParams(query);
  search.set("editSearch", String(id));
  return pathname + "?" + search.toString();
}
