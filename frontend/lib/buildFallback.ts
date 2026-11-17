import { PHASE_PRODUCTION_BUILD } from "next/constants";
import { failedList, loadedList, type ListState } from "./listState";

// CI/local next builds deliberately use an unreachable placeholder API. Only in
// that build phase, outside Vercel, render an explicit failure with data=null.
// Its client results component fetches on mount so an offline build can heal.
// Never substitute [] or total=0: ISR would cache that as a successful empty page.
// Vercel builds must throw, leaving the previous good deployment serving traffic.
// Runtime failures must also throw, so ISR retains the last good prerender rather
// than caching a failed render. Successful zero responses remain genuine zero.
export async function withBuildFallback<T>(
  load: () => Promise<T>,
  count: (data: T) => number,
): Promise<ListState<T>> {
  try {
    const data = await load();
    const loadedAt = (data as { loadedAt?: number } | null)?.loadedAt;
    return loadedList(data, count(data), loadedAt);
  } catch (error) {
    if (process.env.NEXT_PHASE === PHASE_PRODUCTION_BUILD && process.env.VERCEL !== "1") {
      return failedList<T>(null);
    }
    throw error;
  }
}
