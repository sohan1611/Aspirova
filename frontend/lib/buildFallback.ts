import { PHASE_PRODUCTION_BUILD } from "next/constants";

// Statically rendered pages fetch at BUILD time - which force-dynamic pages never
// did. CI builds against a placeholder API URL by design, so an unreachable API
// must not fail the build.
//
// Deliberately scoped to the build phase. Unlike /pricing, which has a meaningful
// FALLBACK_PLANS, there is no static stand-in for a feed: the content IS the API
// data, so an empty render is a bad page rather than a degraded one. At runtime
// the error must propagate instead, because Next then keeps serving the last good
// prerender rather than replacing it with an empty one.
export async function withBuildFallback<T>(
  load: () => Promise<T>,
  fallback: () => T,
): Promise<T> {
  try {
    return await load();
  } catch (error) {
    if (process.env.NEXT_PHASE === PHASE_PRODUCTION_BUILD) {
      return fallback();
    }
    throw error;
  }
}
