"use client";

import { useSyncExternalStore } from "react";
import { getCountry } from "@/lib/countries";
import { useStoredCountryCode } from "@/lib/country";
import { useHydrated } from "@/lib/useHydrated";

export const FEED_ORDER_STORAGE_KEY = "aspirova.feedOrder";
const FEED_ORDER_EVENT = "aspirova:feed-order-change";

function readGlobalFeedOrder(): boolean {
  try {
    return window.localStorage.getItem(FEED_ORDER_STORAGE_KEY) === "global";
  } catch {
    return false;
  }
}

function subscribeFeedOrder(onChange: () => void): () => void {
  window.addEventListener(FEED_ORDER_EVENT, onChange);
  window.addEventListener("storage", onChange);
  return () => {
    window.removeEventListener(FEED_ORDER_EVENT, onChange);
    window.removeEventListener("storage", onChange);
  };
}

export function setGlobalFeedOrder(global: boolean): void {
  try {
    if (global) window.localStorage.setItem(FEED_ORDER_STORAGE_KEY, "global");
    else window.localStorage.removeItem(FEED_ORDER_STORAGE_KEY);
  } catch {
    // Storage can be unavailable in privacy-restricted browser contexts.
  }
  window.dispatchEvent(new Event(FEED_ORDER_EVENT));
}

// Also used for the opt-in label while global order is selected.
export function useFeedCountry(): string | null {
  const storedCountry = useStoredCountryCode();
  const hydrated = useHydrated();
  if (!hydrated) return null;
  const country = getCountry(storedCountry);
  if (country) return country.code;
  try {
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    return zone === "Asia/Kolkata" || zone === "Asia/Calcutta" ? "IN" : null;
  } catch {
    return null;
  }
}

export function usePreferredCountry(): string | null {
  const country = useFeedCountry();
  const global = useSyncExternalStore(subscribeFeedOrder, readGlobalFeedOrder, () => false);
  return global ? null : country;
}
