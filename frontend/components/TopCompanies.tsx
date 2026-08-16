"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import CompanyFavicon from "@/components/CompanyFavicon";
import { getTopCompanies } from "@/lib/api";
import type { CompanyListItem } from "@/lib/types";
import { useSession } from "@/lib/useSession";

type LoadState = {
  sessionKey: string | null;
  status: "idle" | "success" | "error";
  companies: CompanyListItem[];
};

function openRolesLabel(count: number): string {
  return `${count} open ${count === 1 ? "role" : "roles"}`;
}

export default function TopCompanies() {
  const session = useSession();
  // Use the stable user id; Supabase rotates access tokens on refresh, which would cause needless refetches.
  const sessionKey = session?.user?.id ?? null;
  const [state, setState] = useState<LoadState>({
    sessionKey: null,
    status: "idle",
    companies: [],
  });

  useEffect(() => {
    if (!sessionKey) return;

    let cancelled = false;

    getTopCompanies()
      .then((items) => {
        if (cancelled) return;
        setState({ sessionKey, status: "success", companies: items });
      })
      .catch(() => {
        if (cancelled) return;
        setState({ sessionKey, status: "error", companies: [] });
      });

    return () => {
      cancelled = true;
    };
  }, [sessionKey]);

  if (
    !sessionKey ||
    state.sessionKey !== sessionKey ||
    state.status !== "success" ||
    state.companies.length === 0
  ) {
    return null;
  }

  return (
    <section className="mb-6" aria-labelledby="top-companies-heading">
      <div className="flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h2 id="top-companies-heading" className="eyebrow">
            Top companies
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Ranked companies with active opportunities right now.
          </p>
        </div>
      </div>

      <div className="mt-3 flex snap-x snap-mandatory gap-3 overflow-x-auto pb-2">
        {state.companies.map((company) => (
          <Link
            key={company.slug}
            href={`/companies/${company.slug}`}
            className="group flex w-52 shrink-0 snap-start items-center gap-3 rounded-xl border border-border bg-card p-3 shadow-soft transition-[transform,box-shadow,border-color] duration-300 ease-premium hover:-translate-y-0.5 hover:border-primary/50 hover:[box-shadow:var(--shadow-md)] focus-visible:-translate-y-0.5 focus-visible:border-primary/50 focus-visible:[box-shadow:var(--shadow-md)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
          >
            <CompanyFavicon company={company} size={36} />
            <div className="min-w-0">
              <h3 className="truncate text-sm font-semibold text-card-foreground transition-colors duration-300 ease-premium group-hover:text-primary group-focus-visible:text-primary">
                {company.name}
              </h3>
              <p className="mt-1 text-xs font-medium text-muted-foreground">
                {openRolesLabel(company.active_count)}
              </p>
            </div>
          </Link>
        ))}
      </div>
    </section>
  );
}
