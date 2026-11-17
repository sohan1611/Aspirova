/**
 * Results store for listing pages, held outside React and keyed by route plus
 * query string. The module-level instance lives in listingResults.ts; this
 * factory keeps its state transitions independently testable.
 *
 * WHY THIS EXISTS
 *
 * Holding fetched results in component state did not survive. Measured with
 * diagnostics rendered into the DOM and the API server's access log, the effect
 * ran, the request went out, the API answered 200 with thousands of rows, and
 * neither .then nor .catch ever reached the rendered component. "settled" stayed
 * null forever: every search showed "Nothing open here" for a query the API had
 * already answered.
 *
 * These pages are statically prerendered and read useSearchParams, so the results
 * subtree ships as a Suspense fallback in the HTML. The client mounts the real
 * component into that boundary. The instance whose effect ran is not the
 * instance being rendered, and state held inside it is lost.
 *
 * The proof is in this tree: useOpportunityListingFacets fires an identical
 * promise chain and its counts arrived because it seeds state from a module-level
 * cache at mount. Same tree and fetch shape; different storage.
 *
 * Results live outside React too. useSyncExternalStore in listingResults.ts
 * makes React pull the current value on every render rather than relying on a
 * setState landing on the right instance. A remount reads this store
 * synchronously; a remount mid-flight shares the request; a re-render for another
 * reason also sees the results. Keep whole entry objects referentially stable:
 * returning a fresh snapshot on every read makes useSyncExternalStore loop.
 *
 * This store lives for one page load. It survives remounts; it is not a persistent
 * data cache. Scope separates routes: /jobs?q=data and /internships?q=data must
 * never share results, because their different base filters are absent from the
 * query string. Sequences reject superseded requests, including timed-out
 * originals racing Retry; only the current attempt may publish.
 */

import { failedList, loadedList, requestSequence, type ListState } from "./listState";

export type ListingEntry<T> = (ListState<T> | {
  status: "loading"; data: T | null; error: null; loadedAt: number | null;
}) & { key: string; retrying: boolean };

/** One page-load store. Scope separates routes, key separates exact queries. */
export function createListingStore<T extends { items: unknown[]; loadedAt?: number }>(timeoutMs = 20_000) {
  const entries = new Map<string, ListingEntry<T>>();
  const last = new Map<string, ListState<T>>();
  const sequences = new Map<string, ReturnType<typeof requestSequence>>();
  const active = new Map<string, string>();
  const listeners = new Set<() => void>();
  function remember(entry: ListingEntry<T>) {
    // Bound storage while typing; Map insertion order identifies the oldest entry.
    entries.delete(entry.key);
    entries.set(entry.key, entry);
    if (entries.size > 30) entries.delete(entries.keys().next().value!);
    listeners.forEach(listener => listener());
  }
  return {
    // Return the same whole entry until it changes (see WHY THIS EXISTS).
    get: (key: string) => entries.get(key) ?? null,
    subscribe(listener: () => void) { listeners.add(listener); return () => { listeners.delete(listener); }; },
    seed(scope: string, key: string, data: T) {
      if (active.get(scope) !== key) sequences.get(scope)?.cancel();
      active.set(scope, key);
      last.set(scope, loadedList(data, data.items.length, data.loadedAt));
    },
    load(scope: string, key: string, load: () => Promise<T>, initialData: T | null, retry = false) {
      let sequence = sequences.get(scope);
      if (!sequence) { sequence = requestSequence(); sequences.set(scope, sequence); }
      if (active.get(scope) !== key) {
        sequence.cancel();
        if (entries.get(key)?.status === "loading") entries.delete(key);
      }
      active.set(scope, key);
      const existing = entries.get(key);
      if (!retry && existing && existing.status !== "loading") {
        if (existing.status !== "failed") last.set(scope, existing);
        return;
      }
      if (existing?.status === "loading" && !retry) return;
      if (existing?.retrying) return;
      const id = sequence.start();
      const previous = last.get(scope) ?? (initialData ? loadedList(initialData, initialData.items.length, initialData.loadedAt) : null);
      remember({ key, status: "loading", data: previous?.data ?? null, loadedAt: previous?.loadedAt ?? null, error: null, retrying: retry });
      const timer = setTimeout(() => {
        if (!sequence.isCurrent(id)) return;
        sequence.cancel();
        remember({ key, ...failedList(previous, "The request timed out. Try again."), retrying: false });
      }, timeoutMs);
      void Promise.resolve().then(load).then(data => {
        if (!sequence.isCurrent(id)) return;
        const state = loadedList(data, data.items.length, data.loadedAt);
        last.set(scope, state);
        remember({ key, ...state, retrying: false });
      }).catch(() => {
        if (sequence.isCurrent(id)) remember({ key, ...failedList(previous), retrying: false });
      }).finally(() => clearTimeout(timer));
    },
  };
}
