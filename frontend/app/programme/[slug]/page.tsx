import { CalendarDays, ExternalLink, Globe2 } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { getProgramme } from "@/lib/api";
import { formatDate } from "@/lib/date";
import {
  formatProgrammeCategory,
  getProgrammeStatusDisplay,
} from "@/lib/programmes";
import type { ProgrammeDetail, ProgrammeEditionItem } from "@/lib/types";

export const revalidate = 21600;

// Registers the route for on-demand ISR without prerendering any page at build
// time; without this Next leaves a dynamic segment fully per-request.
export async function generateStaticParams(): Promise<{ slug: string }[]> {
  return [];
}

const SITE_URL = "https://www.aspirova.org";

interface PageProps {
  params: Promise<{ slug: string }>;
}

function programmeUrl(slug: string): string {
  return `${SITE_URL}/programme/${encodeURIComponent(slug)}`;
}

function nonEmpty(value: string | null | undefined): string | undefined {
  const trimmed = value?.trim();
  return trimmed || undefined;
}

function buildProgrammeJsonLd(
  programme: ProgrammeDetail,
): Record<string, unknown> {
  const jsonLd: Record<string, unknown> = {
    "@context": "https://schema.org",
    "@type": "EducationalOccupationalProgram",
    name: programme.name,
    provider: {
      "@type": "Organization",
      name: programme.organiser,
    },
    url: programme.url,
  };

  const description = nonEmpty(programme.description);
  if (description) {
    jsonLd.description = description;
  }

  return jsonLd;
}

function serializeJsonLd(value: Record<string, unknown>): string {
  return JSON.stringify(value).replace(/</g, "\\u003c");
}

function statusClass(tone: "primary" | "neutral"): string {
  return tone === "primary"
    ? "border-primary/20 bg-primary text-primary-foreground"
    : "border-border bg-secondary/50 text-muted-foreground";
}

function dateRangeLabel(edition: ProgrammeEditionItem): string | null {
  const opens = edition.opens_at ? `Opens ${formatDate(edition.opens_at)}` : null;
  const closes = edition.closes_at ? `Closes ${formatDate(edition.closes_at)}` : null;
  if (opens && closes) return `${opens} - ${closes}`;
  return opens ?? closes;
}

function EditionRow({
  edition,
}: {
  edition: ProgrammeEditionItem;
}) {
  const status = getProgrammeStatusDisplay(edition, null);
  const range = dateRangeLabel(edition);

  return (
    <li className="rounded-xl border border-border bg-card p-5 shadow-soft">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="tnum font-serif text-xl font-semibold text-foreground">
          {edition.year}
        </h3>
        <span
          className={`inline-flex items-center rounded-md border px-3 py-1.5 text-sm font-medium ${statusClass(
            status.tone,
          )}`}
        >
          {status.text}
        </span>
      </div>
      {range && (
        <p className="tnum mt-3 flex items-center gap-2 text-sm text-muted-foreground">
          <CalendarDays className="size-4 shrink-0" aria-hidden="true" />
          {range}
        </p>
      )}
      {edition.source_url && (
        <a
          href={edition.source_url}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-3 inline-flex max-w-full items-center gap-1.5 break-all text-sm font-medium text-primary underline-offset-4 transition-colors hover:text-primary/80 hover:underline"
        >
          Edition source
          <ExternalLink className="size-3.5 shrink-0" aria-hidden="true" />
          <span className="sr-only"> (opens in a new tab)</span>
        </a>
      )}
    </li>
  );
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { slug } = await params;
  const programme = await getProgramme(slug);
  if (!programme) {
    notFound();
  }

  const description =
    programme.description?.slice(0, 160) ??
    `${programme.name} programme details, eligibility, and annual opening window.`;
  const canonicalUrl = programmeUrl(slug);

  return {
    title: { absolute: `${programme.name} | Aspirova` },
    description,
    alternates: { canonical: canonicalUrl },
    openGraph: {
      title: `${programme.name} | Aspirova`,
      description,
      type: "website",
      url: canonicalUrl,
    },
  };
}

