import { CalendarClock, Clock, MapPin } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import BookmarkButton from "@/components/BookmarkButton";
import CompanyFavicon from "@/components/CompanyFavicon";
import ShareButton from "@/components/ShareButton";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { getOpportunity } from "@/lib/api";
import { cleanLocation } from "@/lib/cleanLocation";
import { getSourceLabel } from "@/lib/sourceLabel";
import type { OpportunityDetail } from "@/lib/types";

const CATEGORY_LABEL: Record<string, string> = {
  internship: "Internship",
  job: "Job",
};
const SITE_URL = "https://aspirova.vercel.app";

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

  const location = nonEmpty(cleanLocation(opportunity.location));
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
  const displayLocation = cleanLocation(opportunity.location);
  const jobPostingJsonLd = buildJobPostingJsonLd(opportunity, canonicalUrl);

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: serializeJsonLd(jobPostingJsonLd) }}
      />
      <main className="mx-auto max-w-prose px-4 py-8">
        <Link
          href="/"
          className="text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
        >
          ← Back to feed
        </Link>

        <div className="mt-4 flex items-start gap-4">
          <CompanyFavicon company={opportunity.company} />
          <div className="min-w-0">
            <h1 className="text-2xl font-bold tracking-tight text-foreground">
              {opportunity.title}
            </h1>
            <p className="mt-1 text-muted-foreground">
              {opportunity.company?.name}
            </p>
          </div>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          {opportunity.category && (
            <Badge variant="secondary">
              {CATEGORY_LABEL[opportunity.category] ?? opportunity.category}
            </Badge>
          )}
          {opportunity.is_remote && <Badge variant="secondary">Remote</Badge>}
          {displayLocation && (
            <Badge variant="outline" className="gap-1 font-normal">
              <MapPin className="h-3 w-3" />
              {displayLocation}
            </Badge>
          )}
          {sourceLabel && (
            <Badge variant="outline" className="font-normal">
              via {sourceLabel}
            </Badge>
          )}
        </div>

        {opportunity.deadline && (
          <div className="mt-4 inline-flex items-center gap-2 rounded-md border border-warning/30 bg-warning/10 px-3 py-2 text-sm font-medium text-warning">
            <Clock className="h-4 w-4 shrink-0" />
            Deadline: {new Date(opportunity.deadline).toLocaleDateString()}
            {opportunity.deadline_confidence !== "explicit" ? " (estimated)" : ""}
          </div>
        )}

        {opportunity.reopen_estimate && (
          <div className="mt-4 flex items-start gap-2 text-sm">
            <CalendarClock
              className="mt-0.5 size-4 shrink-0 text-muted-foreground"
              aria-hidden="true"
            />
            <div>
              <p className="font-medium text-foreground">
                Reopen estimate: Typically opens {opportunity.reopen_estimate.window}
              </p>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {opportunity.reopen_estimate.note} This is an estimate based on{" "}
                {opportunity.reopen_estimate.basis === "historical"
                  ? "past openings"
                  : "curated information"}
                .
              </p>
            </div>
          </div>
        )}

        <div className="mt-6 flex items-center gap-3">
          {/* Always links to the real source - we index and link out, we
              never mirror (Doc 01 sec 7 R1, Doc 04 sec 10). */}
          <Button size="lg" asChild>
            <a href={opportunity.apply_url} target="_blank" rel="noopener noreferrer">
              Apply at source ↗
            </a>
          </Button>
          <BookmarkButton slug={opportunity.slug} />
          <ShareButton slug={opportunity.slug} />
        </div>

        <article className="mt-8 leading-relaxed whitespace-pre-wrap text-foreground">
          {opportunity.description_raw}
        </article>
      </main>
    </>
  );
}
