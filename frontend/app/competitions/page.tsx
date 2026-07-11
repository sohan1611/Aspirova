import { SearchX } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import OpportunityCard from "@/components/OpportunityCard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { getFeed } from "@/lib/api";
import { buildPageHref } from "@/lib/pagination";

const LIMIT = 20;
const DESCRIPTION =
  "Competitions and hackathons for students, auto-discovered from public sources and tracked through their registration deadlines.";
const INTRO =
  "Find competitions and hackathons worth entering, and register before their deadlines close.";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Competitions & hackathons",
  description: DESCRIPTION,
  alternates: { canonical: "/competitions" },
};

interface PageProps {
  searchParams: Promise<{
    sort?: string;
    page?: string;
  }>;
}

type CompetitionSort = "recent" | "deadline";

function sortHref(sort: CompetitionSort): string {
  return sort === "recent" ? "/competitions?sort=recent" : "/competitions";
}

function opportunityCountLabel(count: number): string {
  return `${count} ${count === 1 ? "opportunity" : "opportunities"}`;
}

export default async function CompetitionsPage({ searchParams }: PageProps) {
  const params = await searchParams;
  const page = Math.max(1, Number(params.page ?? "1") || 1);
  const sort: CompetitionSort = params.sort === "recent" ? "recent" : "deadline";
  const data = await getFeed({ kind: "competitions", sort, page, limit: LIMIT });
  const totalPages = Math.max(1, Math.ceil(data.total / LIMIT));

  return (
    <main className="mx-auto w-full max-w-[1680px] px-4 py-10 sm:px-6 sm:py-14 lg:px-10 xl:px-12">
      <header className="max-w-3xl">
        <p className="eyebrow">THE ARENA</p>
        <h1 className="mt-3 font-serif text-4xl font-semibold leading-tight tracking-tight text-foreground sm:text-5xl">
          Competitions &amp; hackathons
        </h1>
        <p className="mt-4 max-w-2xl text-sm leading-6 text-muted-foreground sm:text-base sm:leading-7">
          {INTRO}
        </p>
      </header>

      <div className="mb-5 mt-10 flex flex-wrap items-center justify-between gap-4 border-b border-border pb-4">
        <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-2">
          <p className="eyebrow">Open arena</p>
          <p className="tnum text-sm text-muted-foreground">
            {opportunityCountLabel(data.total)}
          </p>
        </div>

        <div
          className="flex min-w-0 flex-wrap items-center justify-end gap-2"
          role="group"
          aria-label="Sort opportunities"
        >
          <span className="eyebrow mr-1">Sort</span>
          <Badge
            asChild
            variant={sort === "recent" ? "heritage" : "outline"}
            className="px-2.5 py-1"
          >
            <Link href={sortHref("recent")} aria-current={sort === "recent" ? "true" : undefined}>
              Newest
            </Link>
          </Badge>
          <Badge
            asChild
            variant={sort === "deadline" ? "heritage" : "outline"}
            className="px-2.5 py-1"
          >
            <Link
              href={sortHref("deadline")}
              aria-current={sort === "deadline" ? "true" : undefined}
            >
              Closing soon
            </Link>
          </Badge>
        </div>
      </div>

      {data.items.length > 0 ? (
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {data.items.map((item) => (
            <OpportunityCard key={item.slug} item={item} />
          ))}
        </div>
      ) : (
        <section className="flex flex-col items-center rounded-xl border border-border bg-card px-5 py-16 text-center shadow-soft sm:py-20">
          <div className="rounded-lg border border-border bg-secondary/40 p-3 shadow-soft">
            <SearchX className="h-6 w-6 text-muted-foreground" aria-hidden="true" />
          </div>
          <p className="eyebrow mt-5">The arena</p>
          <h2 className="mt-2 font-serif text-xl font-semibold text-foreground">
            The next challenge is still being discovered.
          </h2>
          <p className="mt-2 max-w-md text-sm leading-6 text-muted-foreground">
            Check back soon as Aspirova indexes more competitions and hackathons.
          </p>
        </section>
      )}

      {totalPages > 1 && (
        <nav
          className="mt-8 flex flex-wrap items-center justify-center gap-3 sm:gap-4"
          aria-label="Competitions pagination"
        >
          <Button variant="outline" size="sm" disabled={page <= 1} asChild={page > 1}>
            {page > 1 ? (
              <Link href={buildPageHref(params, page - 1, "/competitions")}>Previous</Link>
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
              <Link href={buildPageHref(params, page + 1, "/competitions")}>Next</Link>
            ) : (
              "Next"
            )}
          </Button>
        </nav>
      )}
    </main>
  );
}
