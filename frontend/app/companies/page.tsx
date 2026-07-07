import { SearchX } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { getCompanies } from "@/lib/api";
import type { CompanyListItem } from "@/lib/types";

const DESCRIPTION =
  "Browse companies with active internships and jobs auto-discovered from public career pages.";
const INTRO =
  "Companies with active opportunities, auto-discovered from public company career pages; " +
  "Aspirova links out to the original source.";
const EMPTY_STATE_CLASS_NAME = [
  "flex flex-col items-center gap-3 rounded-lg border border-dashed",
  "border-border py-16 text-center",
].join(" ");

export const dynamic = "force-dynamic";

export async function generateMetadata(): Promise<Metadata> {
  return {
    title: "Browse companies hiring - Aspirova",
    description: DESCRIPTION,
    alternates: { canonical: "/companies" },
    openGraph: {
      title: "Browse companies hiring - Aspirova",
      description: DESCRIPTION,
      type: "website",
      url: "/companies",
    },
  };
}

function companyPath(slug: string): string {
  return `/companies/${encodeURIComponent(slug)}`;
}

function openRoleLabel(count: number): string {
  return `${count} open ${count === 1 ? "role" : "roles"}`;
}

function companyCountLabel(count: number): string {
  return `${count} ${count === 1 ? "company" : "companies"}`;
}

export default async function CompaniesPage() {
  let companies: CompanyListItem[] = [];
  try {
    companies = await getCompanies();
  } catch {
    companies = [];
  }

  return (
    <main className="mx-auto max-w-4xl px-4 py-8">
      <div className="mb-6">
        <h1 className="text-3xl font-bold tracking-tight text-foreground">
          Companies hiring
        </h1>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
          {INTRO}
        </p>
      </div>

      <p className="mb-3 text-sm text-muted-foreground">
        {companyCountLabel(companies.length)}
      </p>

      {companies.length > 0 ? (
        <div className="grid gap-3 sm:grid-cols-2">
          {companies.map((company) => (
            <Link
              key={company.slug}
              href={companyPath(company.slug)}
              className={[
                "group rounded-lg border border-border bg-card p-4",
                "transition-colors hover:border-primary/50 hover:bg-accent/40",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              ].join(" ")}
            >
              <span className="block text-base font-semibold text-foreground group-hover:text-primary">
                {company.name}
              </span>
              <span className="mt-2 block text-sm text-muted-foreground">
                {openRoleLabel(company.active_count)}
              </span>
            </Link>
          ))}
        </div>
      ) : (
        <div className={EMPTY_STATE_CLASS_NAME}>
          <SearchX className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
          <p className="font-medium text-foreground">No companies found</p>
          <p className="max-w-xs text-sm text-muted-foreground">
            Check back soon as Aspirova discovers more public career pages.
          </p>
        </div>
      )}
    </main>
  );
}
