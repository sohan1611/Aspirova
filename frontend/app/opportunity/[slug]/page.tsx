import { CalendarClock, Clock, MapPin } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import BookmarkButton from "@/components/BookmarkButton";
import CompanyFavicon from "@/components/CompanyFavicon";
import ShareButton from "@/components/ShareButton";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import OpportunityCard from "@/components/OpportunityCard";
import { getOpportunity, getSimilarOpportunities } from "@/lib/api";
import { formatDate } from "@/lib/date";
import { getSourceLabel } from "@/lib/sourceLabel";
import type { OpportunityDetail, OpportunityListItem } from "@/lib/types";

const CATEGORY_LABEL: Record<string, string> = {
  internship: "Internship",
  job: "Job",
};
const SITE_URL = "https://www.aspirova.org";

interface PageProps {
  params: Promise<{ slug: string }>;
}

function opportunityUrl(slug: string): string {
  return `${SITE_URL}/opportunity/${encodeURIComponent(slug)}`;
}

function nonEmpty(value: string | null | undefined): string | undefined {
  const trimmed = value?.trim();
  return trimmed || undefined;
}

function buildJobPostingJsonLd(
  opportunity: OpportunityDetail,
  canonicalUrl: string,
): Record<string, unknown> {
  const jsonLd: Record<string, unknown> = {
    "@context": "https://schema.org",
    "@type": "JobPosting",
    directApply: false,
    url: canonicalUrl,
  };

  const title = nonEmpty(opportunity.title);
  if (title) {
    jsonLd.title = title;
  }

  const description = nonEmpty(opportunity.description_raw);
  if (description) {
    jsonLd.description = description;
  }

  const companyName = nonEmpty(opportunity.company?.name);
  if (companyName) {
    jsonLd.hiringOrganization = { "@type": "Organization", name: companyName };
  }

  if (opportunity.posted_at) {
    jsonLd.datePosted = opportunity.posted_at;
  }

  if (opportunity.deadline && opportunity.deadline_confidence === "explicit") {
    jsonLd.validThrough = opportunity.deadline;
  }

  const location = nonEmpty(opportunity.location);
  if (opportunity.is_remote) {
    jsonLd.jobLocationType = "TELECOMMUTE";
    if (location) {
      jsonLd.applicantLocationRequirements = {
        "@type": "AdministrativeArea",
        name: location,
      };
    }
  } else if (location) {
    jsonLd.jobLocation = { "@type": "Place", name: location };
  }

  return jsonLd;
}

function serializeJsonLd(value: Record<string, unknown>): string {
  return JSON.stringify(value).replace(/</g, "\\u003c");
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { slug } = await params;
  const opportunity = await getOpportunity(slug);
  if (!opportunity) {
    return { title: "Opportunity not found" };
  }

  // The root layout's title template ("%s - Aspirova") appends the suffix -
  // do not repeat it here, or the <title> doubles up.
  const companyName = opportunity.company?.name ?? "";
  const title = `${opportunity.title}${companyName ? ` at ${companyName}` : ""}`;
  const description = opportunity.description_raw.slice(0, 160);
  const canonicalUrl = opportunityUrl(slug);

  return {
    title,
    description,
    alternates: { canonical: canonicalUrl },
    // openGraph.title has no automatic template applied (unlike <title>),
    // so the "- Aspirova" suffix is added explicitly here for share
    // previews on Twitter/LinkedIn/etc.
    openGraph: {
      title: `${title} - Aspirova`,
      description,
      type: "website",
      url: canonicalUrl,
    },
  };
}

