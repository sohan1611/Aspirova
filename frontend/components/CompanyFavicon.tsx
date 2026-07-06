"use client";

import { useState } from "react";
import type { CompanySummary } from "@/lib/types";

/**
 * The only client leaf in the feed card - everything else stays
 * server-rendered text. Isolated here so a broken/missing favicon can
 * fall back to an initial-letter avatar via onError, which needs JS,
 * without making the whole card (and its SEO-relevant text) client-side.
 */
export default function CompanyFavicon({ company }: { company: CompanySummary | null }) {
  const [failed, setFailed] = useState(false);
  const name = company?.name ?? "?";
  const src =
    company?.logo_url ??
    (company?.domain
      ? `https://www.google.com/s2/favicons?domain=${encodeURIComponent(company.domain)}&sz=64`
      : null);

  if (!src || failed) {
    return (
      <div
        aria-hidden="true"
        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-secondary text-sm font-semibold text-secondary-foreground"
      >
        {name.charAt(0).toUpperCase()}
      </div>
    );
  }

  return (
    // eslint-disable-next-line @next/next/no-img-element -- external, unpredictable-domain favicons; next/image would need per-domain remotePatterns config for a purely decorative icon
    <img
      src={src}
      alt=""
      width={36}
      height={36}
      loading="lazy"
      referrerPolicy="no-referrer"
      onError={() => setFailed(true)}
      className="h-9 w-9 shrink-0 rounded-md border border-border bg-background object-contain p-1"
    />
  );
}
