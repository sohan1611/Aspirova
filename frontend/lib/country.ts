import { useSyncExternalStore } from "react";
import { useHydrated } from "@/lib/useHydrated";

export const COUNTRY_STORAGE_KEY = "aspirova.country";
export const COUNTRY_EVENT = "aspirova:country-change";

// localStorage as an external store (the sanctioned pattern — a
// setState-in-effect read triggers cascading renders). Writes dispatch a
// same-tab event so the store re-reads immediately; "storage" covers other tabs.
export function readStoredCountryCode(): string | null {
  try {
    return window.localStorage.getItem(COUNTRY_STORAGE_KEY);
  } catch {
    // Storage can be unavailable in privacy-restricted browser contexts.
    return null;
  }
}

export function storeCountryCode(code: string): void {
  try {
    window.localStorage.setItem(COUNTRY_STORAGE_KEY, code);
  } catch {
    // Keep the in-session preference even if persistent storage is unavailable.
  }
  window.dispatchEvent(new Event(COUNTRY_EVENT));
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
