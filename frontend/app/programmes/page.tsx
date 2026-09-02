import { AlertCircle, SearchX } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import MatchedProgrammes from "@/components/MatchedProgrammes";
import {
  ProgrammesActiveFilterChips,
  type ProgrammesFacetsStatus,
} from "@/components/ProgrammesAdvancedFilters";
import ProgrammesListingControls from "@/components/ProgrammesListingControls";
import ProgrammeCard from "@/components/ProgrammeCard";
import { FeedNavigationProvider } from "@/components/FeedNavigation";
import { Button } from "@/components/ui/button";
import { getFacets } from "@/lib/api";
import {
  formatProgrammeCategory,
  PROGRAMME_CATEGORIES,
  PROGRAMME_CATEGORY_LABELS,
} from "@/lib/programmes";
import {
  appendCurrentProgrammeFilters,
  loadProgrammes,
  parseParamValues,
  parseProgrammesRequest,
  programmeCountLabel,
  PROGRAMMES_LIMIT,
  type ProgrammeSearchParams,
} from "@/lib/programmesQuery";
import type { Facets, ProgrammeListItem } from "@/lib/types";

const DESCRIPTION =
  "Research internships, fellowships, government and open-source programmes - with the windows they usually open in.";

export async function generateMetadata(): Promise<Metadata> {
  return {
    title: "Programmes almanac",
    description: DESCRIPTION,
    alternates: { canonical: "/programmes" },
    openGraph: {
      title: "Programmes almanac - Aspirova",
      description: DESCRIPTION,
      type: "website",
      url: "/programmes",
    },
  };
}

interface PageProps {
  searchParams: Promise<ProgrammeSearchParams>;
}

function categoryHref(query: ProgrammeSearchParams, category?: string): string {
  const search = new URLSearchParams();
  appendCurrentProgrammeFilters(search, query, "category");
  if (category) search.set("category", category);
  const queryString = search.toString();
  return queryString ? `/programmes?${queryString}` : "/programmes";
}

function pageHref(page: number, query: ProgrammeSearchParams): string {
  const search = new URLSearchParams({ page: String(page) });
  appendCurrentProgrammeFilters(search, query);
  return `/programmes?${search.toString()}`;
}

