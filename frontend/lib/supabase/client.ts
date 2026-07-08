import {
  createClient as createSupabaseClient,
  type SupabaseClient,
} from "@supabase/supabase-js";

// Auth state lives entirely client-side in Phase 1 (Doc 07 Part 1.7: "basic
// auth UI"). No server-side session/middleware yet - the bookmark button is
// a client component anyway, so there is no SSR auth-flash problem to
// solve here. Revisit if a server-rendered "your bookmarks" page is added.
let browserClient: SupabaseClient | undefined;

export function createClient(): SupabaseClient {
  // Singleton: one browser client per tab. Multiple GoTrueClient instances
  // share the same localStorage auth key and fight over token auto-refresh +
  // storage events, which storms into runaway CPU/memory on pages that mount
  // several useSession() consumers at once (e.g. /pricing). @supabase/ssr's
  // createBrowserClient memoised for us; raw createClient does not, so we do.
  if (browserClient) return browserClient;
  // Use implicit flow: token in URL hash, auto-detected client-side.
  // This app has no server callback route to exchange a PKCE code.
  browserClient = createSupabaseClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
  );
  return browserClient;
}
