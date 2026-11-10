import { useCallback, useSyncExternalStore } from "react";
import { type FieldProfile } from "@/lib/taxonomy";
import { normalizeProfile } from "@/lib/profilePreferences";
import { useHydrated } from "@/lib/useHydrated";

export const FIELD_PROFILE_STORAGE_KEY = "aspirova.field_profile";
export const FIELD_PROFILE_EVENT = "aspirova:field-profile-change";
export const OPEN_ONBOARDING_EVENT = "aspirova:open-onboarding";

interface FieldProfileSnapshot {
  profile: FieldProfile;
  hasStoredProfile: boolean;
}

const EMPTY_FIELD_PROFILE: FieldProfile = {
  stream: null,
  divisions: [],
  interests: [],
  country: null,
};
const EMPTY_FIELD_PROFILE_SNAPSHOT: FieldProfileSnapshot = {
  profile: EMPTY_FIELD_PROFILE,
  hasStoredProfile: false,
};

let cachedRawValue: string | null | undefined;
let cachedSnapshot = EMPTY_FIELD_PROFILE_SNAPSHOT;
let inMemoryRawValue: string | null = null;
let storageUnavailable = false;

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

    const profile = normalizeProfile(parsed);
    cachedSnapshot = { profile, hasStoredProfile: hasFieldProfileSelections(profile) };
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
  cachedSnapshot = {
    profile: normalizedProfile,
    hasStoredProfile: hasFieldProfileSelections(normalizedProfile),
  };
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

export function hasFieldProfileSelections(profile: FieldProfile | null): profile is FieldProfile {
  return Boolean(profile?.stream || profile?.divisions.length || profile?.interests.length);
}

/** Opens the globally mounted field-profile dialog from any client component. */
export function requestOnboarding(): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new Event(OPEN_ONBOARDING_EVENT));
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