export default async function ProgrammesPage({ searchParams }: PageProps) {
  const query = await searchParams;
  const request = parseProgrammesRequest(query);
  const selectedCategories = parseParamValues(query.category).filter(
    (category) => category in PROGRAMME_CATEGORY_LABELS,
  );
  const page = request.page;

  let programmes: ProgrammeListItem[] = [];
  let total = 0;
  let failed = false;
  let facets: Facets | null = null;
  let facetsStatus: ProgrammesFacetsStatus = "loaded";

  try {
    const data = await loadProgrammes(request, PROGRAMMES_LIMIT);
    programmes = data.items;
    total = data.total;
  } catch {
    failed = true;
  }

  try {
    facets = await getFacets({ source: "programmes" });
  } catch {
    facetsStatus = "error";
  }

  const totalPages = Math.max(1, Math.ceil(total / PROGRAMMES_LIMIT));
  const activeCategoryLabel =
    selectedCategories.length === 0
      ? "All programmes"
      : selectedCategories.length === 1
        ? formatProgrammeCategory(selectedCategories[0]!)
        : `${selectedCategories.length} categories`;

  return (
    <main className="mx-auto w-full max-w-[1680px] px-4 py-10 sm:px-6 sm:py-14 lg:px-10 xl:px-12">
      <header className="max-w-3xl">
        <p className="eyebrow">The almanac</p>
        <h1 className="mt-3 font-serif text-4xl font-semibold leading-tight tracking-tight text-foreground sm:text-5xl">
          Programmes students miss because they open once a year
        </h1>
        <p className="mt-4 max-w-2xl text-sm leading-6 text-muted-foreground sm:text-base sm:leading-7">
          {DESCRIPTION}
        </p>
      </header>

      <MatchedProgrammes />

      <FeedNavigationProvider>
        <section className="mt-10 border-y border-border py-6" aria-label="Programme categories">
          <p className="eyebrow">Browse by category</p>
          <div className="mt-4 flex flex-wrap gap-2">
            <Link
              href={categoryHref(query)}
              className={`inline-flex h-9 items-center rounded-md border px-3 text-sm font-medium transition-colors ${
                selectedCategories.length > 0
                  ? "border-border bg-transparent text-muted-foreground hover:bg-secondary/50 hover:text-foreground"
                  : "border-primary/20 bg-primary text-primary-foreground"
              }`}
            >
              All
            </Link>
            {PROGRAMME_CATEGORIES.map((category) => {
              const selected = selectedCategories.includes(category.value);
              return (
                <Link
                  key={category.value}
                  href={categoryHref(query, category.value)}
                  className={`inline-flex h-9 items-center rounded-md border px-3 text-sm font-medium transition-colors ${
                    selected
                      ? "border-primary/20 bg-primary text-primary-foreground"
                      : "border-border bg-transparent text-muted-foreground hover:bg-secondary/50 hover:text-foreground"
                  }`}
                >
                  {category.label}
                </Link>
              );
            })}
          </div>
        </section>

        <div className="mb-5 mt-10 flex flex-wrap items-center justify-between gap-4 border-b border-border pb-4">
          <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-2">
            <p className="eyebrow">{activeCategoryLabel}</p>
            {!failed && (
              <p className="tnum text-sm text-muted-foreground">
                {programmeCountLabel(total)}
              </p>
            )}
          </div>
          <ProgrammesListingControls
            facets={facets}
            facetsStatus={facetsStatus}
            path="/programmes"
            activeFilterLabel="programme filters"
            panelLabel="Programme filters"
            mobileDescription="Counted programme filters"
            searchPlaceholder="Search programmes..."
            searchLabel="Search programmes"
          />
        </div>

        <ProgrammesActiveFilterChips facets={facets} path="/programmes" />

        {failed ? (
          <section className="flex flex-col items-center rounded-xl border border-border bg-card px-5 py-16 text-center shadow-soft sm:py-20">
            <div className="rounded-lg border border-border bg-secondary/40 p-3 shadow-soft">
              <AlertCircle className="h-6 w-6 text-muted-foreground" aria-hidden="true" />
            </div>
            <p className="eyebrow mt-5">Programmes</p>
            <h2 className="mt-2 font-serif text-xl font-semibold text-foreground">
              The almanac could not be loaded.
            </h2>
            <p className="mt-2 max-w-md text-sm leading-6 text-muted-foreground">
              Check back soon; the official programme pages remain the source of truth.
            </p>
          </section>
        ) : programmes.length > 0 ? (
          <>
            <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {programmes.map((programme) => (
                <ProgrammeCard key={programme.slug} programme={programme} />
              ))}
            </div>

            {totalPages > 1 && (
              <nav
                aria-label="Programmes pagination"
                className="mt-8 flex flex-wrap items-center justify-center gap-4"
              >
                <Button variant="outline" size="sm" disabled={page <= 1} asChild={page > 1}>
                  {page > 1 ? (
                    <Link href={pageHref(page - 1, query)}>Previous</Link>
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
                    <Link href={pageHref(page + 1, query)}>Next</Link>
                  ) : (
                    "Next"
                  )}
                </Button>
              </nav>
            )}
          </>
        ) : (
          <section className="flex flex-col items-center rounded-xl border border-border bg-card px-5 py-16 text-center shadow-soft sm:py-20">
            <div className="rounded-lg border border-border bg-secondary/40 p-3 shadow-soft">
              <SearchX className="h-6 w-6 text-muted-foreground" aria-hidden="true" />
            </div>
            <p className="eyebrow mt-5">Programmes</p>
            <h2 className="mt-2 font-serif text-xl font-semibold text-foreground">
              No programmes match this view.
            </h2>
            <p className="mt-2 max-w-md text-sm leading-6 text-muted-foreground">
              Try another category or clear filters as the registry expands across annual
              student programmes.
            </p>
          </section>
        )}
      </FeedNavigationProvider>
    </main>
  );
}
