export const ROLE_OPTIONS = [
  { value: "software", label: "Software" },
  { value: "data", label: "Data" },
  { value: "design", label: "Design" },
  { value: "marketing", label: "Marketing" },
  { value: "finance", label: "Finance" },
  { value: "hr", label: "HR" },
  { value: "sales", label: "Sales" },
  { value: "product", label: "Product" },
  { value: "operations", label: "Operations" },
  { value: "content", label: "Content" },
  { value: "engineering", label: "Engineering" },
  { value: "research", label: "Research" },
] as const;

export function formatDomains(roles: string[]): string {
  const labels = ROLE_OPTIONS.filter((option) => roles.includes(option.value)).map((option) => option.label);
  if (labels.length === 0) return "All domains";
  if (labels.length === 1) return labels[0];
  return `${labels.slice(0, -1).join(", ")} and ${labels[labels.length - 1]}`;
}

export function companyAlertSavedMessage(roles: string[], target: string): string {
  return roles.length === 0
    ? `We'll email you about new roles at ${target}`
    : `We'll email you about new ${formatDomains(roles)} roles at ${target}`;
}

export type Role = typeof ROLE_OPTIONS[number]["value"];
export interface RoleSignalParams {
  paid?: boolean;
  min_stipend?: number;
  part_time?: boolean;
  max_duration?: number;
  job_offer?: boolean;
  posted_within?: number;
  role?: Role;
}

export const ROLE_FILTER_KEYS = [
  "paid", "min_stipend", "part_time", "max_duration", "job_offer", "posted_within", "role",
] as const;
export type RoleFilterKey = typeof ROLE_FILTER_KEYS[number];

export function parseRoleSignalParams(sp: { get(key: string): string | null }): RoleSignalParams {
  const params: RoleSignalParams = {};
  for (const key of ["paid", "part_time", "job_offer"] as const) {
    const value = sp.get(key);
    if (value === "true" || value === "false") params[key] = value === "true";
  }
  for (const key of ["min_stipend", "max_duration", "posted_within"] as const) {
    const raw = sp.get(key);
    if (!raw?.trim()) continue;
    const value = Number(raw);
    if (!Number.isInteger(value) || value < 0) continue;
    if (key === "max_duration" && (value < 1 || value > 24)) continue;
    if (key === "posted_within" && ![1, 3, 7, 30].includes(value)) continue;
    params[key] = value;
  }
  const role = ROLE_OPTIONS.find((option) => option.value === sp.get("role"));
  if (role) params.role = role.value;
  return params;
}

export function appendRoleSignalParams(search: URLSearchParams, params: RoleSignalParams) {
  for (const key of ROLE_FILTER_KEYS) {
    if (params[key] !== undefined) search.set(key, String(params[key]));
  }
}

export function roleFilterLabel(key: RoleFilterKey, value: string): string {
  if (key === "paid") return value === "true" ? "Paid only" : "Unpaid or pay not stated";
  if (key === "min_stipend") return `Minimum ₹${Number(value).toLocaleString("en-IN")}/month`;
  if (key === "max_duration") return `Up to ${value} months`;
  if (key === "part_time") return value === "true" ? "Part-time" : "Any work schedule";
  if (key === "job_offer") return value === "true" ? "Job offer possible" : "Any job offer status";
  if (key === "posted_within") return value === "1" ? "Past 24 hours" : `Past ${value} days`;
  return ROLE_OPTIONS.find((option) => option.value === value)?.label ?? value;
}
