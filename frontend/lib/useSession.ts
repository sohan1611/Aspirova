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

export function useSession(): Session | null {
  const [session, setSession] = useState<Session | null>(null);

  useEffect(() => {
    const supabase = createClient();
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
      scrubAuthArtifactsFromUrl();
    });
    const { data: listener } = supabase.auth.onAuthStateChange((_event, newSession) => {
      setSession(newSession);
    });
    return () => listener.subscription.unsubscribe();
  }, []);

  return session;
}
