"use client";

import { useEffect } from "react";
import { recordView, type RecentItem } from "@/lib/recentlyViewed";

type RecordOpportunityViewProps = Omit<RecentItem, "viewedAt">;

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
  }, [slug, title, companyName, companyDomain, companyLogoUrl, category]);

  return null;
}
