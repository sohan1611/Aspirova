import { PHASE_PRODUCTION_BUILD } from "next/constants";
import { failedList, loadedList, type ListState } from "./listState";

// CI/local next builds deliberately use an unreachable placeholder API. Only in
// that build phase, outside Vercel, render an explicit failure with data=null.
// Its client results component fetches on mount so an offline build can heal.
// Never substitute [] or total=0: ISR would cache that as a successful empty page.
// Vercel builds retry transient load failures twice (after 3s and 8s), then throw
// the last error, leaving the previous good deployment serving traffic. Unknown
// failures and other 4xx responses throw immediately; CI/local builds never retry.
// Runtime failures must also throw, so ISR retains the last good prerender rather
// than caching a failed render. Successful zero responses remain genuine zero.

const BUILD_RETRY_DELAYS_MS = [3_000, 8_000] as const;

function transientFailure(error: unknown): string | null {
  if (!(error instanceof Error)) return null;
  if (error.name === "TimeoutError" || error.name === "AbortError") return error.name;
  // Fetch's TypeError is transient; arbitrary TypeErrors may be coding bugs.
  if (error.name === "TypeError" && /^(fetch failed|Failed to fetch|NetworkError when attempting to fetch resource\.?)$/.test(error.message)) {
    return "TypeError";
  }
  // api.ts list reads use fetchListing -> listJson, which puts the HTTP status
  // in this exact message. Also accept errors exposing a numeric status field.
  const status = "status" in error ? error.status
    : Number(/^Couldn't load results: (\d{3})$/.exec(error.message)?.[1]);
  return typeof status === "number" && (status === 429 || (Number.isInteger(status) && status >= 500 && status <= 599))
    ? `HTTP ${status}` : null;
}

export async function withBuildFallback<T>(
  load: () => Promise<T>,
  count: (data: T) => number,
): Promise<ListState<T>> {
  try {
    const vercelBuild = process.env.NEXT_PHASE === PHASE_PRODUCTION_BUILD && process.env.VERCEL === "1";
    let data: T;
    for (let attempt = 0; ; attempt++) {
      try {
        data = await load();
        break;
      } catch (error) {
        const delay = BUILD_RETRY_DELAYS_MS[attempt];
        const failure = vercelBuild ? transientFailure(error) : null;
        if (!failure || delay === undefined) throw error;
        console.error(`[build] API read failed (${failure}), retrying in ${delay / 1000}s (attempt ${attempt + 2}/3)`);
        await new Promise<void>(resolve => setTimeout(resolve, delay));
      }
    }
    const loadedAt = (data as { loadedAt?: number } | null)?.loadedAt;
    return loadedList(data, count(data), loadedAt);
  } catch (error) {
    if (process.env.NEXT_PHASE === PHASE_PRODUCTION_BUILD && process.env.VERCEL !== "1") {
      return failedList<T>(null);
    }
    throw error;
  }
}