export default async function OpportunityPage({ params }: PageProps) {
  const { slug } = await params;
  const opportunity = await getOpportunity(slug);
  if (!opportunity) {
    notFound();
  }

  const sourceLabel = getSourceLabel(opportunity.apply_url);
  const canonicalUrl = opportunityUrl(slug);
  const jobPostingJsonLd = buildJobPostingJsonLd(opportunity, canonicalUrl);
  let similarOpportunities: OpportunityListItem[] = [];

  try {
    similarOpportunities = await getSimilarOpportunities(slug);
  } catch {
    // Related opportunities are non-essential to the detail page.
  }

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: serializeJsonLd(jobPostingJsonLd) }}
      />
      <main className="mx-auto w-full max-w-5xl px-4 py-10 sm:py-14">
        <Link
          href="/"
          className="inline-flex text-sm text-muted-foreground underline-offset-4 transition-colors hover:text-foreground hover:underline"
        >
          ← All opportunities
        </Link>

        <header className="mt-8 max-w-3xl">
          <div className="flex items-center gap-3">
            <div className="flex shrink-0 items-center justify-center rounded-lg border border-border bg-secondary/50 p-1.5 shadow-soft">
              <CompanyFavicon company={opportunity.company} />
            </div>
            <p className="text-sm font-medium text-muted-foreground">
              {opportunity.company?.slug ? (
                <Link
                  href={`/companies/${opportunity.company.slug}`}
                  className="underline-offset-4 transition-colors hover:text-foreground hover:underline"
                >
                  {opportunity.company.name}
                </Link>
              ) : (
                opportunity.company?.name ?? "Independent listing"
              )}
            </p>
          </div>

          <h1 className="mt-6 font-serif text-4xl font-semibold leading-tight tracking-tight text-foreground sm:text-5xl">
            {opportunity.title}
          </h1>

          <div className="mt-6 flex flex-wrap items-center gap-2">
            {opportunity.category && (
              <Badge variant="secondary" className="eyebrow rounded-full px-2.5 py-1">
                {CATEGORY_LABEL[opportunity.category] ?? opportunity.category}
              </Badge>
            )}
            {opportunity.is_remote && (
              <Badge variant="secondary" className="eyebrow rounded-full px-2.5 py-1">
                Remote
              </Badge>
            )}
            {opportunity.is_hidden && (
              <Badge variant="heritage" className="rounded-full px-2.5 py-1">
                Hidden gem
              </Badge>
            )}
            {opportunity.location && (
              <Badge
                variant="outline"
                className="eyebrow gap-1 rounded-full px-2.5 py-1"
              >
                <MapPin className="size-3" aria-hidden="true" />
                {opportunity.location}
              </Badge>
            )}
            {sourceLabel && (
              <Badge variant="outline" className="eyebrow rounded-full px-2.5 py-1">
                via {sourceLabel}
              </Badge>
            )}
          </div>
        </header>

        <section
          aria-label="Application actions"
          className="mt-8 flex max-w-3xl flex-col gap-5 border-y border-border py-6 sm:flex-row sm:items-center sm:justify-between"
        >
          <div>
            {/* Always links to the real source - we index and link out, we
                never mirror (Doc 01 sec 7 R1, Doc 04 sec 10). */}
            <Button size="lg" asChild>
              <a href={opportunity.apply_url} target="_blank" rel="noopener noreferrer">
                {opportunity.company?.name
                  ? `Apply on ${opportunity.company.name} →`
                  : "Apply at the source →"}
              </a>
            </Button>
            <p className="mt-2 max-w-lg text-xs leading-5 text-muted-foreground">
              Opens the company&apos;s own listing — Aspirova never mirrors applications.
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-3">
            <BookmarkButton slug={opportunity.slug} />
            <ShareButton slug={opportunity.slug} />
          </div>
        </section>

        {opportunity.deadline && (
          <div className="mt-8 inline-flex items-center gap-2 rounded-md border border-warning/25 bg-warning/15 px-3 py-2 text-sm font-medium text-warning-foreground dark:text-warning">
            <Clock className="size-4 shrink-0" aria-hidden="true" />
            <span>
              Deadline:{" "}
              <span className="tnum">
                {formatDate(opportunity.deadline, "numeric")}
              </span>
              {opportunity.deadline_confidence !== "explicit" ? " (estimated)" : ""}
            </span>
          </div>
        )}

        {(opportunity.summary || opportunity.reopen_estimate) && (
          <aside className="mt-8 max-w-3xl rounded-xl border border-border bg-card p-6 shadow-soft sm:p-7">
            {opportunity.summary && (
              <div>
                <p className="eyebrow">AI summary</p>
                <p className="mt-3 whitespace-pre-wrap leading-7 text-foreground">
                  {opportunity.summary}
                </p>
              </div>
            )}

            {opportunity.reopen_estimate && (
              <div
                className={
                  opportunity.summary ? "mt-6 border-t border-border pt-6" : undefined
                }
              >
                <div className="flex items-center gap-2">
                  <CalendarClock
                    className="size-4 shrink-0 text-primary"
                    aria-hidden="true"
                  />
                  <p className="eyebrow">Reopen outlook</p>
                </div>
                <p className="tnum mt-3 font-medium text-foreground">
                  Typically opens {opportunity.reopen_estimate.window}
                </p>
                <p className="mt-1.5 text-sm leading-6 text-muted-foreground">
                  {opportunity.reopen_estimate.note} This is an estimate based on{" "}
                  {opportunity.reopen_estimate.basis === "historical"
                    ? "past openings"
                    : "curated information"}
                  .
                </p>
              </div>
            )}
          </aside>
        )}

        <article className="mt-10 max-w-3xl">
          <p className="eyebrow">Opportunity brief</p>
          <div className="mt-4 whitespace-pre-wrap text-base leading-8 text-foreground">
            {opportunity.description_raw}
          </div>
        </article>

        {similarOpportunities.length > 0 && (
          <section className="mt-14">
            <p className="eyebrow">More like this</p>
            <h2 className="mt-2 font-serif text-3xl font-semibold tracking-tight text-foreground">
              Related opportunities
            </h2>
            <div className="mt-6 grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
              {similarOpportunities.map((item) => (
                <OpportunityCard key={item.slug} item={item} />
              ))}
            </div>
          </section>
        )}
      </main>
    </>
  );
}