export default async function ProgrammePage({ params }: PageProps) {
  const { slug } = await params;
  const programme = await getProgramme(slug);
  if (!programme) {
    notFound();
  }

  const status = getProgrammeStatusDisplay(
    programme.current_edition,
    programme.typical_window,
  );
  const isOpen = programme.current_edition?.status === "open";
  const currentSourceUrl = programme.current_edition?.source_url?.trim() || null;
  const showEditionSource =
    currentSourceUrl !== null && currentSourceUrl !== programme.url;
  const programmeJsonLd = buildProgrammeJsonLd(programme);

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: serializeJsonLd(programmeJsonLd) }}
      />
      <main className="mx-auto w-full max-w-5xl px-4 py-10 sm:py-14">
        <Link
          href="/programmes"
          className="inline-flex text-sm text-muted-foreground underline-offset-4 transition-colors hover:text-foreground hover:underline"
        >
          All programmes
        </Link>

        <header className="mt-8 border-b border-border pb-10">
          <p className="eyebrow">Programme field note</p>
          <h1 className="mt-3 break-words font-serif text-4xl font-semibold leading-tight tracking-tight text-foreground sm:text-5xl">
            {programme.name}
          </h1>
          <p className="mt-3 break-words text-sm font-medium text-muted-foreground sm:text-base">
            {programme.organiser}
          </p>

          <div className="mt-5 flex flex-wrap items-center gap-2">
            <Badge variant="secondary" className="eyebrow rounded-full px-2.5 py-1">
              {formatProgrammeCategory(programme.category)}
            </Badge>
            {programme.country && (
              <Badge variant="outline" className="eyebrow rounded-full px-2.5 py-1">
                {programme.country}
              </Badge>
            )}
          </div>

          <div
            className={`mt-6 inline-flex items-center rounded-md border px-3 py-1.5 text-sm font-medium ${statusClass(
              status.tone,
            )}`}
          >
            {status.text}
          </div>
        </header>

        <section
          aria-label="Programme official links"
          className="mt-8 flex max-w-3xl flex-col gap-5 border-b border-border pb-8 sm:flex-row sm:items-start sm:justify-between"
        >
          <div>
            <div className="flex flex-wrap gap-3">
              <Button size="lg" variant={isOpen ? "default" : "outline"} asChild>
                <a
                  href={programme.url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {isOpen ? "Official application page" : "Official programme page"}
                  <ExternalLink className="size-4" aria-hidden="true" />
                  <span className="sr-only"> (opens in a new tab)</span>
                </a>
              </Button>
              {showEditionSource && (
                <Button size="lg" variant="outline" asChild>
                  <a
                    href={currentSourceUrl ?? programme.url}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Current edition source
                    <ExternalLink className="size-4" aria-hidden="true" />
                    <span className="sr-only"> (opens in a new tab)</span>
                  </a>
                </Button>
              )}
            </div>
            <p className="mt-3 max-w-2xl text-xs leading-5 text-muted-foreground">
              Dates and eligibility must be verified on the official page for every
              annual edition.
            </p>
          </div>
        </section>

        <div className="mt-10 grid gap-8 lg:grid-cols-[minmax(0,2fr)_minmax(260px,1fr)]">
          <article className="min-w-0">
            <p className="eyebrow">Programme brief</p>
            <div className="mt-4 whitespace-pre-wrap text-base leading-8 text-foreground">
              {programme.description ?? "No programme description is available yet."}
            </div>

            {programme.eligibility && (
              <section className="mt-10 border-t border-border pt-8">
                <p className="eyebrow">Eligibility</p>
                <div className="mt-4 whitespace-pre-wrap text-base leading-8 text-foreground">
                  {programme.eligibility}
                </div>
              </section>
            )}
          </article>

          <aside className="space-y-6">
            <section className="rounded-xl border border-border bg-card p-5 shadow-soft">
              <p className="eyebrow">Typical window</p>
              <p className="mt-3 text-sm leading-6 text-card-foreground">
                {programme.typical_window ?? "Window to be confirmed"}
              </p>
            </section>
            <section className="rounded-xl border border-border bg-card p-5 shadow-soft">
              <p className="eyebrow">Official home</p>
              <a
                href={programme.url}
                target="_blank"
                rel="noopener noreferrer"
                className="mt-3 inline-flex max-w-full items-center gap-1.5 break-all text-sm font-medium text-primary underline-offset-4 transition-colors hover:text-primary/80 hover:underline"
              >
                <Globe2 className="size-4 shrink-0" aria-hidden="true" />
                {programme.url}
                <span className="sr-only"> (opens in a new tab)</span>
              </a>
            </section>
          </aside>
        </div>

        <section className="mt-14" aria-labelledby="programme-editions-title">
          <p className="eyebrow">Editions</p>
          <div className="mb-5 mt-2 flex flex-wrap items-end justify-between gap-3 border-b border-border pb-4">
            <h2
              id="programme-editions-title"
              className="font-serif text-2xl font-semibold leading-tight text-foreground sm:text-3xl"
            >
              Annual record
            </h2>
            <p className="tnum text-sm text-muted-foreground">
              {programme.editions.length}{" "}
              {programme.editions.length === 1 ? "edition" : "editions"}
            </p>
          </div>

          {programme.editions.length > 0 ? (
            <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              {programme.editions.map((edition) => (
                <EditionRow
                  key={`${edition.year}-${edition.status}-${edition.source_url ?? ""}`}
                  edition={edition}
                />
              ))}
            </ul>
          ) : (
            <div className="rounded-xl border border-border bg-card p-6 text-sm leading-6 text-muted-foreground shadow-soft">
              No annual editions have been recorded yet.
            </div>
          )}
        </section>
      </main>
    </>
  );
}
