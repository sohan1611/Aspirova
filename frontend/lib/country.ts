import { useSyncExternalStore } from "react";
import { useHydrated } from "@/lib/useHydrated";
import { getAccount, updateAccount } from "@/lib/api";
import { hasFieldProfileSelections, readStoredFieldProfile, storeFieldProfile } from "@/lib/fieldProfile";
import { countrySyncDecision, mergeProfile, normalizeCountry, normalizeProfile } from "@/lib/profilePreferences";
import type { FieldProfile } from "@/lib/taxonomy";

export const COUNTRY_STORAGE_KEY = "aspirova.country";
export const COUNTRY_EVENT = "aspirova:country-change";

let inMemoryCountryCode: string | null = null;
let preferenceWrites: Promise<void> = Promise.resolve();

// Serialize account JSON updates so rapid country/interest edits cannot race.
function enqueuePreferenceWrite(write: () => Promise<void>): Promise<void> {
  const pending = preferenceWrites.then(write);
  preferenceWrites = pending.catch(() => {});
  return pending;
}

// localStorage as an external store (the sanctioned pattern — a
// setState-in-effect read triggers cascading renders). Writes dispatch a
// same-tab event so the store re-reads immediately; "storage" covers other tabs.
export function readStoredCountryCode(): string | null {
  try {
    return normalizeCountry(window.localStorage.getItem(COUNTRY_STORAGE_KEY));
  } catch {
    // Storage can be unavailable in privacy-restricted browser contexts.
    return inMemoryCountryCode;
  }
}

function storeCountryLocally(code: string): void {
  inMemoryCountryCode = code;
  try {
    window.localStorage.setItem(COUNTRY_STORAGE_KEY, code);
  } catch {
    // Keep the in-session preference even if persistent storage is unavailable.
  }
  window.dispatchEvent(new Event(COUNTRY_EVENT));
}

export function saveProfilePreferences(
  accessToken: string | undefined,
  changes: Partial<FieldProfile>,
): Promise<void> {
  const localProfile = mergeProfile(readStoredFieldProfile(), changes);
  storeFieldProfile(localProfile);
  const storedProfile = readStoredFieldProfile();
  const storedCountry = readStoredCountryCode();
  if (!accessToken) return Promise.resolve();

  return enqueuePreferenceWrite(async () => {
    // Read before replacing the JSON, including when this device has no profile yet.
    const account = await getAccount(accessToken);
    const base = normalizeProfile(account.field_profile);
    const profile = mergeProfile(hasFieldProfileSelections(base) ? base : localProfile, {
      country: base.country ?? localProfile.country ?? readStoredCountryCode(),
      ...changes,
    });
    await updateAccount(accessToken, { field_profile: profile });
    if (readStoredFieldProfile() === storedProfile) storeFieldProfile(profile);
    if (profile.country && readStoredCountryCode() === storedCountry) {
      storeCountryLocally(profile.country);
    }
  });
}

export function storeCountryCode(code: string, accessToken?: string): Promise<void> {
  const country = normalizeCountry(code);
  if (!country) return Promise.resolve();
  storeCountryLocally(country);
  // Signed-out visitors retain the country-only local store.
  if (!accessToken) return Promise.resolve();
  return saveProfilePreferences(accessToken, { country });
}

export function syncAccountPreferences(
  accessToken: string,
  isCurrent: () => boolean,
): Promise<void> {
  const localProfile = readStoredFieldProfile();
  const localCountry = readStoredCountryCode();
  return enqueuePreferenceWrite(async () => {
    if (!isCurrent()) return;
    const account = await getAccount(accessToken);
    if (!isCurrent() || localProfile !== readStoredFieldProfile() ||
      localCountry !== readStoredCountryCode()) return;

    const serverProfile = normalizeProfile(account.field_profile);
    const decision = countrySyncDecision(serverProfile.country, localCountry);
    const profile = mergeProfile(
      hasFieldProfileSelections(serverProfile) ? serverProfile : localProfile,
      { country: decision.country },
    );
    if (hasFieldProfileSelections(profile) || decision.country) storeFieldProfile(profile);
    if (decision.action === "adopt" && decision.country) {
      storeCountryLocally(decision.country);
    } else if (decision.action === "upload") {
      await updateAccount(accessToken, { field_profile: profile });
    }
  });
}

export function subscribeStoredCountry(onChange: () => void): () => void {
  window.addEventListener(COUNTRY_EVENT, onChange);
  window.addEventListener("storage", onChange);
  return () => {
    window.removeEventListener(COUNTRY_EVENT, onChange);
    window.removeEventListener("storage", onChange);
  };
}

export function useStoredCountryCode(): string | null {
  return useSyncExternalStore(subscribeStoredCountry, readStoredCountryCode, () => null);
}

export type Currency = "INR" | "USD";

export function currencyForCountry(code: string | null): Currency {
  // India is the home-market default until another country is explicitly chosen.
  return code === null || code === "IN" ? "INR" : "USD";
}

export function useCurrency(): {
  currency: Currency;
  hydrated: boolean;
  countryCode: string | null;
} {
  const countryCode = useStoredCountryCode();
  const hydrated = useHydrated();

  return {
    // Match the SSR HTML before browser storage is available.
    currency: hydrated ? currencyForCountry(countryCode) : "INR",
    hydrated,
    countryCode,
  };
}
