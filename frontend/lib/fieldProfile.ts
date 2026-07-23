import { useCallback, useSyncExternalStore } from "react";
import { type FieldProfile } from "@/lib/taxonomy";
import { useHydrated } from "@/lib/useHydrated";

export const FIELD_PROFILE_STORAGE_KEY = "aspirova.field_profile";
export const FIELD_PROFILE_EVENT = "aspirova:field-profile-change";

interface FieldProfileSnapshot {
  profile: FieldProfile;
  hasStoredProfile: boolean;
}

const EMPTY_FIELD_PROFILE: FieldProfile = {
  stream: null,
  divisions: [],
  interests: [],
};
const EMPTY_FIELD_PROFILE_SNAPSHOT: FieldProfileSnapshot = {
  profile: EMPTY_FIELD_PROFILE,
  hasStoredProfile: false,
};

let cachedRawValue: string | null | undefined;
let cachedSnapshot = EMPTY_FIELD_PROFILE_SNAPSHOT;
let inMemoryRawValue: string | null = null;
let storageUnavailable = false;

function normalizeKey(value: unknown): string | null {
  if (typeof value !== "string") return null;

  return value.trim() || null;
}

function normalizeKeys(values: unknown): string[] {
  if (!Array.isArray(values)) return [];

  const keys: string[] = [];
  const seen = new Set<string>();
  for (const item of values) {
    const key = normalizeKey(item);
    if (!key || seen.has(key)) continue;
    seen.add(key);
    keys.push(key);
  }

  return keys;
}

function normalizeProfile(value: unknown): FieldProfile {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return EMPTY_FIELD_PROFILE;
  }

  const profile = value as Record<string, unknown>;
  return {
    stream: normalizeKey(profile.stream),
    divisions: normalizeKeys(profile.divisions),
    interests: normalizeKeys(profile.interests),
  };
}

function readStoredValue(): string | null {
  if (typeof window === "undefined") return null;
  if (storageUnavailable) return inMemoryRawValue;

  try {
    return window.localStorage.getItem(FIELD_PROFILE_STORAGE_KEY);
  } catch {
    // Storage can be unavailable in privacy-restricted browser contexts.
    storageUnavailable = true;
    return inMemoryRawValue;
  }
}

function getFieldProfileSnapshot(): FieldProfileSnapshot {
  const rawValue = readStoredValue();
  if (rawValue === cachedRawValue) return cachedSnapshot;

  cachedRawValue = rawValue;
  if (!rawValue) {
    cachedSnapshot = EMPTY_FIELD_PROFILE_SNAPSHOT;
    return cachedSnapshot;
  }

  try {
    const parsed: unknown = JSON.parse(rawValue);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      cachedSnapshot = EMPTY_FIELD_PROFILE_SNAPSHOT;
      return cachedSnapshot;
    }

    cachedSnapshot = {
      profile: normalizeProfile(parsed),
      hasStoredProfile: true,
    };
  } catch {
    cachedSnapshot = EMPTY_FIELD_PROFILE_SNAPSHOT;
  }

  return cachedSnapshot;
}

function subscribeToFieldProfile(onStoreChange: () => void): () => void {
  if (typeof window === "undefined") return () => {};

  window.addEventListener(FIELD_PROFILE_EVENT, onStoreChange);
  window.addEventListener("storage", onStoreChange);

  return () => {
    window.removeEventListener(FIELD_PROFILE_EVENT, onStoreChange);
    window.removeEventListener("storage", onStoreChange);
  };
}

function getServerSnapshot(): FieldProfileSnapshot {
  return EMPTY_FIELD_PROFILE_SNAPSHOT;
}

export function readStoredFieldProfile(): FieldProfile {
  return getFieldProfileSnapshot().profile;
}

export function storeFieldProfile(profile: FieldProfile): void {
  const normalizedProfile = normalizeProfile(profile);
  const rawValue = JSON.stringify(normalizedProfile);

  cachedRawValue = rawValue;
  cachedSnapshot = { profile: normalizedProfile, hasStoredProfile: true };
  inMemoryRawValue = rawValue;

  if (typeof window === "undefined") return;

  try {
    window.localStorage.setItem(FIELD_PROFILE_STORAGE_KEY, rawValue);
    storageUnavailable = false;
  } catch {
    // The in-memory snapshot remains available for this browser session.
    storageUnavailable = true;
  }

  window.dispatchEvent(new Event(FIELD_PROFILE_EVENT));
}

export function useFieldProfile(): {
  profile: FieldProfile;
  hasStoredProfile: boolean;
  hydrated: boolean;
  setProfile: (profile: FieldProfile) => void;
} {
  const snapshot = useSyncExternalStore(
    subscribeToFieldProfile,
    getFieldProfileSnapshot,
    getServerSnapshot,
  );
  const hydrated = useHydrated();
  const setProfile = useCallback((profile: FieldProfile) => {
    // Part 2 adds signed-in /account/me write-through; this remains local-only for now.
    storeFieldProfile(profile);
  }, []);

  return {
    profile: snapshot.profile,
    hasStoredProfile: snapshot.hasStoredProfile,
    hydrated,
    setProfile,
  };
}
