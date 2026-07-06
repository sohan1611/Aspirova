import { useSyncExternalStore } from "react";

function subscribe() {
  return () => {};
}

function getSnapshot() {
  return true;
}

function getServerSnapshot() {
  return false;
}

/**
 * True once the client has hydrated, false during SSR and the first
 * client render. Needed for any UI that must read browser-only state
 * (theme, matchMedia, localStorage) without a server/client render
 * mismatch - useSyncExternalStore's getServerSnapshot is the sanctioned
 * way to express this, not a setState-in-effect.
 */
export function useHydrated(): boolean {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
