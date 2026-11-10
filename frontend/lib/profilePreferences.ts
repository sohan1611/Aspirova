import type { FieldProfile } from "./taxonomy";

export function normalizeCountry(value: unknown): string | null {
  return typeof value === "string" && /^[A-Z]{2}$/.test(value) ? value : null;
}

function normalizeKey(value: unknown): string | null {
  return typeof value === "string" ? value.trim() || null : null;
}

function normalizeKeys(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return [...new Set(value.map(normalizeKey).filter((key): key is string => key !== null))];
}

export function normalizeProfile(value: unknown): FieldProfile {
  const profile: Record<string, unknown> = value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
  return {
    stream: normalizeKey(profile.stream),
    divisions: normalizeKeys(profile.divisions),
    interests: normalizeKeys(profile.interests),
    country: normalizeCountry(profile.country),
  };
}

export function mergeProfile(value: unknown, changes: Partial<FieldProfile>): FieldProfile {
  return normalizeProfile({ ...normalizeProfile(value), ...changes });
}

export function countrySyncDecision(accountCountry: unknown, browserCountry: unknown): {
  country: string | null;
  action: "adopt" | "upload" | "none";
} {
  const account = normalizeCountry(accountCountry);
  const browser = normalizeCountry(browserCountry);
  if (account) return { country: account, action: "adopt" };
  if (browser) return { country: browser, action: "upload" };
  return { country: null, action: "none" };
}
