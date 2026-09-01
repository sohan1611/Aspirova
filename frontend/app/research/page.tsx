import { AlertCircle } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import ProgrammeCard from "@/components/ProgrammeCard";
import { getProgrammes } from "@/lib/api";
import type { ProgrammeListItem } from "@/lib/types";

const TITLE = "Research fellowships & internships";
const DESCRIPTION =
  "Explore India's flagship IISc, IIT, NIT and TIFR research internships and fellowships, auto-curated with links to the official source.";

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  alternates: { canonical: "/research" },
  openGraph: {
    title: TITLE,
    description: DESCRIPTION,
    type: "website",
    url: "/research",
  },
};

interface PageProps {
  searchParams: Promise<{ category?: string }>;
}

// The research-shaped subset of the programmes registry. This page used to
// query only research_internship + fellowship, which rendered 25 of the 82
// active programmes - the other 57 were reachable only at /programmes, so the
// tab looked empty while the content already existed.
//
// scholarship, open_source, recurring_competition and conference stay out on
// purpose: they live in the registry but they are not research.
type ResearchCategory =
  | "research_internship"
  | "fellowship"
  | "international_research"
  | "corporate_research"
  | "government_internship";

const RESEARCH_CATEGORIES: Array<{ label: string; value: ResearchCategory }> = [
  { label: "Research internships", value: "research_internship" },
  { label: "Fellowships", value: "fellowship" },
  { label: "International research", value: "international_research" },
  { label: "Corporate research", value: "corporate_research" },
  { label: "Government internships", value: "government_internship" },
];

function parseResearchCategory(category?: string): ResearchCategory | undefined {
  return RESEARCH_CATEGORIES.find((entry) => entry.value === category)?.value;
}

function categoryHref(category?: ResearchCategory): string {
  if (!category) return "/research";
  return `/research?category=${encodeURIComponent(category)}`;
}

async function getResearchProgrammes(
  category?: ResearchCategory,
): Promise<ProgrammeListItem[]> {
  if (category) {
    const programmes = await getProgrammes({ category, limit: 100 });
    return programmes.items;
  }

  const results = await Promise.all(
    RESEARCH_CATEGORIES.map((entry) =>
      getProgrammes({ category: entry.value, limit: 100 }),
    ),
  );

  return results
    .flatMap((result) => result.items)
    .sort((a, b) =>
      a.name.localeCompare(b.name, undefined, { sensitivity: "base" }),
    );
}

export default async function ResearchPage({ searchParams }: PageProps) {
  const params = await searchParams;
  const selectedCategory = parseResearchCategory(params.category);
  let programmes: ProgrammeListItem[] = [];
  let failed = false;

  try {
    programmes = await getResearchProgrammes(selectedCategory);
  } catch {
    failed = true;
  }

  return (
    <main className="mx-auto w-full max-w-[1680px] px-4 py-10 sm:px-6 sm:py-14 lg:px-10 xl:px-12">
      <header className="max-w-3xl">
        <p className="eyebrow">The research track</p>
        <h1 className="mt-3 font-serif text-4xl font-semibold leading-tight tracking-tight text-foreground sm:text-5xl">
          Research fellowships & internships
        </h1>
        <p className="mt-4 max-w-2xl text-sm leading-6 text-muted-foreground sm:text-base sm:leading-7">
          Explore India&apos;s flagship institute-run research programmes from IISc, the IITs,
          NITs, TIFR and the national science academies. These recurring programmes are
          shown with the windows they usually open in; students must confirm the live cycle
          on the official page.
        </p>
      </header>

      <section className="mt-10 border-y border-border py-6" aria-label="Research categories">
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
          {RESEARCH_CATEGORIES.map((category) => {
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

      {failed ? (
        <section className="mt-10 flex flex-col items-center rounded-xl border border-border bg-card px-5 py-16 text-center shadow-soft sm:py-20">
          <div className="rounded-lg border border-border bg-secondary/40 p-3 shadow-soft">
            <AlertCircle className="h-6 w-6 text-muted-foreground" aria-hidden="true" />
          </div>
          <p className="eyebrow mt-5">Programmes</p>
          <h2 className="mt-2 font-serif text-xl font-semibold text-foreground">
            The research track could not be loaded.
          </h2>
          <p className="mt-2 max-w-md text-sm leading-6 text-muted-foreground">
            Check back soon; the official programme pages remain the source of truth.
          </p>
        </section>
      ) : (
        <section
          className="mt-10 grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3"
          aria-label="Flagship research programs"
        >
          {programmes.map((programme) => (
            <ProgrammeCard key={programme.slug} programme={programme} />
          ))}
        </section>
      )}
    </main>
  );
}
