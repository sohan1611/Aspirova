import { withBuildFallback } from "@/lib/buildFallback";
import { CompaniesBuildRecovery } from "@/components/BuildListingRecovery";
import type { Metadata } from "next";
import Link from "next/link";
import CompanyFavicon from "@/components/CompanyFavicon";
import SourceCompanyCard from "@/components/SourceCompanyCard";
import { getCompanies } from "@/lib/api";
import { EXTERNAL_COMPANIES } from "@/lib/externalCompanies";
import { ListingEmpty, ListingSnapshotNotice } from "@/components/ListingFeedback";

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
  const { data: companies } = await withBuildFallback(getCompanies, data => data.length);
  if (!companies) return <main className="mx-auto max-w-6xl px-4 py-10"><h1 className="font-serif text-3xl font-bold">Companies hiring now</h1><CompaniesBuildRecovery /></main>;

  return (
    <main className="mx-auto w-full max-w-[1680px] px-4 py-10 sm:px-6 sm:py-14 lg:px-10 xl:px-12">
      <header className="max-w-3xl">
        <p className="eyebrow">The roster</p>
        <h1 className="mt-3 font-serif text-4xl font-bold leading-tight tracking-tight text-foreground sm:text-5xl">
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
          className="mt-2 font-serif text-2xl font-bold leading-tight text-foreground sm:text-3xl"
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

      <ListingSnapshotNotice loadedAt={companies.loadedAt} expiresAt={companies.expiresAt} />
      {companies.length > 0 ? (
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {companies.map((company) => (
            <Link
              key={company.slug}
              href={companyPath(company.slug)}
              className="group flex min-h-44 flex-col rounded-lg border border-border bg-card p-5 shadow-soft transition-colors duration-300 ease-premium hover:border-primary/45 focus-visible:border-primary/45 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
            >
              <CompanyFavicon company={company} size={70} />

              <div className="mt-auto pt-6">
                <h2 className="min-w-0 break-words font-serif text-md font-bold leading-snug text-card-foreground transition-colors duration-300 ease-premium group-hover:text-primary group-focus-visible:text-primary">
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
        <ListingEmpty pathname="/companies" title="No companies are hiring here yet." />
      )}
    </main>
  );
}
