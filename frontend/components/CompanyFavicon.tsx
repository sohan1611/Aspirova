"use client";

import { useState } from "react";
import type { CompanySummary } from "@/lib/types";

const MONOGRAM_COLORS = [
  "#7c4a2b",
  "#5e2b47",
  "#4a5d4f",
  "#7a5c22",
  "#6b3a2f",
  "#3f5561",
  "#6a4b6e",
  "#8a4a3a",
  "#4c5a3a",
  "#5a4a76",
] as const;

interface CompanyFaviconProps {
  company: CompanySummary | null;
  size?: number;
}

/**
 * The only client leaf in the feed card - everything else stays
 * server-rendered text. Isolated here so a broken/missing favicon can
 * fall back to an initial-letter avatar via onError, which needs JS,
 * without making the whole card (and its SEO-relevant text) client-side.
 */
export default function CompanyFavicon({
  company,
  size = 44,
}: CompanyFaviconProps) {
  const [failed, setFailed] = useState(false);
  const name = company?.name?.trim() || "?";
  const colorIndex =
    name.split("").reduce((sum, character) => sum + character.charCodeAt(0), 0) %
    MONOGRAM_COLORS.length;
  const src =
    company?.logo_url ??
    (company?.domain
      ? `https://www.google.com/s2/favicons?domain=${encodeURIComponent(company.domain)}&sz=64`
      : null);

  if (!src || failed) {
    return (
      <div
        aria-hidden="true"
        className="grid h-11 w-11 shrink-0 place-items-center rounded-lg text-sm font-semibold text-[#f7f1e6] ring-1 ring-black/5"
        style={{
          backgroundColor: MONOGRAM_COLORS[colorIndex],
          ...(size === 44 ? {} : { height: size, width: size }),
        }}
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
      width={size}
      height={size}
      loading="lazy"
      referrerPolicy="no-referrer"
      onError={() => setFailed(true)}
      className="h-11 w-11 shrink-0 rounded-lg border border-border bg-background object-contain p-1.5"
      style={size === 44 ? undefined : { height: size, width: size }}
    />
  );
}
