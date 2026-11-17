import { withBuildFallback } from "@/lib/buildFallback";
import { ProgrammeBuildRecovery } from "@/components/BuildListingRecovery";
import { ListingEmpty, ListingSnapshotNotice } from "@/components/ListingFeedback";
import type { Metadata } from "next";
import Link from "@/components/HoverPrefetchLink";
import MatchedProgrammes from "@/components/MatchedProgrammes";
import {
  ProgrammesActiveFilterChips,
  type ProgrammesFacetsStatus,
} from "@/components/ProgrammesAdvancedFilters";
import ProgrammesListingControls from "@/components/ProgrammesListingControls";
import ProgrammeCard from "@/components/ProgrammeCard";
import ProgrammeAlmanac from "@/components/ProgrammeAlmanac";
import ProgrammeViewToggle, { type ProgrammeViewQuery } from "@/components/ProgrammeViewToggle";
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
} from "@/lib/programmesQuery";
import type { Facets } from "@/lib/types";

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
  searchParams: Promise<ProgrammeViewQuery>;
}

function categoryHref(query: ProgrammeViewQuery, category?: string): string {
  const search = new URLSearchParams();
  appendCurrentProgrammeFilters(search, query, "category");
  if (category) search.set("category", category);
  if ((Array.isArray(query.view) ? query.view[0] : query.view) === "browse") search.set("view", "browse");
  const queryString = search.toString();
  return queryString ? `/programmes?${queryString}` : "/programmes";
}

function pageHref(page: number, query: ProgrammeViewQuery): string {
  const search = new URLSearchParams({ page: String(page) });
  appendCurrentProgrammeFilters(search, query);
  if ((Array.isArray(query.view) ? query.view[0] : query.view) === "browse") search.set("view", "browse");
  return `/programmes?${search.toString()}`;
}

export default async function ProgrammesPage({ searchParams }: PageProps) {
  const query = await searchParams;
  const request = parseProgrammesRequest(query);
  const selectedCategories = parseParamValues(query.category).filter(
    (category) => category in PROGRAMME_CATEGORY_LABELS,
  );
  const page = request.page;

  const { data } = await withBuildFallback(() => loadProgrammes(request, PROGRAMMES_LIMIT), result => result.items.length);
  if (!data) return <main className="mx-auto max-w-6xl px-4 py-10"><h1 className="font-serif text-3xl font-bold">Programmes almanac</h1><ProgrammeBuildRecovery params={{ ...request, limit: PROGRAMMES_LIMIT }} pathname="/programmes" query={new URLSearchParams(Object.entries(query).flatMap(([key, value]) => (Array.isArray(value) ? value : value ? [value] : []).map(v => [key, v]))).toString()} /></main>;
  const { items: programmes, total } = data;
  let facets: Facets | null = null;
  let facetsStatus: ProgrammesFacetsStatus = "loaded";

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
    <main className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-6 sm:py-10">
      <header className="max-w-3xl">
        <p className="eyebrow">The almanac</p>
        <h1 className="mt-3 font-serif text-[1.875rem] font-bold leading-tight tracking-tight text-foreground sm:text-[2.25rem]">
          Programmes students miss because they open once a year
        </h1>
        <p className="mt-4 max-w-2xl text-sm leading-6 text-muted-foreground sm:text-base sm:leading-7">
          {DESCRIPTION}
        </p>
      </header>

      <MatchedProgrammes />

      <FeedNavigationProvider>
        <section className="mt-6 border-y border-border py-4 sm:mt-8 sm:py-5" aria-label="Programme categories">
          <p className="eyebrow">Browse by category</p>
          <div className="mt-3 flex flex-col items-start gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex w-full min-w-0 flex-wrap gap-2 lg:flex-1">
              <Link
                href={categoryHref(query)}
                className={`inline-flex min-h-11 items-center whitespace-nowrap rounded-full border px-3 text-sm font-medium transition-colors ${selectedCategories.length > 0
                    ? "border-border bg-card text-muted-foreground hover:bg-secondary hover:text-foreground"
                    : "border-primary bg-accent text-accent-foreground"
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
                    className={`inline-flex min-h-11 items-center whitespace-nowrap rounded-full border px-3 text-sm font-medium transition-colors ${selected
                        ? "border-primary bg-accent text-accent-foreground"
                        : "border-border bg-card text-muted-foreground hover:bg-secondary hover:text-foreground"
                      }`}
                  >
                    {category.label}
                  </Link>
                );
              })}
            </div>
            <ProgrammeViewToggle query={query} />
          </div>
        </section>

        <div className="mb-5 mt-6 flex flex-wrap items-center justify-between gap-4 border-b border-border pb-4 sm:mt-8">
          <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-2">
            <p className="eyebrow">{activeCategoryLabel}</p>
              <p className="tnum text-sm text-muted-foreground">
                {programmeCountLabel(total)}
              </p>

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

        <ListingSnapshotNotice loadedAt={data.loadedAt} expiresAt={data.expiresAt} />
        {programmes.length > 0 ? (
          <>
            {(Array.isArray(query.view) ? query.view[0] : query.view) !== "browse" && <ProgrammeAlmanac programmes={programmes} />}
            <div className="grid min-w-0 grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
              {programmes.map((programme) => (
                <ProgrammeCard key={programme.slug} programme={programme} />
              ))}
            </div>

            {totalPages > 1 && (
              <nav
                aria-label="Programmes pagination"
                className="mt-8 flex flex-wrap items-center justify-center gap-4"
              >
                <Button variant="outline" size="sm" className="min-h-11" disabled={page <= 1} asChild={page > 1}>
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
                  className="min-h-11"
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
          <ListingEmpty facets={facets} pathname="/programmes" query={new URLSearchParams(Object.entries(query).flatMap(([key, value]) => (Array.isArray(value) ? value : value ? [value] : []).map(v => [key, v]))).toString()} title="No programmes match this view." />
        )}
      </FeedNavigationProvider>
    </main>
  );
}
