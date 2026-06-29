import { createBrowserClient } from "@supabase/ssr";

// Auth state lives entirely client-side in Phase 1 (Doc 07 Part 1.7: "basic
// auth UI"). No server-side session/middleware yet - the bookmark button is
// a client component anyway, so there is no SSR auth-flash problem to
// solve here. Revisit if a server-rendered "your bookmarks" page is added.
export function createClient() {
  return createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
  );
}
