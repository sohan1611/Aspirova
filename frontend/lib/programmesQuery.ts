import { getProgrammes } from "@/lib/api";
import type { ProgrammeListResponse } from "@/lib/types";

export const PROGRAMMES_LIMIT = 50;
export const PROGRAMME_FILTER_PARAM_KEYS = [
  "category",
  "field",
  "organiser",
  "institution_type",
  "status",
] as const;

export type ProgrammeFilterParamKey = (typeof PROGRAMME_FILTER_PARAM_KEYS)[number];
export type ProgrammeSearchParamValue = string | string[] | undefined;

export interface ProgrammeSearchParams {
  category?: ProgrammeSearchParamValue;
  field?: ProgrammeSearchParamValue;
  organiser?: ProgrammeSearchParamValue;
  institution_type?: ProgrammeSearchParamValue;
  status?: ProgrammeSearchParamValue;
  q?: ProgrammeSearchParamValue;
  page?: ProgrammeSearchParamValue;
}

export interface ProgrammesRequest {
  category: string[];
  field: string[];
  organiser: string[];
  institution_type: string[];
  status: string[];
  q: string | undefined;
  page: number;
}

export function parseParamValues(value: ProgrammeSearchParamValue): string[] {
  const rawValues = Array.isArray(value) ? value : value ? [value] : [];
  return Array.from(
    new Set(rawValues.map((item) => item.trim()).filter(Boolean)),
  );
}

function parseSingleParamValue(value: ProgrammeSearchParamValue): string | undefined {
  const rawValue = Array.isArray(value) ? value[0] : value;
  const nextValue = rawValue?.trim();
  return nextValue || undefined;
}

export function parseProgrammesRequest(
  query: ProgrammeSearchParams,
  options: {
    allowedCategories?: readonly string[];
    defaultCategories?: readonly string[];
  } = {},
): ProgrammesRequest {
  const rawCategories = parseParamValues(query.category);
  const allowedCategories = options.allowedCategories
    ? new Set(options.allowedCategories)
    : null;
  const selectedCategories = allowedCategories
    ? rawCategories.filter((category) => allowedCategories.has(category))
    : rawCategories;
  const scopedCategories =
    selectedCategories.length > 0
      ? selectedCategories
      : Array.from(options.defaultCategories ?? []);
  const rawPage = Array.isArray(query.page) ? query.page[0] : query.page;
  const page = Math.max(1, Number(rawPage ?? "1") || 1);

  return {
    category: scopedCategories,
    field: parseParamValues(query.field),
    organiser: parseParamValues(query.organiser),
    institution_type: parseParamValues(query.institution_type),
    status: parseParamValues(query.status),
    q: parseSingleParamValue(query.q),
    page,
  };
}

export function loadProgrammes(
  request: ProgrammesRequest,
  limit = PROGRAMMES_LIMIT,
): Promise<ProgrammeListResponse> {
  return getProgrammes({
    category: request.category,
    field: request.field,
    organiser: request.organiser,
    institution_type: request.institution_type,
    status: request.status,
    q: request.q,
    page: request.page,
    limit,
  });
}

export function programmeCountLabel(count: number): string {
  return `${count} ${count === 1 ? "programme" : "programmes"}`;
}

export function programmesTotalPages(total: number, limit = PROGRAMMES_LIMIT): number {
  return Math.max(1, Math.ceil(total / limit));
}

export function appendCurrentProgrammeFilters(
  search: URLSearchParams,
  query: ProgrammeSearchParams,
  exclude: ProgrammeFilterParamKey | "q" | null = null,
) {
  for (const key of PROGRAMME_FILTER_PARAM_KEYS) {
    if (key === exclude) continue;
    for (const value of parseParamValues(query[key])) {
      search.append(key, value);
    }
  }

  if (exclude !== "q") {
    const q = parseSingleParamValue(query.q);
    if (q) search.set("q", q);
  }
}
