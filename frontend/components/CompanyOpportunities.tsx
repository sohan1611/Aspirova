import { ExternalLink, SearchX } from "lucide-react";
import Link from "next/link";
import CompanyFavicon from "@/components/CompanyFavicon";
import OpportunityCard from "@/components/OpportunityCard";
import { Button } from "@/components/ui/button";
import type { CompanyPage as CompanyPageData } from "@/lib/types";

const INTRO =
  "Auto-discovered from public company career pages; " +
  "Aspirova links out to the original source.";

interface CompanyOpportunitiesProps {
  data: CompanyPageData;
  page: number;
  slug: string;
}

function companyPath(slug: string): string {
  return `/companies/${encodeURIComponent(slug)}`;
}

function companyPageHref(slug: string, page: number): string {
  const basePath = companyPath(slug);
  return page <= 1 ? basePath : `${basePath}/page/${page}`;
}

function companyWebsite(domain: string): string {
  return /^https?:\/\//i.test(domain) ? domain : `https://${domain}`;
}

export default function CompanyOpportunities({
  data,
  page,
  slug,
}: CompanyOpportunitiesProps) {
  const totalPages = Math.max(1, Math.ceil(data.total / data.limit));
  const domain = data.company.domain?.trim() || null;

  return (
    <main className="mx-auto w-full max-w-[1680px] px-4 py-10 sm:px-6 sm:py-14 lg:px-10 xl:px-12">
      <Link
        href="/companies"
        className="inline-flex text-sm text-muted-foreground underline-offset-4 transition-colors hover:text-foreground hover:underline"
      >
        ← All companies
      </Link>

      <header className="mt-8 border-b border-border pb-10">
        <div className="flex flex-col items-start gap-5 sm:flex-row sm:items-center sm:gap-7">
          <div className="rounded-xl border border-border bg-card p-2 shadow-soft">
            <CompanyFavicon company={data.company} size={72} />
          </div>

          <div className="min-w-0">
            <p className="eyebrow">Company field note</p>
            <h1 className="mt-2 break-words font-serif text-4xl font-semibold leading-tight tracking-tight text-foreground sm:text-5xl">
              {data.company.name}
            </h1>
            {domain && (
              <a
                href={companyWebsite(domain)}
                target="_blank"
                rel="noopener noreferrer"
                className="mt-3 inline-flex max-w-full items-center gap-1.5 break-all text-sm font-medium text-primary underline-offset-4 transition-colors hover:text-primary/80 hover:underline"
              >
                {domain}
                <ExternalLink className="size-3.5 shrink-0" aria-hidden="true" />
                <span className="sr-only"> (opens in a new tab)</span>
              </a>
            )}
          </div>
        </div>

        <p className="mt-6 max-w-2xl text-sm leading-6 text-muted-foreground sm:text-base sm:leading-7">
          {INTRO}
        </p>
      </header>

      <section className="mt-10" aria-labelledby="company-opportunities-title">
        <p className="eyebrow">Open opportunities</p>
        <div className="mb-5 mt-2 flex flex-wrap items-end justify-between gap-3 border-b border-border pb-4">
          <h2
            id="company-opportunities-title"
            className="font-serif text-2xl font-semibold leading-tight text-foreground sm:text-3xl"
          >
            Current openings
          </h2>
          <p className="tnum text-sm text-muted-foreground">
            {data.total} {data.total === 1 ? "opportunity" : "opportunities"}
          </p>
        </div>

        {data.items.length > 0 ? (
          <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {data.items.map((item) => (
              <OpportunityCard key={item.slug} item={item} />
            ))}
          </div>
        ) : (
          <div className="flex flex-col items-center rounded-xl border border-border bg-card px-5 py-16 text-center shadow-soft sm:py-20">
            <div className="rounded-lg border border-border bg-secondary/40 p-3 shadow-soft">
              <SearchX className="h-6 w-6 text-muted-foreground" aria-hidden="true" />
            </div>
            <p className="eyebrow mt-5">Open opportunities</p>
            <h2 className="mt-2 font-serif text-xl font-semibold text-foreground">
              Nothing on the ledger today.
            </h2>
            <p className="mt-2 max-w-md text-sm leading-6 text-muted-foreground">
              Check back soon as Aspirova discovers new roles from this company&apos;s public
              career pages.
            </p>
          </div>
        )}

        {totalPages > 1 && (
          <nav
            aria-label="Company opportunities pagination"
            className="mt-8 flex flex-wrap items-center justify-center gap-4"
          >
            <Button variant="outline" size="sm" disabled={page <= 1} asChild={page > 1}>
              {page > 1 ? (
                <Link href={companyPageHref(slug, page - 1)}>Previous</Link>
              ) : (
                "Previous"
              )}
            </Button>
            <span className="tnum text-sm text-muted-foreground">
              Page {page} of {totalPages}
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={page >= totalPages}
              asChild={page < totalPages}
            >
              {page < totalPages ? (
                <Link href={companyPageHref(slug, page + 1)}>Next</Link>
              ) : (
                "Next"
              )}
            </Button>
          </nav>
        )}
      </section>
    </main>
  );
}
