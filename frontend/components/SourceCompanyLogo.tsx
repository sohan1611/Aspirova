"use client";

import { useEffect, useState } from "react";
import CompanyFavicon from "@/components/CompanyFavicon";
import { getExternalCompanyLogos } from "@/lib/api";
import type { ExternalCompany } from "@/lib/externalCompanies";
import type { CompanySummary } from "@/lib/types";

// All curated cards share one API request, including cards in client-side search.
let logosRequest: Promise<Record<string, CompanySummary>> | undefined;

export default function SourceCompanyLogo({
  company,
  size,
}: {
  company: ExternalCompany;
  size: number;
}) {
  const [logos, setLogos] = useState<Record<string, CompanySummary>>({});

  useEffect(() => {
    let active = true;
    logosRequest ??= getExternalCompanyLogos();
    void logosRequest.then(
      (result) => {
        if (active) setLogos(result);
      },
      () => {
        logosRequest = undefined;
      },
    );
    return () => {
      active = false;
    };
  }, []);

  return (
    <CompanyFavicon
      company={logos[company.slug] ?? {
        slug: company.slug,
        name: company.name,
        domain: null,
        logo_url: null,
      }}
      size={size}
    />
  );
}
