import { AlertCircle, SearchX } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { getProgramme, getProgrammes } from "@/lib/api";
import {
  formatProgrammeCategory,
  getProgrammeStatusDisplay,
  programmePath,
  PROGRAMME_CATEGORIES,
} from "@/lib/programmes";
import type { ProgrammeListItem } from "@/lib/types";

const DESCRIPTION =
  "Research internships, fellowships, government and open-source programmes - with the windows they usually open in.";
const LIMIT = 50;

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
  searchParams: Promise<{
    category?: string;
    page?: string;
  }>;
}

function categoryHref(category?: string): string {
  if (!category) return "/programmes";
  return `/programmes?category=${encodeURIComponent(category)}`;
}

function pageHref(page: number, category?: string): string {
  const search = new URLSearchParams({ page: String(page) });
  if (category) search.set("category", category);
  return `/programmes?${search.toString()}`;
}

function programmeCountLabel(count: number): string {
  return `${count} ${count === 1 ? "programme" : "programmes"}`;
}

function truncateText(value: string | null | undefined, maxLength = 170): string {
  const trimmed = value?.trim();
  if (!trimmed) {
    return "Programme details vary by annual edition; verify dates and eligibility on the official page.";
  }
  if (trimmed.length <= maxLength) return trimmed;
  return `${trimmed.slice(0, maxLength - 1).trimEnd()}...`;
}

async function getProgrammeDescriptions(
  items: ProgrammeListItem[],
): Promise<Map<string, string | null>> {
  const entries = await Promise.all(
    items.map(async (item): Promise<[string, string | null]> => {
      try {
        const detail = await getProgramme(item.slug);
        return [item.slug, detail?.description ?? null];
      } catch {
        return [item.slug, null];
      }
    }),
  );
  return new Map(entries);
}

function ProgrammeCard({
  programme,
  description,
}: {
  programme: ProgrammeListItem;
  description: string | null | undefined;
}) {
  const status = getProgrammeStatusDisplay(
    programme.current_edition,
    programme.typical_window,
  );
  const statusClass =
    status.tone === "primary"
      ? "border-primary/20 bg-primary text-primary-foreground"
      : "border-border bg-secondary/50 text-muted-foreground";

  return (
    <Link
      href={programmePath(programme.slug)}
      className="group flex min-h-72 flex-col rounded-xl border border-border bg-card p-5 shadow-soft transition-[transform,box-shadow,border-color] duration-300 ease-premium hover:-translate-y-1 hover:border-primary/45 hover:[box-shadow:var(--shadow-md)] focus-visible:-translate-y-1 focus-visible:border-primary/45 focus-visible:[box-shadow:var(--shadow-md)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
    >
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="secondary" className="eyebrow rounded-full px-2.5 py-1">
          {formatProgrammeCategory(programme.category)}
        </Badge>
        {programme.country && (
          <Badge variant="outline" className="eyebrow rounded-full px-2.5 py-1">
            {programme.country}
          </Badge>
        )}
      </div>

      <div className="mt-5">
        <h2 className="break-words font-serif text-2xl font-semibold leading-tight text-card-foreground transition-colors duration-300 ease-premium group-hover:text-primary group-focus-visible:text-primary">
          {programme.name}
        </h2>
        <p className="mt-2 text-sm font-medium text-muted-foreground">
          {programme.organiser}
        </p>
      </div>

      <div
        className={`mt-5 inline-flex w-fit items-center rounded-md border px-3 py-1.5 text-sm font-medium ${statusClass}`}
      >
        {status.text}
      </div>

      <p className="mt-5 line-clamp-4 text-sm leading-6 text-muted-foreground">
        {truncateText(description)}
      </p>
    </Link>
  );
}

export default async function ProgrammesPage({ searchParams }: PageProps) {
  const query = await searchParams;
  const selectedCategory = query.category?.trim() || undefined;
  const page = Math.max(1, Number(query.page ?? "1") || 1);

  let programmes: ProgrammeListItem[] = [];
  let total = 0;
  let descriptions = new Map<string, string | null>();
  let failed = false;

  try {
    const data = await getProgrammes({
      category: selectedCategory,
      page,
      limit: LIMIT,
    });
    programmes = data.items;
    total = data.total;
    descriptions = await getProgrammeDescriptions(programmes);
  } catch {
    failed = true;
  }

  const totalPages = Math.max(1, Math.ceil(total / LIMIT));

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

      <section className="mt-10 border-y border-border py-6" aria-label="Programme categories">
        <p className="eyebrow">Browse by category</p>
        <div className="mt-4 flex flex-wrap gap-2">
          <Link
            href={categoryHref()}
            className={`inline-flex h-9 items-center rounded-md border px-3 text-sm font-medium transition-colors ${
              selectedCategory
                ? "border-border bg-transparent text-muted-foreground hover:bg-secondary/50 hover:text-foreground"
                : "border-primary/20 bg-primary text-primary-foreground"
            }`}
          >
            All
          </Link>
          {PROGRAMME_CATEGORIES.map((category) => {
            const selected = selectedCategory === category.value;
            return (
              <Link
                key={category.value}
                href={categoryHref(category.value)}
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

      <div className="mb-5 mt-10 flex items-center justify-between gap-4 border-b border-border pb-4">
        <p className="eyebrow">
          {selectedCategory
            ? formatProgrammeCategory(selectedCategory)
            : "All programmes"}
        </p>
        {!failed && (
          <p className="tnum text-sm text-muted-foreground">
            {programmeCountLabel(total)}
          </p>
        )}
      </div>

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
              <ProgrammeCard
                key={programme.slug}
                programme={programme}
                description={descriptions.get(programme.slug)}
              />
            ))}
          </div>

          {totalPages > 1 && (
            <nav
              aria-label="Programmes pagination"
              className="mt-8 flex flex-wrap items-center justify-center gap-4"
            >
              <Button variant="outline" size="sm" disabled={page <= 1} asChild={page > 1}>
                {page > 1 ? (
                  <Link href={pageHref(page - 1, selectedCategory)}>Previous</Link>
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
                  <Link href={pageHref(page + 1, selectedCategory)}>Next</Link>
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
            Try another category as the registry expands across annual student programmes.
          </p>
        </section>
      )}
    </main>
  );
}
