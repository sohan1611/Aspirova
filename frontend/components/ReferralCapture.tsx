"use client";

import { useEffect, useRef } from "react";
import { useSearchParams } from "next/navigation";
import { claimReferral } from "@/lib/api";
import { useSession } from "@/lib/useSession";

const REFERRAL_STASH_KEY = "aspirova_ref";

export default function ReferralCapture() {
  const searchParams = useSearchParams();
  const session = useSession();
  const claimStartedRef = useRef(false);

  useEffect(() => {
    const code = searchParams.get("ref")?.trim();
    if (!code) return;

    try {
      if (!window.localStorage.getItem(REFERRAL_STASH_KEY)) {
        window.localStorage.setItem(REFERRAL_STASH_KEY, code);
      }
    } catch {
      // Referral capture is opportunistic and must never block page use.
    }
  }, [searchParams]);

  useEffect(() => {
    if (!session?.access_token || claimStartedRef.current) return;

    let code: string | null = null;
    try {
      code = window.localStorage.getItem(REFERRAL_STASH_KEY);
    } catch {
      return;
    }

    if (!code) return;
    claimStartedRef.current = true;

    claimReferral(code, session.access_token)
      .catch(() => {
        // Duplicate, invalid, or transient claims are silent by design.
      })
      .finally(() => {
        try {
          window.localStorage.removeItem(REFERRAL_STASH_KEY);
        } catch {
          // Ignore storage failures.
        }
      });
  }, [searchParams, session?.access_token]);

  return null;
}
