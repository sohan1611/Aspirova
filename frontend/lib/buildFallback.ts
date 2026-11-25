import { PHASE_PRODUCTION_BUILD } from "next/constants";
import { failedList, loadedList, type ListState } from "./listState";

// CI/local next builds deliberately use an unreachable placeholder API. Only in
// that build phase, outside Vercel, render an explicit failure with data=null.
// Its client results component fetches on mount so an offline build can heal.
// Never substitute [] or total=0: ISR would cache that as a successful empty page.
// Vercel builds retry transient load failures twice (after 3s and 8s), within
// one 40s budget including reads and waits, then render the same failed/null
// shell. The client fetches on mount and ISR can fill it later. Unknown
// failures and other 4xx responses throw immediately; CI/local builds never retry.
// Runtime failures must also throw, so ISR retains the last good prerender rather
// than caching a failed render. Successful zero responses remain genuine zero.

const BUILD_RETRY_DELAYS_MS = [3_000, 8_000] as const;
const BUILD_READ_BUDGET_MS = 40_000;

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
  load: (signal?: AbortSignal) => Promise<T>,
  count: (data: T) => number,
): Promise<ListState<T>> {
  const vercelBuild = process.env.NEXT_PHASE === PHASE_PRODUCTION_BUILD && process.env.VERCEL === "1";
  let budgetTimer: ReturnType<typeof setTimeout> | undefined;
  let expired = false;
  const controller = vercelBuild ? new AbortController() : null;
  try {
    const budget = vercelBuild ? new Promise<never>((_resolve, reject) => {
      budgetTimer = setTimeout(() => {
        expired = true;
        const error = new Error("Build API read budget exhausted");
        error.name = "TimeoutError";
        controller?.abort(error);
        reject(error);
      }, BUILD_READ_BUDGET_MS);
    }) : null;
    let data: T;
    for (let attempt = 0; ; attempt++) {
      try {
        data = await (budget ? Promise.race([load(controller?.signal), budget]) : load());
        break;
      } catch (error) {
        const delay = BUILD_RETRY_DELAYS_MS[attempt];
        const failure = vercelBuild ? transientFailure(error) : null;
        if (!failure || expired || delay === undefined) throw error;
        console.error(`[build] API read failed (${failure}), retrying in ${delay / 1000}s (attempt ${attempt + 2}/3)`);
        let retryTimer: ReturnType<typeof setTimeout> | undefined;
        try {
          const wait = new Promise<void>(resolve => { retryTimer = setTimeout(resolve, delay); });
          await (budget ? Promise.race([wait, budget]) : wait);
        } finally {
          clearTimeout(retryTimer);
        }
      }
    }
    const loadedAt = (data as { loadedAt?: number } | null)?.loadedAt;
    return loadedList(data, count(data), loadedAt);
  } catch (error) {
    if (process.env.NEXT_PHASE === PHASE_PRODUCTION_BUILD &&
      (process.env.VERCEL !== "1" || transientFailure(error))) {
      if (vercelBuild) console.error("[build] API read unavailable; rendering recovery shell");
      return failedList<T>(null);
    }
    throw error;
  } finally {
    clearTimeout(budgetTimer);
  }
}
