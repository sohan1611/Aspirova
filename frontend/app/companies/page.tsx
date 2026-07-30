import { SearchX } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import CompanyFavicon from "@/components/CompanyFavicon";
import SourceCompanyCard from "@/components/SourceCompanyCard";
import { getCompanies } from "@/lib/api";
import { EXTERNAL_COMPANIES } from "@/lib/externalCompanies";
import type { CompanyListItem } from "@/lib/types";

const DESCRIPTION =
  "Browse companies with active internships and jobs auto-discovered from public career pages.";
const INTRO =
  "Companies with active opportunities, auto-discovered from public company career pages; " +
  "Aspirova links out to the original source.";
export const revalidate = 3600;

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
    <main className="mx-auto w-full max-w-[1680px] px-4 py-10 sm:px-6 sm:py-14 lg:px-10 xl:px-12">
      <header className="max-w-3xl">
        <p className="eyebrow">The roster</p>
        <h1 className="mt-3 font-serif text-4xl font-semibold leading-tight tracking-tight text-foreground sm:text-5xl">
          Companies hiring now
        </h1>
        <p className="mt-4 max-w-2xl text-sm leading-6 text-muted-foreground sm:text-base sm:leading-7">
          {INTRO}
        </p>
      </header>

      <section className="mt-10 border-y border-border py-8" aria-labelledby="marquee-title">
        <p className="eyebrow">Marquee employers</p>
        <h2
          id="marquee-title"
          className="mt-2 font-serif text-2xl font-semibold leading-tight text-foreground sm:text-3xl"
        >
          Straight to the source
        </h2>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-muted-foreground sm:text-base sm:leading-7">
          Roles at these giants live only on their own careers sites — we point you straight there,
          and track their flagship student programs.
        </p>
        <div className="mt-6 grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {EXTERNAL_COMPANIES.map((company) => (
            <SourceCompanyCard key={company.slug} company={company} />
          ))}
        </div>
      </section>

      <div className="mb-5 mt-10 flex items-center justify-between gap-4 border-b border-border pb-4">
        <p className="eyebrow">Companies</p>
        <p className="tnum text-sm text-muted-foreground">
          {companyCountLabel(companies.length)}
        </p>
      </div>

      {companies.length > 0 ? (
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {companies.map((company) => (
            <Link
              key={company.slug}
              href={companyPath(company.slug)}
              className="group flex min-h-44 flex-col rounded-xl border border-border bg-card p-5 shadow-soft transition-[transform,box-shadow,border-color] duration-300 ease-premium hover:-translate-y-1 hover:border-primary/45 hover:[box-shadow:var(--shadow-md)] focus-visible:-translate-y-1 focus-visible:border-primary/45 focus-visible:[box-shadow:var(--shadow-md)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
            >
              <div className="w-fit rounded-xl border border-border bg-secondary/40 p-1.5 shadow-soft">
                <CompanyFavicon company={company} size={56} />
              </div>

              <div className="mt-auto pt-6">
                <h2 className="min-w-0 break-words font-sans text-md font-medium leading-snug text-card-foreground transition-colors duration-300 ease-premium group-hover:text-primary group-focus-visible:text-primary">
                  {company.name}
                </h2>
                <p className="tnum mt-2 text-sm text-muted-foreground">
                  {openRoleLabel(company.active_count)}
                </p>
              </div>
            </Link>
          ))}
        </div>
      ) : (
        <section className="flex flex-col items-center rounded-xl border border-border bg-card px-5 py-16 text-center shadow-soft sm:py-20">
          <div className="rounded-lg border border-border bg-secondary/40 p-3 shadow-soft">
            <SearchX className="h-6 w-6 text-muted-foreground" aria-hidden="true" />
          </div>
          <p className="eyebrow mt-5">The roster</p>
          <h2 className="mt-2 font-serif text-xl font-semibold text-foreground">
            The next company is still being indexed.
          </h2>
          <p className="mt-2 max-w-md text-sm leading-6 text-muted-foreground">
            Check back soon as Aspirova discovers more public career pages.
          </p>
        </section>
      )}
    </main>
  );
}
