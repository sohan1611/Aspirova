import type { SearchRelatedResponse } from "./types";

/** Like listingStore, survive the listing Suspense boundary's remounts. */
export function createSearchRelatedStore(
  load: (q: string, signal: AbortSignal) => Promise<SearchRelatedResponse>,
) {
  type Entry = {
    data: SearchRelatedResponse | null;
    startedAt: number;
    listingsDone: boolean;
    controller: AbortController;
    timer?: ReturnType<typeof setTimeout>;
  };
  const entries = new Map<string, Entry>();
  const active = new Map<string, string>();
  const listeners = new Set<() => void>();
  const notify = () => listeners.forEach(listener => listener());
  function discard(entry: Entry) {
    clearTimeout(entry.timer);
    entry.controller.abort();
  }
  return {
    get: (key: string) => entries.get(key)?.data ?? null,
    subscribe(listener: () => void) { listeners.add(listener); return () => { listeners.delete(listener); }; },
    start(scope: string, key: string, q?: string, retry = false) {
      const previousKey = active.get(scope);
      if (previousKey && previousKey !== key) {
        const previous = entries.get(previousKey);
        if (previous) discard(previous);
        entries.delete(previousKey);
      }
      active.set(scope, key);
      if (!q?.trim()) return;
      if (entries.has(key) && !retry) return entries.get(key);
      const previous = entries.get(key);
      if (previous) discard(previous);
      const entry: Entry = { data: null, startedAt: Date.now(), listingsDone: false, controller: new AbortController() };
      entries.set(key, entry);
      notify();
      // Starts alongside the listing loader, never awaited by that loader.
      void load(q, entry.controller.signal).then(data => {
        if (entry.controller.signal.aborted || entries.get(key) !== entry) return;
        if (entry.listingsDone && Date.now() - entry.startedAt > 1_500) {
          discard(entry);
          console.debug("Related search arrived after the display deadline");
          return;
        }
        clearTimeout(entry.timer);
        entry.data = data;
        notify();
      }).catch(error => {
        if (!entry.controller.signal.aborted) console.debug("Related search unavailable", error);
      });
      return entry;
    },
    listingsSettled(key: string, attempt?: Entry) {
      const entry = entries.get(key);
      if (!entry || (attempt && attempt !== entry) || entry.listingsDone) return;
      entry.listingsDone = true;
      if (entry.data) return;
      const remaining = 1_500 - (Date.now() - entry.startedAt);
      if (remaining <= 0) discard(entry);
      else entry.timer = setTimeout(() => discard(entry), remaining);
    },
  };
}
