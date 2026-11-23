import { assertEligibilityFacts } from "./eligibility";
import { unstable_cache } from "next/cache";
import { listJson } from "./listState";

export type ListingSnapshot<T> = T & { loadedAt: number; expiresAt: number };
type Shape = "page" | "array" | "object" | "calendar" | "company";

/** Cache parsed successes only: malformed 200 bodies must not poison ISR. */
export async function fetchListing<T>(url: string, seconds = 300, shape: Shape = "page", signal?: AbortSignal): Promise<ListingSnapshot<T>> {
  const load = async () => {
    const timeout = AbortSignal.timeout(20_000);
    const response = await fetch(url, { cache: "no-store", signal: signal ? AbortSignal.any([signal, timeout]) : timeout });
    if (shape === "company" && response.status === 404) return { data: null, loadedAt: Date.now() };
    const data = await listJson<T>(response);
    if (!data || (shape === "array" ? !Array.isArray(data) : typeof data !== "object")) throw new Error("Invalid listing response");
    if (shape === "page" || shape === "calendar" || shape === "company") {
      const page = data as { items?: unknown; total?: unknown; rolling?: unknown };
      if (!Array.isArray(page.items)) throw new Error("Invalid listing items");
      if (shape !== "calendar" && (typeof page.total !== "number" || !Number.isSafeInteger(page.total) || page.total < 0)) throw new Error("Invalid listing total");
      if (shape === "calendar" && !Array.isArray(page.rolling)) throw new Error("Invalid calendar response");
    }
    const items = Array.isArray(data) ? data : (data as { items?: unknown[] }).items;
    for (const item of items ?? []) {
      if (item && typeof item === "object" && "eligibility" in item) assertEligibilityFacts(item.eligibility);
    }
    return { data, loadedAt: Date.now() };
  };
  // A new time bucket must await validation rather than receive unstable_cache's
  // stale-while-revalidate value. A failed refresh then throws to the route's ISR
  // boundary, preserving its last good HTML. Errors never create a cache entry.
  const snapshot = typeof window === "undefined" && seconds > 0
    ? await unstable_cache(load, ["validated-list-v1", url, String(Math.floor(Date.now() / (seconds * 1000)))], { revalidate: seconds })()
    : await load();
  return (snapshot.data === null ? null : Object.assign(snapshot.data as object, {
    loadedAt: snapshot.loadedAt,
    expiresAt: snapshot.loadedAt + (seconds > 0 ? seconds : 300) * 1000,
  })) as ListingSnapshot<T>;
}
