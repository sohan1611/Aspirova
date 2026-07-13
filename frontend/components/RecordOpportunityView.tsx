"use client";

import { useEffect } from "react";
import { pingOpportunityView } from "@/lib/api";
import { recordView, type RecentItem } from "@/lib/recentlyViewed";

type RecordOpportunityViewProps = Omit<RecentItem, "viewedAt">;

const VIEW_PINGED_STORAGE_KEY = "aspirova.viewPinged";

export default function RecordOpportunityView({
  slug,
  title,
  companyName,
  companyDomain,
  companyLogoUrl,
  category,
}: RecordOpportunityViewProps) {
  useEffect(() => {
    recordView({
      slug,
      title,
      companyName,
      companyDomain,
      companyLogoUrl,
      category,
      viewedAt: Date.now(),
    });

    if (typeof window === "undefined") return;

    try {
      const stored = window.sessionStorage.getItem(VIEW_PINGED_STORAGE_KEY);
      const parsed: unknown = stored ? JSON.parse(stored) : [];
      const pingedSlugs = Array.isArray(parsed)
        ? parsed.filter((value): value is string => typeof value === "string")
        : [];

      if (pingedSlugs.includes(slug)) return;

      window.sessionStorage.setItem(
        VIEW_PINGED_STORAGE_KEY,
        JSON.stringify([...pingedSlugs, slug]),
      );
      void pingOpportunityView(slug);
    } catch {
      // Ignore unavailable or malformed session storage.
    }
  }, [slug, title, companyName, companyDomain, companyLogoUrl, category]);

  return null;
}
