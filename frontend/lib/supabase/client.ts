import { createClient as createSupabaseClient } from "@supabase/supabase-js";

// Auth state lives entirely client-side in Phase 1 (Doc 07 Part 1.7: "basic
// auth UI"). No server-side session/middleware yet - the bookmark button is
// a client component anyway, so there is no SSR auth-flash problem to
// solve here. Revisit if a server-rendered "your bookmarks" page is added.
export function createClient() {
  // Use implicit flow: token in URL hash, auto-detected client-side.
  // This app has no server callback route to exchange a PKCE code.
  return createSupabaseClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
  );
}
