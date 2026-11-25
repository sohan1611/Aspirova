import { getCountry } from "./countries";
import type { EligibilityFacts, EligibilityFact, Stage } from "./types";

export const ELIGIBILITY_FILTER_KEYS = ["grad_year", "stage", "eligibility_stated", "visa"] as const;
export const STAGE_OPTIONS: { value: Stage; label: string }[] = [
  { value: "school", label: "School" },
  { value: "undergraduate", label: "Undergraduate" },
  { value: "postgraduate", label: "Postgraduate" },
  { value: "doctoral", label: "PhD" },
  { value: "recent_graduate", label: "Recent graduate" },
];

export interface EligibilityParams {
  grad_year?: number;
  stage?: Stage[];
  eligibility_stated?: boolean;
  visa?: "needs";
}

export function parseEligibilityParams(sp: { get(key: string): string | null; getAll(key: string): string[] }): EligibilityParams {
  const raw = sp.get("grad_year");
  const year = raw && /^\d{4}$/.test(raw) ? Number(raw) : undefined;
  const stage = [...new Set(sp.getAll("stage").flatMap((value) => value.split(",")))].filter(
    (value): value is Stage => STAGE_OPTIONS.some((option) => option.value === value),
  );
  return {
    visa: sp.get("visa") === "needs" ? "needs" : undefined,
    grad_year: year && year >= 2015 && year <= 2035 ? year : undefined,
    stage: stage.length ? stage : undefined,
    eligibility_stated: ["1", "true"].includes(sp.get("eligibility_stated") ?? "") ? true : undefined,
  };
}

export function appendEligibilityParams(sp: URLSearchParams, params: EligibilityParams): void {
  if (params.visa === "needs") sp.set("visa", "needs");
  if (params.grad_year !== undefined) sp.set("grad_year", String(params.grad_year));
  for (const stage of params.stage ?? []) sp.append("stage", stage);
  if (params.eligibility_stated) sp.set("eligibility_stated", "1");
}

export const ELIGIBILITY_DIMENSIONS = [
  ["grad_years", "Graduation year"], ["stages", "Study level"],
  ["final_year_only", "Final year"], ["degree_levels", "Required degree"],
  ["college_restriction", "College restriction"], ["citizenship", "Citizenship"],
  ["remote_mode", "Work mode"], ["remote_regions", "Remote from"],
  ["work_authorization", "Work authorization"], ["visa_sponsorship", "Visa sponsorship"],
  ["timezones", "Time zone"],
] as const;

const STAGE_LABELS: Record<Stage, string> = {
  school: "School students", undergraduate: "Undergraduates", postgraduate: "Postgraduates",
  doctoral: "PhD students", recent_graduate: "Recent graduates",
};

export function eligibilityValueText(key: typeof ELIGIBILITY_DIMENSIONS[number][0], fact: EligibilityFact<unknown>): string {
  const value = fact.value;
  if (key === "remote_mode") return { remote: "Remote", hybrid: "Hybrid", onsite: "On-site" }[value as string] ?? "Not stated";
  if (key === "visa_sponsorship") return value ? "Visa sponsorship available" : "No visa sponsorship";
  if (key === "timezones") {
    const zone = value as { min: number; max: number };
    const offset = (n: number) => "UTC" + (n >= 0 ? "+" : "") + String(n);
    return zone.min === zone.max ? offset(zone.min) : offset(zone.min) + " to " + offset(zone.max);
  }
  if (key === "remote_regions") return (value as string[]).map(regionText).join(", ");
  if (key === "work_authorization") return (value as string[]).length ? (value as string[]).join(" / ") + " work authorization required" : "Work authorization required — country not stated";
  if (key === "final_year_only") return "Final year students only";
  if (key === "college_restriction") return "Specific colleges only";
  if (!Array.isArray(value)) return "Not stated";
  if (key === "grad_years") {
    const years = value as number[];
    const consecutive = years.length > 1 && years.every((year, index) => index === 0 || year === years[index - 1] + 1);
    return (consecutive ? String(years[0]) + "-" + String(years.at(-1)).slice(-2) : years.join(", ")) + " batch";
  }
  if (key === "stages") return (value as Stage[]).map((stage) => STAGE_LABELS[stage]).join(", ");
  if (key === "citizenship") return value.length ? value.join(" / ") + " citizens only" : "Citizenship requirement — country not stated";
  return value.map((level) => ({ diploma: "Diploma", bachelor: "Bachelor’s", master: "Master’s", doctorate: "Doctorate" })[level as string] ?? level).join(" / ") + " degree required";
}

export function eligibilityLabelText(facts?: EligibilityFacts | null, filters: EligibilityParams = {}): string | null {
  if ((filters.grad_year !== undefined && !facts?.grad_years) || (filters.stage?.length && !facts?.stages)) return "Eligibility not stated";
  const parts = ELIGIBILITY_DIMENSIONS.slice(0, 6).flatMap(([key]) => facts?.[key] ? [eligibilityValueText(key, facts[key])] : []);
  return parts.length ? parts.join(" · ") : null;
}

