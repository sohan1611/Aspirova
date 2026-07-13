import { useCallback, useSyncExternalStore } from "react";
import { useHydrated } from "@/lib/useHydrated";

export const FIELDS = [
  { key: "software", label: "Software Engineering" },
  { key: "data_ai", label: "Data & AI / ML" },
  { key: "product_design", label: "Product & Design" },
  { key: "marketing", label: "Marketing & Growth" },
  { key: "finance", label: "Finance & Consulting" },
  { key: "business_ops", label: "Business & Operations" },
  { key: "research", label: "Research & Academia" },
  { key: "hardware", label: "Hardware & Electronics" },
  { key: "content_media", label: "Content & Media" },
  { key: "other", label: "Open to anything" },
] as const;

export type InterestFieldKey = (typeof FIELDS)[number]["key"];

export const INTERESTS_STORAGE_KEY = "aspirova.interests";
export const INTERESTS_EVENT = "aspirova:interests-change";
export const OPEN_ONBOARDING_EVENT = "aspirova:open-onboarding";

interface InterestsSnapshot {
  fields: InterestFieldKey[];
  hasStoredInterests: boolean;
}

const EMPTY_INTERESTS: InterestsSnapshot = {
  fields: [],
  hasStoredInterests: false,
};
const FIELD_KEYS = new Set<string>(FIELDS.map((field) => field.key));

let cachedRawValue: string | null | undefined;
let cachedSnapshot = EMPTY_INTERESTS;
let inMemoryRawValue: string | null = null;

function normalizeFields(fields: readonly string[]): InterestFieldKey[] {
  const seen = new Set<InterestFieldKey>();

  for (const field of fields) {
    if (FIELD_KEYS.has(field)) {
      seen.add(field as InterestFieldKey);
    }
  }

  return FIELDS.flatMap((field) => (seen.has(field.key) ? [field.key] : []));
}

function readStoredValue(): string | null {
  try {
    return window.localStorage.getItem(INTERESTS_STORAGE_KEY);
  } catch {
    // Storage can be unavailable in privacy-restricted browser contexts.
    return inMemoryRawValue;
  }
}

function getInterestsSnapshot(): InterestsSnapshot {
  const rawValue = readStoredValue();
  if (rawValue === cachedRawValue) return cachedSnapshot;

  cachedRawValue = rawValue;

  if (!rawValue) {
    cachedSnapshot = EMPTY_INTERESTS;
    return cachedSnapshot;
  }

  try {
    const parsed: unknown = JSON.parse(rawValue);
    if (
      !parsed ||
      typeof parsed !== "object" ||
      !Array.isArray((parsed as { fields?: unknown }).fields)
    ) {
      cachedSnapshot = EMPTY_INTERESTS;
      return cachedSnapshot;
    }

    cachedSnapshot = {
      fields: normalizeFields((parsed as { fields: string[] }).fields),
      hasStoredInterests: true,
    };
  } catch {
    cachedSnapshot = EMPTY_INTERESTS;
  }

  return cachedSnapshot;
}

function subscribeToInterests(onStoreChange: () => void): () => void {
  window.addEventListener(INTERESTS_EVENT, onStoreChange);
  window.addEventListener("storage", onStoreChange);

  return () => {
    window.removeEventListener(INTERESTS_EVENT, onStoreChange);
    window.removeEventListener("storage", onStoreChange);
  };
}

function getServerSnapshot(): InterestsSnapshot {
  return EMPTY_INTERESTS;
}

export function storeInterests(fields: readonly string[]): void {
  const normalizedFields = normalizeFields(fields);
  const rawValue = JSON.stringify({ fields: normalizedFields });

  cachedRawValue = rawValue;
  cachedSnapshot = { fields: normalizedFields, hasStoredInterests: true };
  inMemoryRawValue = rawValue;

  try {
    window.localStorage.setItem(INTERESTS_STORAGE_KEY, rawValue);
  } catch {
    // The in-memory snapshot remains available for this browser session.
  }

  window.dispatchEvent(new Event(INTERESTS_EVENT));
}

/** Opens the globally mounted interests dialog from any client component. */
export function requestOnboarding(): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new Event(OPEN_ONBOARDING_EVENT));
}

export function useInterests() {
  const snapshot = useSyncExternalStore(
    subscribeToInterests,
    getInterestsSnapshot,
    getServerSnapshot,
  );
  const hydrated = useHydrated();
  const setFields = useCallback((fields: readonly string[]) => {
    storeInterests(fields);
  }, []);

  return {
    fields: snapshot.fields,
    hasStoredInterests: snapshot.hasStoredInterests,
    setFields,
    hydrated,
  };
}
