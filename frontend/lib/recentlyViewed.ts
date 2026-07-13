import { useSyncExternalStore } from "react";
import { useHydrated } from "@/lib/useHydrated";

export interface RecentItem {
  slug: string;
  title: string;
  companyName: string | null;
  companyDomain: string | null;
  companyLogoUrl: string | null;
  category: string | null;
  viewedAt: number;
}

export const RECENTLY_VIEWED_STORAGE_KEY = "aspirova.recentlyViewed";
export const RECENTLY_VIEWED_EVENT = "aspirova:recently-viewed";

const MAX_RECENT_ITEMS = 12;
const EMPTY_RECENT_ITEMS: RecentItem[] = [];

let cachedRawValue: string | undefined;
let cachedSnapshot = EMPTY_RECENT_ITEMS;
let inMemoryRawValue: string | null = null;

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

function isRecentItem(value: unknown): value is RecentItem {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;

  const item = value as Record<string, unknown>;
  return (
    typeof item.slug === "string" &&
    typeof item.title === "string" &&
    isNullableString(item.companyName) &&
    isNullableString(item.companyDomain) &&
    isNullableString(item.companyLogoUrl) &&
    isNullableString(item.category) &&
    typeof item.viewedAt === "number" &&
    Number.isFinite(item.viewedAt)
  );
}

function readStoredValue(): string | null {
  if (typeof window === "undefined") return null;

  try {
    return window.localStorage.getItem(RECENTLY_VIEWED_STORAGE_KEY);
  } catch {
    // Storage can be unavailable in privacy-restricted browser contexts.
    return inMemoryRawValue;
  }
}

function getRecentlyViewedRawValue(): string {
  return readStoredValue() ?? "[]";
}

function parseRecentlyViewed(rawValue: string): RecentItem[] {
  if (rawValue === cachedRawValue) return cachedSnapshot;

  cachedRawValue = rawValue;

  try {
    const parsed: unknown = JSON.parse(rawValue);
    if (!Array.isArray(parsed) || !parsed.every(isRecentItem)) {
      cachedSnapshot = EMPTY_RECENT_ITEMS;
      return cachedSnapshot;
    }

    cachedSnapshot = parsed.length > 0 ? parsed.slice(0, MAX_RECENT_ITEMS) : EMPTY_RECENT_ITEMS;
  } catch {
    cachedSnapshot = EMPTY_RECENT_ITEMS;
  }

  return cachedSnapshot;
}

function subscribeToRecentlyViewed(onStoreChange: () => void): () => void {
  if (typeof window === "undefined") return () => {};

  window.addEventListener(RECENTLY_VIEWED_EVENT, onStoreChange);
  window.addEventListener("storage", onStoreChange);

  return () => {
    window.removeEventListener(RECENTLY_VIEWED_EVENT, onStoreChange);
    window.removeEventListener("storage", onStoreChange);
  };
}

function storeItems(items: RecentItem[]): void {
  const snapshot = items.length > 0 ? items : EMPTY_RECENT_ITEMS;
  const rawValue = JSON.stringify(snapshot);

  cachedRawValue = rawValue;
  cachedSnapshot = snapshot;
  inMemoryRawValue = rawValue;

  try {
    window.localStorage.setItem(RECENTLY_VIEWED_STORAGE_KEY, rawValue);
  } catch {
    // The in-memory snapshot remains available for this browser session.
  }

  window.dispatchEvent(new Event(RECENTLY_VIEWED_EVENT));
}

export function recordView(item: RecentItem): void {
  if (typeof window === "undefined") return;

  const nextItem = { ...item };
  const items = [
    nextItem,
    ...parseRecentlyViewed(getRecentlyViewedRawValue()).filter(
      (storedItem) => storedItem.slug !== nextItem.slug,
    ),
  ].slice(0, MAX_RECENT_ITEMS);

  storeItems(items);
}

export function clearRecentlyViewed(): void {
  if (typeof window === "undefined") return;

  storeItems(EMPTY_RECENT_ITEMS);
}

export function useRecentlyViewed(): { items: RecentItem[]; hydrated: boolean } {
  const rawValue = useSyncExternalStore(
    subscribeToRecentlyViewed,
    getRecentlyViewedRawValue,
    () => "[]",
  );
  const items = parseRecentlyViewed(rawValue);
  const hydrated = useHydrated();

  return { items, hydrated };
}