/** Validate evidence objects before a successful response enters the read cache. */
export function assertEligibilityFacts(value: unknown): void {
  if (value == null) return; // Older cached payloads can omit the field.
  if (typeof value !== "object" || Array.isArray(value) || !Number.isInteger((value as EligibilityFacts).v) || (value as EligibilityFacts).v < 1) throw new Error("Invalid eligibility facts");
  const facts = value as Record<string, unknown>;
  for (const [key] of ELIGIBILITY_DIMENSIONS) {
    const fact = facts[key] as EligibilityFact<unknown> | undefined;
    if (fact === undefined) continue;
    if (!fact || typeof fact !== "object" || typeof fact.evidence !== "string" || !fact.evidence || fact.evidence.length > 160 || !["title", "description", "tags", "location"].includes(fact.source)) throw new Error("Invalid eligibility evidence");
    const result = fact.value;
    const offset = (n: unknown): n is number => typeof n === "number" && Number.isFinite(n) && n >= -12 && n <= 14;
    const zone = result as { min?: unknown; max?: unknown } | null;
    const valid = key === "remote_mode" ? typeof result === "string" && ["remote", "hybrid", "onsite"].includes(result)
      : key === "visa_sponsorship" ? typeof result === "boolean"
      : key === "timezones" ? !!zone && typeof zone === "object" && !Array.isArray(zone) && Object.keys(zone).length === 2 && offset(zone.min) && offset(zone.max) && zone.min <= zone.max
      : key === "remote_regions" ? Array.isArray(result) && result.length > 0 && result.every((item) => typeof item === "string" && (REGION_TOKENS.has(item) || (/^[A-Z]{2}$/.test(item) && !!getCountry(item))))
      : key === "work_authorization" ? Array.isArray(result) && result.every((item) => typeof item === "string" && /^[A-Z]{2}$/.test(item) && !!getCountry(item))
      : key === "final_year_only" || key === "college_restriction" ? result === true
      : Array.isArray(result) && (key === "citizenship"
        ? result.every((item) => typeof item === "string" && /^[A-Z]{2}$/.test(item))
        : result.length > 0 && result.every((item) => key === "grad_years" ? Number.isInteger(item) && item >= 2015 && item <= 2035
          : key === "stages" ? STAGE_OPTIONS.some((option) => option.value === item)
            : ["diploma", "bachelor", "master", "doctorate"].includes(item)));
    if (!valid) throw new Error("Invalid eligibility value");
  }
}

/** One quote per distinct sentence, for the card tooltip and screen readers. */
export function eligibilityEvidenceText(facts?: EligibilityFacts | null): string {
  const seen = new Set<string>();
  const parts: string[] = [];
  for (const fact of Object.values(facts ?? {})) {
    if (!fact || typeof fact !== "object" || typeof fact.evidence !== "string") continue;
    const key = fact.source + "\u0000" + fact.evidence;
    if (seen.has(key)) continue;
    seen.add(key);
    const lead = fact.source === "title" ? "Title says" : fact.source === "tags" ? "Source tags say" : fact.source === "location" ? "Source location says" : "Listing says";
    parts.push(`${lead} “${fact.evidence}”`);
  }
  return parts.length ? parts.join("; ") + " — check all requirements" : "";
}


export const REGION_TOKENS = new Set(["WORLDWIDE", "EUROPE", "EMEA", "APAC", "ASIA", "LATAM", "NORTH_AMERICA", "MIDDLE_EAST", "AFRICA"]);
const REGION_LABELS: Record<string, string> = { WORLDWIDE: "Worldwide", EUROPE: "Europe", EMEA: "EMEA", APAC: "APAC", ASIA: "Asia", LATAM: "Latin America", NORTH_AMERICA: "North America", MIDDLE_EAST: "Middle East", AFRICA: "Africa" };
function regionText(code: string): string {
  return REGION_LABELS[code] ?? (["US", "GB"].includes(code) ? { US: "US", GB: "UK" }[code]! : getCountry(code)?.name ?? code);
}

/** Source-grounded restrictions; the structured remote flag never implies a region. */
export function remoteLabelText(facts?: EligibilityFacts | null, isRemote = false, scopeActive = false): string | null {
  const mode = facts?.remote_mode?.value ?? (isRemote ? "remote" : undefined);
  const parts: string[] = [];
  if (mode) {
    const label = { remote: "Remote", hybrid: "Hybrid", onsite: "On-site" }[mode];
    const regions = facts?.remote_regions?.value;
    parts.push(mode === "onsite" ? label : regions?.length
      ? label + " · " + regions.slice(0, 3).map(regionText).join(", ") + (regions.length > 3 ? " +" + String(regions.length - 3) : "") + (regions.length === 1 && regions[0] !== "WORLDWIDE" ? " only" : "")
      : label + (scopeActive ? " — where you can work from is not stated" : ""));
  }
  if (facts?.visa_sponsorship?.value === false) parts.push("No visa sponsorship");
  if (facts?.work_authorization) parts.push(eligibilityValueText("work_authorization", facts.work_authorization));
  return parts.length ? parts.join(" · ") : null;
}
