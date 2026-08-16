"use client";

import { useEffect, useState } from "react";
import type { Session } from "@supabase/supabase-js";
import { createClient } from "./supabase/client";

const AUTH_HASH_PARAMS = [
  "access_token",
  "refresh_token",
  "provider_token",
  "provider_refresh_token",
  "expires_in",
  "expires_at",
  "token_type",
  "type",
];

function getUrlWithoutAuthArtifacts(href: string): string | null {
  const url = new URL(href);
  let changed = false;

  if (url.searchParams.has("code")) {
    url.searchParams.delete("code");
    changed = true;
  }

  const hashParams = new URLSearchParams(url.hash.slice(1));
  for (const param of AUTH_HASH_PARAMS) {
    if (hashParams.has(param)) {
      hashParams.delete(param);
      changed = true;
    }
  }

  if (!changed) return null;

  url.hash = hashParams.toString();
  return `${url.pathname}${url.search}${url.hash}`;
}

function scrubAuthArtifactsFromUrl() {
  if (typeof window === "undefined") return;

  const cleanUrl = getUrlWithoutAuthArtifacts(window.location.href);
  if (cleanUrl) {
    window.history.replaceState(window.history.state, "", cleanUrl);
  }
}

export type SessionState = {
  session: Session | null;
  /**
   * True once the initial lookup has settled. A caller that must tell "no
   * session" apart from "not looked yet" — the password reset page, which
   * otherwise flashes an expired-link message while the code is exchanged —
   * needs this; `useSession` alone reports both as null.
   */
  resolved: boolean;
};

export function useSessionState(): SessionState {
  const [state, setState] = useState<SessionState>({ session: null, resolved: false });

  useEffect(() => {
    const supabase = createClient();
    supabase.auth
      .getSession()
      .then(({ data }) => {
        setState({ session: data.session, resolved: true });
        // Must run after getSession: scrubbing first would strip the PKCE code
        // before supabase exchanges it.
        scrubAuthArtifactsFromUrl();
      })
      .catch(() => {
        // A lookup that failed is still a lookup that finished; callers must
        // not spin forever.
        setState({ session: null, resolved: true });
      });
    const { data: listener } = supabase.auth.onAuthStateChange((_event, newSession) => {
      // Only the initial lookup decides `resolved` — an early INITIAL_SESSION
      // event carrying null must not be mistaken for a settled answer.
      setState((previous) => ({ session: newSession, resolved: previous.resolved }));
    });
    return () => listener.subscription.unsubscribe();
  }, []);

  return state;
}

export function useSession(): Session | null {
  return useSessionState().session;
}
